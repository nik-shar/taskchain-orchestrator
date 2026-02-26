"""Execute node: schema-validated tool gateway execution."""

from __future__ import annotations

from typing import Any

from agent_orchestrator.config.settings import get_settings
from agent_orchestrator.graph.state import AgentState
from agent_orchestrator.tools import ToolExecutor, default_args_for_tool, resolve_registry


def run(state: AgentState) -> AgentState:
    settings = get_settings()
    requested_mode = str(state.get("executor_mode", settings.executor_mode)).lower()
    resolution = resolve_registry(
        requested_mode=requested_mode,
        provider=settings.llm_provider,
        api_key=settings.resolved_openai_api_key(),
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
        backoff_s=settings.llm_backoff_s,
    )
    executor = ToolExecutor(
        registry=resolution.registry,
        tool_timeout_s=settings.tool_timeout_s,
        max_retries=settings.tool_max_retries,
        backoff_s=settings.tool_retry_backoff_s,
    )

    user_input = state.get("user_input", "")
    task_context = state.get("task_context", {})
    plan_steps = state.get("plan_steps", [])
    tool_results = dict(state.get("tool_results", {}))
    telemetry = dict(state.get("telemetry", {}))
    telemetry["executor"] = {
        "requested_mode": resolution.requested_mode,
        "effective_mode": resolution.effective_mode,
        "fallback_used": resolution.effective_mode != resolution.requested_mode,
        "fallback_reason": resolution.fallback_reason,
    }

    history = telemetry.get("tool_execution", {}).get("events", [])
    events: list[dict[str, Any]] = list(history) if isinstance(history, list) else []
    iteration = int(state.get("retry_count", 0))
    for step in plan_steps:
        tool_name = step.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            continue
        existing = tool_results.get(tool_name)
        if isinstance(existing, dict) and existing.get("status") == "ok":
            continue

        args = step.get("args")
        args = _resolve_step_args(
            tool_name=tool_name,
            step_args=args if isinstance(args, dict) else None,
            user_input=user_input,
            task_context=task_context if isinstance(task_context, dict) else {},
            tool_results=tool_results,
        )

        result = executor.execute(tool_name, args)
        if result["status"] == "ok":
            tool_results[tool_name] = {
                "status": "ok",
                "data": result["output"],
                "implementation": result["implementation"],
                "attempts": result["attempts"],
                "duration_ms": result["duration_ms"],
            }
        else:
            tool_results[tool_name] = {
                "status": "failed",
                "error": result["error"],
                "implementation": result["implementation"],
                "attempts": result["attempts"],
                "duration_ms": result["duration_ms"],
            }

        events.append(
            {
                "iteration": iteration,
                "tool": tool_name,
                "status": result["status"],
                "implementation": result["implementation"],
                "attempts": result["attempts"],
                "duration_ms": result["duration_ms"],
            }
        )

    telemetry["tool_execution"] = {
        "events": events,
        "summary": {
            "executed_tools": len(events),
            "failed_tools": sum(1 for event in events if event["status"] != "ok"),
        },
    }

    return {"tool_results": tool_results, "telemetry": telemetry}


def _resolve_step_args(
    *,
    tool_name: str,
    step_args: dict[str, Any] | None,
    user_input: str,
    task_context: dict[str, Any] | None,
    tool_results: dict[str, Any],
) -> dict[str, Any]:
    args = (
        dict(step_args)
        if isinstance(step_args, dict)
        else default_args_for_tool(tool_name, user_input=user_input, context=task_context)
    )
    if tool_name != "build_incident_brief":
        return args

    incident_knowledge = _tool_result_rows(tool_results, "search_incident_knowledge")
    previous_issues = _tool_result_rows(tool_results, "search_previous_issues")
    args["query"] = str(args.get("query") or user_input)
    args["incident_knowledge"] = incident_knowledge
    args["previous_issues"] = previous_issues
    return args


def _tool_result_rows(tool_results: dict[str, Any], tool_name: str) -> list[dict[str, Any]]:
    payload = tool_results.get(tool_name)
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    rows = data.get("results")
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]
