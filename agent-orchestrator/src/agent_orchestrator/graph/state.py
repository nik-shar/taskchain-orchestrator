"""Typed state contract for LangGraph workflow."""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
    user_input: str
    mode: str
    executor_mode: str
    plan_steps: list[dict[str, Any]]
    tool_results: dict[str, Any]
    verification: dict[str, Any]
    final_output: str | None
    retry_count: int
    retry_budget: int
    telemetry: dict[str, Any]


def initial_state(
    task_id: str,
    user_input: str,
    mode: str = "llm",
    executor_mode: str = "llm",
    retry_budget: int = 2,
) -> AgentState:
    return {
        "task_id": task_id,
        "user_input": user_input,
        "mode": mode,
        "executor_mode": executor_mode,
        "plan_steps": [],
        "tool_results": {},
        "verification": {},
        "final_output": None,
        "retry_count": 0,
        "retry_budget": retry_budget,
        "telemetry": {},
    }
