"""Tool registry resolution for deterministic and LLM-enabled execution modes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

from agent_orchestrator.tools import deterministic
from agent_orchestrator.tools.llm import (
    build_openai_incident_brief_tool,
    build_openai_summarize_tool,
)
from agent_orchestrator.tools.schemas import (
    BuildIncidentBriefInput,
    BuildIncidentBriefOutput,
    ClassifyPriorityInput,
    ClassifyPriorityOutput,
    ExtractActionItemsInput,
    ExtractActionItemsOutput,
    ExtractDeadlinesInput,
    ExtractDeadlinesOutput,
    ExtractEntitiesInput,
    ExtractEntitiesOutput,
    SearchIncidentKnowledgeInput,
    SearchIncidentKnowledgeOutput,
    SearchPreviousIssuesInput,
    SearchPreviousIssuesOutput,
    SummarizeInput,
    SummarizeOutput,
)


@dataclass(frozen=True)
class ToolSpec:
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    fn: Callable[[BaseModel], BaseModel]
    implementation: str = "deterministic"


@dataclass(frozen=True)
class RegistryResolution:
    registry: dict[str, ToolSpec]
    requested_mode: str
    effective_mode: str
    fallback_reason: str | None = None


def build_registry() -> dict[str, ToolSpec]:
    return {
        "extract_entities": ToolSpec(
            input_model=ExtractEntitiesInput,
            output_model=ExtractEntitiesOutput,
            fn=deterministic.extract_entities,
        ),
        "extract_deadlines": ToolSpec(
            input_model=ExtractDeadlinesInput,
            output_model=ExtractDeadlinesOutput,
            fn=deterministic.extract_deadlines,
        ),
        "extract_action_items": ToolSpec(
            input_model=ExtractActionItemsInput,
            output_model=ExtractActionItemsOutput,
            fn=deterministic.extract_action_items,
        ),
        "classify_priority": ToolSpec(
            input_model=ClassifyPriorityInput,
            output_model=ClassifyPriorityOutput,
            fn=deterministic.classify_priority,
        ),
        "summarize": ToolSpec(
            input_model=SummarizeInput,
            output_model=SummarizeOutput,
            fn=deterministic.summarize,
        ),
        "search_incident_knowledge": ToolSpec(
            input_model=SearchIncidentKnowledgeInput,
            output_model=SearchIncidentKnowledgeOutput,
            fn=deterministic.search_incident_knowledge,
        ),
        "search_previous_issues": ToolSpec(
            input_model=SearchPreviousIssuesInput,
            output_model=SearchPreviousIssuesOutput,
            fn=deterministic.search_previous_issues,
        ),
        "build_incident_brief": ToolSpec(
            input_model=BuildIncidentBriefInput,
            output_model=BuildIncidentBriefOutput,
            fn=deterministic.build_incident_brief,
        ),
    }


def resolve_registry(
    *,
    requested_mode: str,
    provider: str,
    api_key: str,
    model: str,
    base_url: str,
    timeout_s: float,
    max_retries: int,
    backoff_s: float,
) -> RegistryResolution:
    normalized_mode = requested_mode.lower().strip()
    deterministic_registry = build_registry()

    if normalized_mode != "llm":
        return RegistryResolution(
            registry=deterministic_registry,
            requested_mode=normalized_mode,
            effective_mode="deterministic",
        )

    if provider.lower().strip() != "openai":
        return RegistryResolution(
            registry=deterministic_registry,
            requested_mode=normalized_mode,
            effective_mode="deterministic",
            fallback_reason=f"unsupported executor provider: {provider}",
        )

    if not api_key:
        return RegistryResolution(
            registry=deterministic_registry,
            requested_mode=normalized_mode,
            effective_mode="deterministic",
            fallback_reason="OPENAI_API_KEY is missing for executor llm mode",
        )

    try:
        llm_summarize = build_openai_summarize_tool(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_s=timeout_s,
            max_retries=max_retries,
            backoff_s=backoff_s,
        )
        llm_incident_brief = build_openai_incident_brief_tool(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_s=timeout_s,
            max_retries=max_retries,
            backoff_s=backoff_s,
        )
    except Exception as exc:  # noqa: BLE001
        return RegistryResolution(
            registry=deterministic_registry,
            requested_mode=normalized_mode,
            effective_mode="deterministic",
            fallback_reason=str(exc),
        )

    llm_registry = dict(deterministic_registry)
    llm_registry["summarize"] = ToolSpec(
        input_model=SummarizeInput,
        output_model=SummarizeOutput,
        fn=llm_summarize,
        implementation="llm",
    )
    llm_registry["build_incident_brief"] = ToolSpec(
        input_model=BuildIncidentBriefInput,
        output_model=BuildIncidentBriefOutput,
        fn=llm_incident_brief,
        implementation="llm",
    )

    return RegistryResolution(
        registry=llm_registry,
        requested_mode=normalized_mode,
        effective_mode="llm",
        fallback_reason=None,
    )


def list_tools() -> list[str]:
    return sorted(build_registry().keys())


def default_args_for_tool(
    tool_name: str,
    *,
    user_input: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context_payload = context if isinstance(context, dict) else {}
    if tool_name == "summarize":
        return {"text": user_input, "max_words": 80}
    if tool_name in {"extract_entities", "extract_deadlines", "extract_action_items"}:
        return {"text": user_input}
    if tool_name == "classify_priority":
        return {"text": _priority_text(user_input=user_input, context=context_payload)}
    if tool_name == "search_incident_knowledge":
        return {
            "query": user_input,
            "limit": 3,
            "service": _context_value(context_payload, "service"),
            "severity": _context_value(context_payload, "severity"),
        }
    if tool_name == "search_previous_issues":
        return {
            "query": user_input,
            "limit": 3,
            "service": _context_value(context_payload, "service"),
            "severity": _context_value(context_payload, "severity"),
        }
    if tool_name == "build_incident_brief":
        return {"query": user_input, "incident_knowledge": [], "previous_issues": []}
    return {}


def _context_value(context: dict[str, Any], key: str) -> str | None:
    raw = context.get(key)
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _priority_text(*, user_input: str, context: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in ("priority", "severity", "status"):
        value = _context_value(context, key)
        if value:
            lines.append(f"{key.title()}: {value}")
    if not lines:
        return user_input
    lines.append(f"Summary: {user_input}")
    return "\n".join(lines)
