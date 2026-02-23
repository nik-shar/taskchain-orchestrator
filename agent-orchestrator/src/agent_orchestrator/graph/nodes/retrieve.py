"""Retrieve node: lightweight retrieval-stage telemetry for orchestration."""

from __future__ import annotations

from agent_orchestrator.graph.state import AgentState


def run(state: AgentState) -> AgentState:
    telemetry = dict(state.get("telemetry", {}))
    retrieval_tools = [
        step.get("tool")
        for step in state.get("plan_steps", [])
        if step.get("tool") in {"search_incident_knowledge", "search_previous_issues"}
    ]
    telemetry["retrieval"] = {
        "planned_retrieval_tools": [tool for tool in retrieval_tools if isinstance(tool, str)],
        "count": len(retrieval_tools),
    }
    return {"telemetry": telemetry}
