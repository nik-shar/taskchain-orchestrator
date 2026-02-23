"""OpenAI-backed planner for Step 7 controlled LLM enablement."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, request

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_TOOLS = {
    "summarize",
    "extract_entities",
    "extract_deadlines",
    "extract_action_items",
    "classify_priority",
    "search_incident_knowledge",
    "search_previous_issues",
    "build_incident_brief",
}


class _LLMPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class _LLMPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[_LLMPlanStep] = Field(default_factory=list)


def build_llm_plan(
    *,
    user_input: str,
    api_key: str,
    model: str,
    base_url: str,
    timeout_s: float,
    max_retries: int,
    backoff_s: float,
) -> list[dict[str, Any]]:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing")

    response_json = _request_with_retry(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_s=timeout_s,
        max_retries=max_retries,
        backoff_s=backoff_s,
        user_input=user_input,
    )
    plan = _parse_plan(response_json)
    _validate_allowed_tools(plan)

    normalized_steps: list[dict[str, Any]] = []
    for idx, step in enumerate(plan.steps):
        normalized_steps.append(
            {
                "id": step.id or f"llm_step_{idx + 1}",
                "tool": step.tool,
                "status": "pending",
                "args": step.args,
            }
        )
    if not normalized_steps:
        raise RuntimeError("LLM planner returned an empty plan")
    return normalized_steps


def _request_with_retry(
    *,
    api_key: str,
    model: str,
    base_url: str,
    timeout_s: float,
    max_retries: int,
    backoff_s: float,
    user_input: str,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return _request_once(
                api_key=api_key,
                model=model,
                base_url=base_url,
                timeout_s=timeout_s,
                user_input=user_input,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < max_retries and backoff_s > 0:
                time.sleep(backoff_s)

    if last_error is None:
        raise RuntimeError("LLM planner request failed")
    raise last_error


def _request_once(
    *,
    api_key: str,
    model: str,
    base_url: str,
    timeout_s: float,
    user_input: str,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict planner for an orchestration workflow. "
                    "Return JSON only with key 'steps'. Each step must contain 'tool' and optional 'args'. "
                    "Allowed tools: summarize, extract_entities, extract_deadlines, "
                    "extract_action_items, classify_priority, search_incident_knowledge, search_previous_issues. "
                    "build_incident_brief. For incident-like prompts, include both "
                    "search_incident_knowledge and search_previous_issues, then build_incident_brief, "
                    "before summarize."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Build a short plan (3-6 steps) for this request:\n"
                    f"{user_input}\n\n"
                    'Output schema: {"steps":[{"id":"optional","tool":"...","args":{...}}]}'
                ),
            },
        ],
    }

    req = request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"LLM planner request failed with status {exc.code}: {raw[:400]}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM planner request failed: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LLM planner returned non-JSON response") from exc


def _parse_plan(response_json: dict[str, Any]) -> _LLMPlan:
    choices = response_json.get("choices", [])
    if not choices:
        raise RuntimeError("LLM planner response missing choices")

    message = choices[0].get("message", {})
    content = message.get("content")

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        content_text = "".join(parts).strip()
    elif isinstance(content, str):
        content_text = content.strip()
    else:
        content_text = ""

    if not content_text:
        raise RuntimeError("LLM planner response had empty content")

    try:
        parsed = json.loads(content_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LLM planner content was not valid JSON") from exc

    return _LLMPlan.model_validate(parsed)


def _validate_allowed_tools(plan: _LLMPlan) -> None:
    for step in plan.steps:
        if step.tool not in ALLOWED_TOOLS:
            raise RuntimeError(f"Unsupported tool from LLM planner: {step.tool}")
