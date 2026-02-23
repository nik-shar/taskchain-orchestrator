from __future__ import annotations

from orchestrator_api.app.models import Plan, Step, ToolCall
from orchestrator_api.app.verifier import verify_execution


def test_incident_verification_fails_without_evidence() -> None:
    plan = Plan(
        steps=[
            Step(
                step_id="search_incident_knowledge",
                description="Search similar incidents",
                tool_calls=[ToolCall(tool="search_incident_knowledge", args={"query": "p1 alert"})],
            ),
            Step(
                step_id="fetch_incident_policy",
                description="Fetch incident policy",
                tool_calls=[
                    ToolCall(
                        tool="fetch_company_reference",
                        args={"source": "policy_v2", "query": "incident escalation"},
                    )
                ],
            ),
            Step(
                step_id="summarize",
                description="Summarize findings",
                tool_calls=[ToolCall(tool="summarize", args={"text": "incident", "max_words": 50})],
            ),
        ]
    )
    execution_result = {
        "steps": [
            {
                "step_id": "search_incident_knowledge",
                "tool_results": [
                    {
                        "tool": "search_incident_knowledge",
                        "status": "error",
                        "error": "timeout",
                    }
                ],
            },
            {
                "step_id": "fetch_incident_policy",
                "tool_results": [
                    {
                        "tool": "fetch_company_reference",
                        "status": "ok",
                        "output": {
                            "source": "policy_v2",
                            "path": "company_sim/policies/policy_v2.md",
                            "matched": True,
                            "excerpt": "policy excerpt",
                        },
                    }
                ],
            },
            {
                "step_id": "summarize",
                "tool_results": [
                    {
                        "tool": "summarize",
                        "status": "ok",
                        "output": {"summary": "Incident summary."},
                    }
                ],
            },
        ]
    }

    verification = verify_execution(plan, execution_result)

    assert verification.passed is False
    assert any("successful evidence source" in reason for reason in verification.reasons)


def test_incident_verification_fails_without_policy_reference() -> None:
    plan = Plan(
        steps=[
            Step(
                step_id="search_incident_knowledge",
                description="Search similar incidents",
                tool_calls=[ToolCall(tool="search_incident_knowledge", args={"query": "p1 alert"})],
            ),
            Step(
                step_id="summarize",
                description="Summarize findings",
                tool_calls=[ToolCall(tool="summarize", args={"text": "incident", "max_words": 50})],
            ),
        ]
    )
    execution_result = {
        "steps": [
            {
                "step_id": "search_incident_knowledge",
                "tool_results": [
                    {
                        "tool": "search_incident_knowledge",
                        "status": "ok",
                        "output": {
                            "total": 1,
                            "confidence": "high",
                            "recommend_fallback": False,
                            "hits": [{"chunk_id": "jira:OPS-101:0"}],
                        },
                    }
                ],
            },
            {
                "step_id": "summarize",
                "tool_results": [
                    {
                        "tool": "summarize",
                        "status": "ok",
                        "output": {"summary": "Incident summary."},
                    }
                ],
            },
        ]
    }

    verification = verify_execution(plan, execution_result)

    assert verification.passed is False
    assert any("policy/governance citation" in reason for reason in verification.reasons)


def test_incident_verification_passes_with_evidence_and_policy() -> None:
    plan = Plan(
        steps=[
            Step(
                step_id="search_incident_knowledge",
                description="Search similar incidents",
                tool_calls=[ToolCall(tool="search_incident_knowledge", args={"query": "p1 alert"})],
            ),
            Step(
                step_id="fetch_incident_policy",
                description="Fetch incident policy",
                tool_calls=[
                    ToolCall(
                        tool="fetch_company_reference",
                        args={"source": "policy_v2", "query": "incident escalation"},
                    )
                ],
            ),
            Step(
                step_id="summarize",
                description="Summarize findings",
                tool_calls=[ToolCall(tool="summarize", args={"text": "incident", "max_words": 50})],
            ),
        ]
    )
    execution_result = {
        "steps": [
            {
                "step_id": "search_incident_knowledge",
                "tool_results": [
                    {
                        "tool": "search_incident_knowledge",
                        "status": "ok",
                        "output": {
                            "total": 1,
                            "confidence": "high",
                            "recommend_fallback": False,
                            "hits": [{"chunk_id": "jira:OPS-101:0"}],
                        },
                    }
                ],
            },
            {
                "step_id": "fetch_incident_policy",
                "tool_results": [
                    {
                        "tool": "fetch_company_reference",
                        "status": "ok",
                        "output": {
                            "source": "policy_v2",
                            "path": "company_sim/policies/policy_v2.md",
                            "matched": True,
                            "excerpt": "policy excerpt",
                        },
                    }
                ],
            },
            {
                "step_id": "summarize",
                "tool_results": [
                    {
                        "tool": "summarize",
                        "status": "ok",
                        "output": {"summary": "Incident summary with evidence."},
                    }
                ],
            },
        ]
    }

    verification = verify_execution(plan, execution_result)

    assert verification.passed is True
    assert verification.reasons == []
