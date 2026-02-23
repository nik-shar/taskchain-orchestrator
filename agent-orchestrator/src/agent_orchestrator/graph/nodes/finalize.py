"""Finalize node: produce final user-facing output."""

from __future__ import annotations

from typing import Any

from agent_orchestrator.graph.state import AgentState


def run(state: AgentState) -> AgentState:
    tool_results = state.get("tool_results", {})
    summary_payload = tool_results.get("summarize", {})
    summary = summary_payload.get("data", {}).get("summary", "No summary available.")

    verification = state.get("verification", {})
    if not verification.get("passed", False):
        retry_info = verification.get("retry", {})
        final_output = (
            "Run completed with verification issues: "
            f"missing={verification.get('missing_tools', [])}, "
            f"failed={verification.get('failed_tools', [])}, "
            f"gates={verification.get('gate_failures', [])}, "
            f"retry_budget_exhausted={retry_info.get('budget_exhausted', False)}."
        )
    else:
        brief_payload = tool_results.get("build_incident_brief", {})
        brief_data = brief_payload.get("data", {}) if isinstance(brief_payload, dict) else {}
        if isinstance(brief_data, dict) and brief_data.get("summary"):
            final_output = _render_incident_brief(brief_data)
        else:
            final_output = summary

    return {"final_output": final_output}


def _render_incident_brief(brief: dict[str, Any]) -> str:
    summary = str(brief.get("summary", "")).strip()
    causes = _string_list(brief.get("probable_causes"))
    actions = _string_list(brief.get("recommended_actions"))
    incidents = _string_list(brief.get("similar_incidents"))
    escalation = str(brief.get("escalation_recommendation", "")).strip()
    confidence = brief.get("confidence")
    confidence_text = f"{float(confidence):.2f}" if isinstance(confidence, (int, float)) else "n/a"

    lines: list[str] = []
    if summary:
        lines.append(summary)
    lines.append(f"Confidence: {confidence_text}")
    if escalation:
        lines.append(f"Escalation: {escalation}")
    if causes:
        lines.append("Probable causes: " + "; ".join(causes[:3]))
    if actions:
        lines.append("Recommended actions: " + "; ".join(actions[:4]))
    if incidents:
        lines.append("Similar incidents: " + "; ".join(incidents[:3]))

    citations = brief.get("citations")
    if isinstance(citations, list) and citations:
        rendered_citations: list[str] = []
        for item in citations[:3]:
            if not isinstance(item, dict):
                continue
            reference = str(item.get("reference", "")).strip()
            source_tool = str(item.get("source_tool", "")).strip()
            if reference:
                rendered_citations.append(
                    f"{source_tool}:{reference}" if source_tool else reference
                )
        if rendered_citations:
            lines.append("Citations: " + ", ".join(rendered_citations))

    return " | ".join(lines)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            output.append(text)
    return output
