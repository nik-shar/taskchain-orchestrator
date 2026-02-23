from __future__ import annotations

import sys
from pathlib import Path

from agent_orchestrator.graph.nodes import plan as agent_plan
from agent_orchestrator.graph.state import initial_state
from agent_orchestrator.graph.workflow import build_graph


def _legacy_build_plan(task_text: str):
    project_root = Path(__file__).resolve().parents[3]
    legacy_src = project_root / "src"
    legacy_src_text = str(legacy_src)
    if legacy_src_text not in sys.path:
        sys.path.insert(0, legacy_src_text)

    from orchestrator_api.app.planner import build_plan  # type: ignore

    return build_plan(task_text)


def _tool_set_from_agent_plan(plan_steps: list[dict[str, object]]) -> set[str]:
    return {
        str(step.get("tool"))
        for step in plan_steps
        if isinstance(step, dict) and isinstance(step.get("tool"), str)
    }


def _tool_set_from_legacy_plan(plan_obj) -> set[str]:
    tools: set[str] = set()
    for step in plan_obj.steps:
        for tool_call in step.tool_calls:
            tools.add(tool_call.tool)
    return tools


def test_step6_real_world_graph_flow_passes() -> None:
    prompt = (
        "Prepare an executive update for the Atlas Checkout migration. "
        "Stakeholders: Alice Chen, Raj Patel, Finance Ops. "
        "Include risks, mitigation owners, and next 30-day milestones."
    )

    graph = build_graph(max_graph_loops=2)
    state = initial_state(task_id="step6-real-world", user_input=prompt, mode="deterministic")
    result = graph.invoke(state)

    assert result["verification"]["passed"] is True
    assert result["verification"]["incident_gate"]["required"] is False
    assert result["tool_results"]["summarize"]["status"] == "ok"
    assert result["tool_results"]["extract_entities"]["status"] == "ok"
    assert result["tool_results"]["classify_priority"]["status"] == "ok"
    assert result["final_output"]


def test_step6_incident_graph_flow_passes_with_rag_evidence() -> None:
    prompt = (
        "P2 alert: intermittent API gateway errors impacting checkout. "
        "Investigate incident evidence and propose escalation with policy citations."
    )

    graph = build_graph(max_graph_loops=2)
    state = initial_state(task_id="step6-incident", user_input=prompt, mode="deterministic")
    result = graph.invoke(state)

    assert result["verification"]["passed"] is True
    assert result["verification"]["incident_gate"]["required"] is True
    assert result["verification"]["incident_gate"]["passed"] is True

    incident_hits = result["tool_results"]["search_incident_knowledge"]["data"]["results"]
    previous_hits = result["tool_results"]["search_previous_issues"]["data"]["results"]
    brief = result["tool_results"]["build_incident_brief"]["data"]

    assert len(incident_hits) >= 1
    assert len(previous_hits) >= 1
    assert brief["summary"]
    assert isinstance(brief["citations"], list)
    assert "Confidence:" in result["final_output"]


def test_step6_parity_non_incident_tool_coverage_with_legacy_planner() -> None:
    prompt = (
        "Prepare summary for Project Atlas and Team Orion with owners, deadlines, and priorities."
    )

    legacy_plan = _legacy_build_plan(prompt)
    agent_result = agent_plan.run(
        {
            "task_id": "parity-non-incident",
            "mode": "deterministic",
            "user_input": prompt,
            "telemetry": {},
        }
    )

    legacy_tools = _tool_set_from_legacy_plan(legacy_plan)
    agent_tools = _tool_set_from_agent_plan(agent_result["plan_steps"])

    core = {"summarize", "extract_entities", "classify_priority"}
    assert core.issubset(legacy_tools)
    assert core.issubset(agent_tools)


def test_step6_parity_incident_retrieval_with_legacy_planner() -> None:
    prompt = (
        "P1 incident in checkout service with elevated latency and 5xx errors. "
        "Need incident knowledge and previous issue correlation."
    )

    legacy_plan = _legacy_build_plan(prompt)
    agent_result = agent_plan.run(
        {
            "task_id": "parity-incident",
            "mode": "deterministic",
            "user_input": prompt,
            "telemetry": {},
        }
    )

    legacy_tools = _tool_set_from_legacy_plan(legacy_plan)
    agent_tools = _tool_set_from_agent_plan(agent_result["plan_steps"])

    required_retrieval = {"search_incident_knowledge", "search_previous_issues"}
    assert required_retrieval.issubset(legacy_tools)
    assert required_retrieval.issubset(agent_tools)
