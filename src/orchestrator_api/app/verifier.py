from __future__ import annotations

from typing import Any

from .models import Plan, VerificationResult

INCIDENT_EVIDENCE_TOOLS = {
    "search_incident_knowledge",
    "jira_search_tickets",
    "search_previous_issues",
}
POLICY_GOVERNANCE_SOURCES = {"policy_v1", "policy_v2", "governance_notes"}


def verify_execution(plan: Plan, execution_result: dict[str, Any]) -> VerificationResult:
    reasons: list[str] = []
    step_results = execution_result.get("steps", [])
    result_map = {step.get("step_id"): step for step in step_results if "step_id" in step}

    for step in plan.steps:
        step_result = result_map.get(step.step_id)
        if step_result is None:
            reasons.append(f"Missing result for step '{step.step_id}'.")
            continue

        tool_results = step_result.get("tool_results", [])
        for tool_call in step.tool_calls:
            matching = next(
                (item for item in tool_results if item.get("tool") == tool_call.tool),
                None,
            )
            if matching is None:
                reasons.append(
                    f"Missing tool result for tool '{tool_call.tool}' in step '{step.step_id}'."
                )
                continue
            if matching.get("status") != "ok":
                reasons.append(
                    f"Tool '{tool_call.tool}' failed in step '{step.step_id}': "
                    f"{matching.get('error', 'unknown error')}"
                )

    extracted_entities: list[str] = []
    summary_text = ""
    for step in step_results:
        for tool_result in step.get("tool_results", []):
            if tool_result.get("status") != "ok":
                continue
            if tool_result.get("tool") == "extract_entities":
                output = tool_result.get("output", {})
                extracted_entities = output.get("entities", [])
            if tool_result.get("tool") == "summarize":
                output = tool_result.get("output", {})
                summary_text = output.get("summary", "")

    if not summary_text:
        reasons.append("Missing summary output from summarize tool.")
    elif extracted_entities:
        lowered = summary_text.lower()
        if not any(entity.lower() in lowered for entity in extracted_entities):
            reasons.append("Summary does not reference extracted entities.")

    if _is_incident_plan(plan):
        has_incident_evidence = False
        has_policy_citation = False
        for step in step_results:
            for tool_result in step.get("tool_results", []):
                if tool_result.get("status") != "ok":
                    continue
                tool_name = tool_result.get("tool")
                if tool_name in INCIDENT_EVIDENCE_TOOLS:
                    has_incident_evidence = True
                if tool_name == "fetch_company_reference":
                    output = tool_result.get("output", {})
                    source = output.get("source") if isinstance(output, dict) else None
                    if source in POLICY_GOVERNANCE_SOURCES:
                        has_policy_citation = True

        if not has_incident_evidence:
            reasons.append(
                "Incident plan requires at least one successful evidence source from "
                "search_incident_knowledge, search_previous_issues, or jira_search_tickets."
            )
        if not has_policy_citation:
            reasons.append(
                "Incident plan requires at least one successful policy/governance citation "
                "via fetch_company_reference."
            )

    return VerificationResult(passed=not reasons, reasons=reasons)


def _is_incident_plan(plan: Plan) -> bool:
    for step in plan.steps:
        if "incident" in step.step_id.lower() or "incident" in step.description.lower():
            return True
        for tool_call in step.tool_calls:
            if tool_call.tool == "search_incident_knowledge":
                return True
            if tool_call.tool == "jira_search_tickets":
                text = str(tool_call.args.get("text", "")).lower()
                if "incident" in text:
                    return True
    return False
