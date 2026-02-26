from __future__ import annotations

from orchestrator_api.app.models import Plan, Step, ToolCall
from orchestrator_api.app.planner import Planner


def test_deterministic_planner_incident_path_includes_retrieval() -> None:
    planner = Planner(mode="deterministic", llm_adapter=None, timeout_s=2.0)
    plan = planner.build_plan(
        "P1 alert: checkout outage detected, investigate incident and escalation.",
        context={
            "service": "saas-api",
            "severity": "P1",
            "start_time": "2026-02-14T10:00:00Z",
            "end_time": "2026-02-14T10:30:00Z",
        },
    )

    step_ids = [step.step_id for step in plan.steps]
    assert step_ids == [
        "extract_entities",
        "extract_deadlines",
        "extract_action_items",
        "classify_priority",
        "search_previous_issues",
        "search_incident_knowledge",
        "fetch_incident_policy",
        "summarize",
    ]
    rag_args = plan.steps[4].tool_calls[0].args
    assert rag_args["query"].startswith("P1 alert")
    assert rag_args["top_k"] == 6
    assert "source" not in rag_args
    assert "project" not in rag_args
    assert "opened_from" not in rag_args
    assert "opened_to" not in rag_args

    retrieval_args = plan.steps[5].tool_calls[0].args
    assert retrieval_args["query"].startswith("P1 alert")
    assert retrieval_args["service"] == "saas-api"
    assert retrieval_args["severity"] == "P1"
    assert retrieval_args["time_start"] == "2026-02-14T10:00:00Z"
    assert retrieval_args["time_end"] == "2026-02-14T10:30:00Z"

    policy_call = plan.steps[6].tool_calls[0]
    assert policy_call.tool == "fetch_company_reference"
    assert policy_call.args["source"] == "policy_v2"


def test_deterministic_planner_non_incident_path_unchanged() -> None:
    planner = Planner(mode="deterministic", llm_adapter=None, timeout_s=2.0)
    plan = planner.build_plan("Prepare an executive update for Atlas migration milestones.")

    step_ids = [step.step_id for step in plan.steps]
    assert step_ids == [
        "extract_entities",
        "extract_deadlines",
        "extract_action_items",
        "classify_priority",
        "summarize",
    ]


def test_deterministic_planner_adds_risk_step_when_risk_language_present() -> None:
    planner = Planner(mode="deterministic", llm_adapter=None, timeout_s=2.0)
    plan = planner.build_plan(
        "Prepare release update and include key risks, blockers, and mitigations."
    )

    step_ids = [step.step_id for step in plan.steps]
    assert "extract_risks" in step_ids
    risk_step = next(step for step in plan.steps if step.step_id == "extract_risks")
    assert risk_step.tool_calls[0].tool == "extract_risks"


def test_llm_planner_accepts_search_incident_knowledge() -> None:
    class SearchToolAdapter:
        def generate_structured(self, **kwargs):
            response_model = kwargs["response_model"]
            if response_model is Plan:
                return Plan(
                    steps=[
                        Step(
                            step_id="retrieve",
                            description="Find similar incidents",
                            tool_calls=[
                                ToolCall(tool="search_incident_knowledge", args={}),
                            ],
                        ),
                        Step(
                            step_id="summarize",
                            description="Summarize findings",
                            tool_calls=[ToolCall(tool="summarize", args={"max_words": 80})],
                        ),
                    ]
                )
            raise AssertionError("Unexpected response model")

    planner = Planner(mode="llm", llm_adapter=SearchToolAdapter(), timeout_s=2.0)
    plan = planner.build_plan(
        "Incident alert for checkout API outage.",
        context={
            "service": "saas-api",
            "severity": "P1",
            "start_time": "2026-02-14T10:00:00Z",
            "end_time": "2026-02-14T10:30:00Z",
        },
    )

    search_args = plan.steps[0].tool_calls[0].args
    summarize_args = plan.steps[1].tool_calls[0].args
    assert plan.steps[0].tool_calls[0].tool == "search_incident_knowledge"
    assert search_args["query"] == "Incident alert for checkout API outage."
    assert search_args["service"] == "saas-api"
    assert search_args["severity"] == "P1"
    assert search_args["time_start"] == "2026-02-14T10:00:00Z"
    assert search_args["time_end"] == "2026-02-14T10:30:00Z"
    assert summarize_args["text"] == "Incident alert for checkout API outage."
    assert summarize_args["max_words"] == 80


def test_deterministic_planner_issue_path_adds_previous_issue_search() -> None:
    planner = Planner(mode="deterministic", llm_adapter=None, timeout_s=2.0)
    plan = planner.build_plan(
        "Investigate repeated bug in user profile display and propose fix plan.",
        context={"project_key": "WLC"},
    )

    step_ids = [step.step_id for step in plan.steps]
    assert step_ids == [
        "extract_entities",
        "extract_deadlines",
        "extract_action_items",
        "classify_priority",
        "search_previous_issues",
        "summarize",
    ]
    rag_call = plan.steps[4].tool_calls[0]
    assert rag_call.tool == "search_previous_issues"
    assert rag_call.args["source"] == "jira"
    assert rag_call.args["project"] == "WLC"


def test_llm_planner_sanitizes_unsupported_tool_args() -> None:
    class SanitizingAdapter:
        def generate_structured(self, **kwargs):
            response_model = kwargs["response_model"]
            if response_model is Plan:
                return Plan(
                    steps=[
                        Step(
                            step_id="summarize",
                            description="Summarize findings",
                            tool_calls=[
                                ToolCall(
                                    tool="summarize",
                                    args={"text": "hello", "max_words": 80, "unknown": "x"},
                                )
                            ],
                        ),
                    ]
                )
            raise AssertionError("Unexpected response model")

    planner = Planner(mode="llm", llm_adapter=SanitizingAdapter(), timeout_s=2.0)
    plan = planner.build_plan("Summarize this task.")

    summarize_args = plan.steps[0].tool_calls[0].args
    assert summarize_args["text"] == "hello"
    assert summarize_args["max_words"] == 80
    assert "unknown" not in summarize_args
