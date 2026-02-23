"""LLM-backed tool call implementations for controlled executor enablement."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, request

from agent_orchestrator.tools.schemas import (
    BuildIncidentBriefInput,
    BuildIncidentBriefOutput,
    SummarizeInput,
    SummarizeOutput,
)


def build_openai_summarize_tool(
    *,
    api_key: str,
    model: str,
    base_url: str,
    timeout_s: float,
    max_retries: int,
    backoff_s: float,
):
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing")

    def _summarize(payload: SummarizeInput) -> SummarizeOutput:
        request_body = _summarize_request_body(model=model, payload=payload)
        response_json = _request_with_retry(
            api_key=api_key,
            base_url=base_url,
            timeout_s=timeout_s,
            max_retries=max_retries,
            backoff_s=backoff_s,
            request_body=request_body,
        )
        return _parse_summary(response_json)

    return _summarize


def build_openai_incident_brief_tool(
    *,
    api_key: str,
    model: str,
    base_url: str,
    timeout_s: float,
    max_retries: int,
    backoff_s: float,
):
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing")

    def _build_incident_brief(payload: BuildIncidentBriefInput) -> BuildIncidentBriefOutput:
        request_body = _incident_brief_request_body(model=model, payload=payload)
        response_json = _request_with_retry(
            api_key=api_key,
            base_url=base_url,
            timeout_s=timeout_s,
            max_retries=max_retries,
            backoff_s=backoff_s,
            request_body=request_body,
        )
        return _parse_incident_brief(response_json)

    return _build_incident_brief


def _request_with_retry(
    *,
    api_key: str,
    base_url: str,
    timeout_s: float,
    max_retries: int,
    backoff_s: float,
    request_body: dict[str, Any],
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return _request_once(
                api_key=api_key,
                base_url=base_url,
                timeout_s=timeout_s,
                request_body=request_body,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < max_retries and backoff_s > 0:
                time.sleep(backoff_s)

    if last_error is None:
        raise RuntimeError("LLM tool request failed")
    raise last_error


def _request_once(
    *,
    api_key: str,
    base_url: str,
    timeout_s: float,
    request_body: dict[str, Any],
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"

    req = request.Request(
        url=url,
        data=json.dumps(request_body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"LLM tool request failed with status {exc.code}: {message[:400]}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM tool request failed: {exc.reason}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LLM tool returned non-JSON response") from exc


def _summarize_request_body(*, model: str, payload: SummarizeInput) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You summarize text concisely. Return JSON only with key 'summary'. "
                    "Do not exceed the requested max word count."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Max words: {payload.max_words}\n\n"
                    f"Text:\n{payload.text}\n\n"
                    'Output schema: {"summary":"..."}'
                ),
            },
        ],
    }


def _incident_brief_request_body(
    *,
    model: str,
    payload: BuildIncidentBriefInput,
) -> dict[str, Any]:
    evidence = {
        "incident_knowledge": [
            {
                "title": item.title,
                "snippet": _compact_text(item.snippet, max_chars=280),
                "source_type": item.source_type,
                "source_id": item.source_id,
                "score": item.score,
                "why_selected": item.why_selected,
            }
            for item in payload.incident_knowledge[:5]
        ],
        "previous_issues": [
            {
                "ticket": item.ticket,
                "summary": _compact_text(item.summary, max_chars=280),
                "relevance": item.relevance,
                "source": item.source,
                "doc_id": item.doc_id,
                "chunk_id": item.chunk_id,
                "score": item.score,
                "retrieval_mode": item.retrieval_mode,
                "why_selected": item.why_selected,
            }
            for item in payload.previous_issues[:5]
        ],
    }
    evidence_json = json.dumps(evidence, ensure_ascii=True)

    return {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an incident response analyst. "
                    "Use ONLY provided evidence. Return JSON with keys exactly: "
                    "summary, similar_incidents, probable_causes, recommended_actions, "
                    "escalation_recommendation, confidence, citations. "
                    "confidence must be a number between 0 and 1. "
                    "Each citation item must contain: source_tool, reference, snippet, score, why_selected."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Incident query:\n{payload.query}\n\n"
                    f"Evidence JSON:\n{evidence_json}\n\n"
                    "Generate a concise, actionable incident brief."
                ),
            },
        ],
    }


def _parse_summary(response_json: dict) -> SummarizeOutput:
    parsed = _extract_json_content(response_json, context="summarize")
    return SummarizeOutput.model_validate(parsed)


def _parse_incident_brief(response_json: dict[str, Any]) -> BuildIncidentBriefOutput:
    parsed = _extract_json_content(response_json, context="build_incident_brief")
    normalized = _normalize_incident_brief_payload(parsed)
    return BuildIncidentBriefOutput.model_validate(normalized)


def _extract_json_content(response_json: dict[str, Any], *, context: str) -> dict[str, Any]:
    choices = response_json.get("choices", [])
    if not choices:
        raise RuntimeError(f"LLM {context} response missing choices")

    message = choices[0].get("message", {})
    content = message.get("content")

    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        text = "".join(parts).strip()
    else:
        text = ""

    if not text:
        raise RuntimeError(f"LLM {context} response content is empty")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM {context} content was not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"LLM {context} content must be a JSON object")
    return parsed


def _compact_text(text: str, *, max_chars: int) -> str:
    compacted = " ".join(text.split()).strip()
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 3].rstrip() + "..."


def _normalize_incident_brief_payload(payload: dict[str, Any]) -> dict[str, Any]:
    output = dict(payload)
    output["summary"] = _as_text(output.get("summary"))
    output["escalation_recommendation"] = _as_text(output.get("escalation_recommendation"))
    output["similar_incidents"] = _normalize_similar_incidents(output.get("similar_incidents"))
    output["probable_causes"] = _normalize_string_list(output.get("probable_causes"))
    output["recommended_actions"] = _normalize_string_list(output.get("recommended_actions"))
    output["citations"] = _normalize_citations(output.get("citations"))
    output["confidence"] = _normalize_confidence(output.get("confidence"))
    return output


def _normalize_similar_incidents(value: Any) -> list[str]:
    rows = _to_list(value)
    output: list[str] = []
    for row in rows:
        if isinstance(row, str):
            text = _as_text(row)
            if text:
                output.append(text)
            continue
        if isinstance(row, dict):
            ticket = _as_text(row.get("ticket"))
            summary = _as_text(row.get("summary"))
            if ticket and summary:
                output.append(f"{ticket}: {_compact_text(summary, max_chars=120)}")
            elif ticket:
                output.append(ticket)
            elif summary:
                output.append(_compact_text(summary, max_chars=120))
            continue
        text = _as_text(row)
        if text:
            output.append(text)
    return output[:6]


def _normalize_string_list(value: Any) -> list[str]:
    rows = _to_list(value)
    output: list[str] = []
    for row in rows:
        text = _as_text(row)
        if text:
            output.append(text)
    return output[:8]


def _normalize_citations(value: Any) -> list[dict[str, Any]]:
    rows = _to_list(value)
    output: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, str):
            text = _as_text(row)
            if not text:
                continue
            output.append(
                {
                    "source_tool": "build_incident_brief",
                    "reference": text,
                    "snippet": "",
                    "score": None,
                    "why_selected": None,
                }
            )
            continue

        if not isinstance(row, dict):
            continue

        source_tool = _as_text(row.get("source_tool")) or "build_incident_brief"
        reference = _as_text(row.get("reference"))
        snippet = _as_text(row.get("snippet"))
        if not reference:
            reference = _as_text(row.get("ticket")) or _as_text(row.get("doc_id"))
        if not snippet:
            snippet = _as_text(row.get("summary"))
        if not reference:
            continue
        output.append(
            {
                "source_tool": source_tool,
                "reference": reference,
                "snippet": snippet or "",
                "score": _optional_float(row.get("score")),
                "why_selected": _as_text(row.get("why_selected")),
            }
        )
    return output[:8]


def _normalize_confidence(value: Any) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        return 0.5
    return max(0.0, min(parsed, 1.0))


def _to_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
