"""Plan node with deterministic routing and LLM-mode fallback behavior."""

from __future__ import annotations

from typing import Any

from agent_orchestrator.config.settings import Settings, get_settings
from agent_orchestrator.graph.state import AgentState
from agent_orchestrator.graph.llm_planner import build_llm_plan as llm_build_plan
from agent_orchestrator.tools import build_registry, default_args_for_tool

INCIDENT_HINTS = ("incident", "outage", "sev", "latency", "error")
CORE_TOOLS = ("extract_entities", "classify_priority", "summarize")
INCIDENT_TOOLS = ("search_incident_knowledge", "search_previous_issues", "build_incident_brief")
TOOL_ARG_KEYS: dict[str, set[str]] = {
    name: set(spec.input_model.model_fields.keys()) for name, spec in build_registry().items()
}


def run(state: AgentState) -> AgentState:
    settings = get_settings()
    user_input = state.get("user_input", "")
    task_context = state.get("task_context", {})
    telemetry = dict(state.get("telemetry", {}))
    requested_mode = str(state.get("mode", "deterministic")).lower()

    if requested_mode == "llm":
        try:
            plan_steps = _build_llm_plan(user_input, settings=settings)
            plan_steps = _enforce_minimum_plan_shape(
                plan_steps,
                user_input=user_input,
                task_context=task_context if isinstance(task_context, dict) else {},
            )
            telemetry["planner"] = {
                "requested_mode": "llm",
                "effective_mode": "llm",
                "fallback_used": False,
                "provider": settings.llm_provider,
                "model": settings.llm_model,
            }
        except Exception as exc:  # noqa: BLE001
            plan_steps = _build_deterministic_plan(
                user_input, task_context=task_context if isinstance(task_context, dict) else {}
            )
            telemetry["planner"] = {
                "requested_mode": "llm",
                "effective_mode": "deterministic",
                "fallback_used": True,
                "fallback_reason": str(exc),
            }
            return {
                "plan_steps": plan_steps,
                "mode": "deterministic",
                "telemetry": telemetry,
            }
    else:
        plan_steps = _build_deterministic_plan(
            user_input, task_context=task_context if isinstance(task_context, dict) else {}
        )
        telemetry["planner"] = {
            "requested_mode": requested_mode,
            "effective_mode": "deterministic",
            "fallback_used": False,
        }

    return {"plan_steps": plan_steps, "telemetry": telemetry}


def _build_deterministic_plan(
    user_input: str,
    *,
    task_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    plan_steps: list[dict[str, Any]] = [
        {"id": "analyze_request", "tool": "summarize", "status": "pending"},
        {"id": "extract_entities", "tool": "extract_entities", "status": "pending"},
        {"id": "classify_priority", "tool": "classify_priority", "status": "pending"},
    ]

    if _is_incident_request(user_input, task_context=task_context):
        plan_steps.extend(
            [
                {
                    "id": "retrieve_incident_knowledge",
                    "tool": "search_incident_knowledge",
                    "status": "pending",
                },
                {
                    "id": "retrieve_previous_issues",
                    "tool": "search_previous_issues",
                    "status": "pending",
                },
                {
                    "id": "build_incident_brief",
                    "tool": "build_incident_brief",
                    "status": "pending",
                },
            ]
        )

    return plan_steps


def _build_llm_plan(user_input: str, *, settings: Settings) -> list[dict[str, Any]]:
    if settings.llm_provider.lower().strip() != "openai":
        raise RuntimeError(f"Unsupported LLM provider: {settings.llm_provider}")

    return llm_build_plan(
        user_input=user_input,
        api_key=settings.resolved_openai_api_key(),
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
        backoff_s=settings.llm_backoff_s,
    )


def _enforce_minimum_plan_shape(
    plan_steps: list[dict[str, Any]],
    *,
    user_input: str,
    task_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(plan_steps):
        if not isinstance(raw, dict):
            continue
        tool_name = raw.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            continue
        args = _normalize_tool_args(
            tool_name,
            raw.get("args"),
            user_input=user_input,
            task_context=task_context,
        )
        normalized.append(
            {
                "id": raw.get("id") or f"llm_step_{idx + 1}",
                "tool": tool_name,
                "status": "pending",
                "args": args,
            }
        )

    existing_tools = {step["tool"] for step in normalized if isinstance(step.get("tool"), str)}

    for tool_name in CORE_TOOLS:
        if tool_name not in existing_tools:
            normalized.append(
                {
                    "id": f"auto_{tool_name}",
                    "tool": tool_name,
                    "status": "pending",
                    "args": _normalize_tool_args(
                        tool_name,
                        None,
                        user_input=user_input,
                        task_context=task_context,
                    ),
                }
            )

    if _is_incident_request(user_input, task_context=task_context):
        for tool_name in INCIDENT_TOOLS:
            if tool_name not in existing_tools:
                normalized.append(
                    {
                        "id": f"auto_{tool_name}",
                        "tool": tool_name,
                        "status": "pending",
                        "args": _normalize_tool_args(
                            tool_name,
                            None,
                            user_input=user_input,
                            task_context=task_context,
                        ),
                    }
                )

    summarize_steps = [step for step in normalized if step.get("tool") == "summarize"]
    other_steps = [step for step in normalized if step.get("tool") != "summarize"]
    if _is_incident_request(user_input, task_context=task_context):
        other_steps = _ensure_incident_brief_after_retrieval(other_steps)
    if summarize_steps:
        final_summarize = summarize_steps[-1]
        final_args = _normalize_tool_args(
            "summarize",
            final_summarize.get("args"),
            user_input=user_input,
            task_context=task_context,
        )
        final_args["text"] = user_input
        final_summarize["args"] = final_args
    else:
        final_summarize = {
            "id": "auto_summarize",
            "tool": "summarize",
            "status": "pending",
            "args": _normalize_tool_args(
                "summarize",
                None,
                user_input=user_input,
                task_context=task_context,
            ),
        }

    return other_steps + [final_summarize]


def _ensure_incident_brief_after_retrieval(
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    brief_indices = [
        idx for idx, step in enumerate(steps) if step.get("tool") == "build_incident_brief"
    ]
    retrieval_indices = [
        idx
        for idx, step in enumerate(steps)
        if step.get("tool") in {"search_incident_knowledge", "search_previous_issues"}
    ]
    if not brief_indices or not retrieval_indices:
        return steps

    target_index = max(retrieval_indices)
    output = list(steps)
    for brief_idx in reversed(brief_indices):
        brief_step = output.pop(brief_idx)
        insert_at = min(target_index + 1, len(output))
        output.insert(insert_at, brief_step)
        target_index = insert_at
    return output


def _normalize_tool_args(
    tool_name: str,
    raw_args: dict[str, Any] | None,
    *,
    user_input: str,
    task_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = default_args_for_tool(tool_name, user_input=user_input, context=task_context)
    incoming = raw_args if isinstance(raw_args, dict) else {}
    merged = {**defaults, **incoming}
    allowed_keys = TOOL_ARG_KEYS.get(tool_name)
    if not allowed_keys:
        return merged
    return {key: value for key, value in merged.items() if key in allowed_keys}


def _is_incident_request(user_input: str, *, task_context: dict[str, Any] | None = None) -> bool:
    lowered = user_input.lower()
    if any(hint in lowered for hint in INCIDENT_HINTS):
        return True

    context = task_context if isinstance(task_context, dict) else {}
    severity = str(context.get("severity", "")).lower().strip()
    priority = str(context.get("priority", "")).lower().strip()
    return bool(severity or priority.startswith("p"))
