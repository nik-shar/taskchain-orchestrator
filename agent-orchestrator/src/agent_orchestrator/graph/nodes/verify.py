"""Verifier gates for tool integrity, consistency, and incident evidence."""

from __future__ import annotations

from typing import Any

from agent_orchestrator.graph.state import AgentState

REQUIRED_TOOLS = ("summarize", "extract_entities", "classify_priority")
INCIDENT_HINTS = ("incident", "outage", "sev", "latency", "error")
POLICY_TERMS = ("policy", "runbook")


def run(state: AgentState) -> AgentState:
    tool_results = state.get("tool_results", {})
    user_input = str(state.get("user_input", ""))

    missing = [tool for tool in REQUIRED_TOOLS if tool not in tool_results]
    failed = [
        tool
        for tool, payload in tool_results.items()
        if isinstance(payload, dict) and payload.get("status") == "failed"
    ]

    gate_failures: list[str] = []
    consistency_issues = _summary_entity_consistency_issues(tool_results)
    if consistency_issues:
        gate_failures.append("summary_entity_inconsistency")

    incident_gate = _incident_gate_result(user_input, tool_results)
    if incident_gate["required"] and not incident_gate["passed"]:
        gate_failures.extend(incident_gate["failures"])

    passed = not missing and not failed and not gate_failures

    retry_count = int(state.get("retry_count", 0)) + (0 if passed else 1)
    retry_budget = int(state.get("retry_budget", 2))

    verification = {
        "passed": passed,
        "missing_tools": missing,
        "failed_tools": failed,
        "gate_failures": gate_failures,
        "consistency_issues": consistency_issues,
        "incident_gate": incident_gate,
        "retry": {
            "count": retry_count,
            "budget": retry_budget,
            "remaining": max(0, retry_budget - retry_count),
            "budget_exhausted": retry_count >= retry_budget,
        },
    }

    return {
        "verification": verification,
        "retry_count": retry_count,
    }


def _summary_entity_consistency_issues(tool_results: dict[str, Any]) -> list[str]:
    summary = tool_results.get("summarize", {}).get("data", {}).get("summary", "")
    entities = tool_results.get("extract_entities", {}).get("data", {}).get("entities", [])

    if not isinstance(summary, str) or not summary.strip():
        return ["missing_or_empty_summary"]
    if not isinstance(entities, list) or not entities:
        return []

    lowered = summary.lower()
    missing_entities = [
        entity for entity in entities if isinstance(entity, str) and entity.lower() not in lowered
    ]

    threshold = max(1, len(entities) // 2)
    if len(missing_entities) > threshold:
        return [f"summary_missing_entities:{','.join(missing_entities[:5])}"]
    return []


def _incident_gate_result(user_input: str, tool_results: dict[str, Any]) -> dict[str, Any]:
    incident_required = any(hint in user_input.lower() for hint in INCIDENT_HINTS)
    if not incident_required:
        return {"required": False, "passed": True, "failures": []}

    failures: list[str] = []

    knowledge_results = (
        tool_results.get("search_incident_knowledge", {}).get("data", {}).get("results", [])
    )
    previous_issue_results = (
        tool_results.get("search_previous_issues", {}).get("data", {}).get("results", [])
    )

    if not isinstance(knowledge_results, list) or not knowledge_results:
        failures.append("missing_incident_knowledge_evidence")

    if not isinstance(previous_issue_results, list) or not previous_issue_results:
        failures.append("missing_previous_issue_evidence")

    failures.extend(
        _incident_citation_quality_failures(
            knowledge_results=knowledge_results,
            previous_issue_results=previous_issue_results,
        )
    )

    has_policy_citation = False
    if isinstance(knowledge_results, list):
        for item in knowledge_results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).lower()
            if any(term in title for term in POLICY_TERMS):
                has_policy_citation = True
                break

    if not has_policy_citation:
        failures.append("missing_policy_citation")

    return {
        "required": True,
        "passed": not failures,
        "failures": failures,
    }


def _incident_citation_quality_failures(
    *,
    knowledge_results: Any,
    previous_issue_results: Any,
) -> list[str]:
    failures: list[str] = []

    if isinstance(knowledge_results, list) and knowledge_results:
        has_incident_identifier = any(
            isinstance(item, dict) and str(item.get("source_id", "")).strip()
            for item in knowledge_results
        )
        has_incident_snippet = any(
            isinstance(item, dict) and str(item.get("snippet", "")).strip()
            for item in knowledge_results
        )
        if not has_incident_identifier:
            failures.append("missing_incident_citation_metadata")
        if not has_incident_snippet:
            failures.append("missing_incident_snippet_evidence")

    if isinstance(previous_issue_results, list) and previous_issue_results:
        has_previous_identifier = any(
            isinstance(item, dict)
            and (
                str(item.get("ticket", "")).strip()
                or str(item.get("doc_id", "")).strip()
                or str(item.get("chunk_id", "")).strip()
            )
            for item in previous_issue_results
        )
        has_previous_snippet = any(
            isinstance(item, dict) and str(item.get("summary", "")).strip()
            for item in previous_issue_results
        )
        if not has_previous_identifier:
            failures.append("missing_previous_issue_citation_metadata")
        if not has_previous_snippet:
            failures.append("missing_previous_issue_snippet_evidence")

    return failures
