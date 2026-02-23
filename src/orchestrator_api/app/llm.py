from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Protocol, TypeVar
from urllib import error, request

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)
logger = logging.getLogger(__name__)


class LLMAdapter(Protocol):
    """Interface for structured LLM completions."""

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        timeout_s: float,
    ) -> TModel: ...


class OpenAIChatCompletionsAdapter:
    """Small OpenAI adapter using the chat completions REST API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        max_retries: int = 1,
        backoff_s: float = 0.2,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self.backoff_s = max(0.0, backoff_s)

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        timeout_s: float,
    ) -> TModel:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__.lower(),
                    # `strict=True` requires every object schema to declare
                    # `additionalProperties: false`, which conflicts with
                    # flexible map fields such as tool args.
                    "strict": False,
                    "schema": response_model.model_json_schema(),
                },
            },
        }
        response_json = self._request_with_retry(payload, timeout_s=timeout_s)
        content = self._extract_content(response_json)
        parsed = json.loads(content)
        return response_model.model_validate(parsed)

    def _request_with_retry(self, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._request(payload, timeout_s=timeout_s)
            except (TimeoutError, ValueError, error.URLError, error.HTTPError) as exc:
                last_error = exc
                logger.warning(
                    "OpenAI request failed attempt=%d/%d model=%s reason=%s",
                    attempt + 1,
                    self.max_retries + 1,
                    self.model,
                    exc,
                )
                if attempt < self.max_retries and self.backoff_s > 0:
                    time.sleep(self.backoff_s)
        if last_error is None:
            raise RuntimeError("LLM request failed with unknown error")
        raise last_error

    def _request(self, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        if _trace_enabled():
            logger.warning(
                "LLM trace request provider=openai model=%s url=%s timeout_s=%s",
                self.model,
                url,
                timeout_s,
            )
        raw_payload = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=url,
            data=raw_payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=timeout_s) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")
            raise error.HTTPError(
                exc.url,
                exc.code,
                f"OpenAI API request failed: {raw_error}",
                exc.headers,
                exc.fp,
            ) from exc
        if _trace_enabled():
            logger.warning("LLM trace response provider=openai model=%s status=ok", self.model)
        return json.loads(body)

    @staticmethod
    def _extract_content(response_json: dict[str, Any]) -> str:
        choices = response_json.get("choices", [])
        if not choices:
            raise ValueError("OpenAI response did not contain choices")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_segments: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        text_segments.append(text)
            merged = "".join(text_segments).strip()
            if merged:
                return merged
        raise ValueError("OpenAI response content could not be parsed as text")


def build_llm_adapter_from_env() -> LLMAdapter | None:
    provider = os.getenv("ORCHESTRATOR_LLM_PROVIDER", "openai").lower()
    if provider != "openai":
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("ORCHESTRATOR_LLM_MODEL", "gpt-4o-mini")
    base_url = os.getenv("ORCHESTRATOR_LLM_BASE_URL", "https://api.openai.com/v1")
    max_retries = _env_int("ORCHESTRATOR_LLM_MAX_RETRIES", default=1)
    backoff_s = _env_float("ORCHESTRATOR_LLM_BACKOFF_S", default=0.2)

    return OpenAIChatCompletionsAdapter(
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_retries=max_retries,
        backoff_s=backoff_s,
    )


def _env_int(name: str, *, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, *, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _trace_enabled() -> bool:
    return os.getenv("ORCHESTRATOR_LLM_TRACE", "0").strip() == "1"
