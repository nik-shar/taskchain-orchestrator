from __future__ import annotations

from typing import Any

from orchestrator_api.app.executor import Executor, build_tool_registry
from orchestrator_api.app.models import Plan, Step, ToolCall
from orchestrator_api.app.planner import Planner


class FakeLLMAdapter:
    def generate_structured(  # noqa: PLR0913
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[Any],
        timeout_s: float,
    ) -> Any:
        _ = (system_prompt, user_prompt, timeout_s)
        if response_model is Plan:
            return Plan(
                steps=[
                    Step(
                        step_id="extract_entities",
                        description="Find entities",
                        tool_calls=[ToolCall(tool="extract_entities", args={"text": "A B"})],
                    ),
                    Step(
                        step_id="summarize",
                        description="Summarize text",
                        tool_calls=[
                            ToolCall(tool="summarize", args={"text": "A B", "max_words": 12})
                        ],
                    ),
                ]
            )
        if response_model.__name__ == "ExtractEntitiesOutput":
            return response_model.model_validate({"entities": ["Atlas", "Orion"]})
        if response_model.__name__ == "SummarizeOutput":
            return response_model.model_validate({"summary": "Atlas and Orion are referenced."})
        raise AssertionError(f"Unexpected response model: {response_model}")


def test_planner_uses_llm_mode_when_adapter_present() -> None:
    planner = Planner(mode="llm", llm_adapter=FakeLLMAdapter(), timeout_s=3.0)
    plan = planner.build_plan("Write a note about Atlas and Orion.")
    assert [step.step_id for step in plan.steps] == ["extract_entities", "summarize"]
    assert plan.steps[0].tool_calls[0].tool == "extract_entities"


def test_planner_falls_back_to_deterministic_when_llm_fails() -> None:
    class BrokenAdapter:
        def generate_structured(self, **_: Any) -> Any:
            raise RuntimeError("boom")

    planner = Planner(mode="llm", llm_adapter=BrokenAdapter(), timeout_s=3.0)
    plan = planner.build_plan("Write a note about Atlas and Orion.")
    assert [step.step_id for step in plan.steps] == [
        "extract_entities",
        "extract_deadlines",
        "extract_action_items",
        "classify_priority",
        "summarize",
    ]
    assert plan.steps[-1].tool_calls[0].tool == "summarize"


def test_executor_can_run_with_llm_backed_tool_registry() -> None:
    registry = build_tool_registry(llm_adapter=FakeLLMAdapter(), llm_timeout_s=3.0)
    executor = Executor(registry=registry, tool_timeout_s=2.0, retry_policy={"max_retries": 0})

    plan = Plan(
        steps=[
            Step(
                step_id="extract_entities",
                description="Find entities",
                tool_calls=[ToolCall(tool="extract_entities", args={"text": "Atlas Orion"})],
            ),
            Step(
                step_id="summarize",
                description="Summarize",
                tool_calls=[
                    ToolCall(tool="summarize", args={"text": "Atlas Orion", "max_words": 10})
                ],
            ),
        ]
    )
    result = executor.execute_plan(plan)

    first_output = result["steps"][0]["tool_results"][0]["output"]
    second_output = result["steps"][1]["tool_results"][0]["output"]
    assert first_output["entities"] == ["Atlas", "Orion"]
    assert "Atlas" in second_output["summary"]


def test_planner_normalizes_common_company_tool_args() -> None:
    class NormalizationAdapter:
        def generate_structured(self, **_: Any) -> Any:
            return Plan(
                steps=[
                    Step(
                        step_id="metrics",
                        description="Metrics query",
                        tool_calls=[ToolCall(tool="metrics_query", args={})],
                    ),
                    Step(
                        step_id="jira",
                        description="Jira query",
                        tool_calls=[
                            ToolCall(
                                tool="jira_search_tickets",
                                args={
                                    "project_key": "OPS",
                                    "start_time": "2026-02-14T10:00:00Z",
                                    "end_time": "2026-02-14T10:30:00Z",
                                },
                            )
                        ],
                    ),
                    Step(
                        step_id="summarize",
                        description="Summarize findings",
                        tool_calls=[ToolCall(tool="summarize", args={"max_words": 100})],
                    ),
                ]
            )

    planner = Planner(mode="llm", llm_adapter=NormalizationAdapter(), timeout_s=3.0)
    plan = planner.build_plan(
        "Investigate checkout latency and propose escalation.",
        context={
            "service": "saas-api",
            "start_time": "2026-02-14T10:00:00Z",
            "end_time": "2026-02-14T10:30:00Z",
            "project_key": "OPS",
        },
    )

    metrics_args = plan.steps[0].tool_calls[0].args
    jira_args = plan.steps[1].tool_calls[0].args
    summarize_args = plan.steps[2].tool_calls[0].args

    assert metrics_args["service"] == "saas-api"
    assert metrics_args["start_time"] == "2026-02-14T10:00:00Z"
    assert metrics_args["end_time"] == "2026-02-14T10:30:00Z"
    assert "start_time" not in jira_args
    assert "end_time" not in jira_args
    assert jira_args["project_key"] == "OPS"
    assert summarize_args["text"] == "Investigate checkout latency and propose escalation."
    assert summarize_args["max_words"] == 100
