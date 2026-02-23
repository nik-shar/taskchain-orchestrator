from __future__ import annotations

from orchestrator_api.app.executor import (
    ClassifyPriorityInput,
    Executor,
    ExtractActionItemsInput,
    ExtractDeadlinesInput,
    classify_priority,
    extract_action_items,
    extract_deadlines,
)
from orchestrator_api.app.models import Plan, Step, ToolCall


def test_extract_deadlines_finds_multiple_formats() -> None:
    output = extract_deadlines(
        ExtractDeadlinesInput(
            text=(
                "Target date is 2026-03-31. "
                "Prepare rollback plan by Friday and final review in March 28, 2026."
            )
        )
    )
    assert "2026-03-31" in output.deadlines
    assert any(value.lower().startswith("by friday") for value in output.deadlines)
    assert any("march 28, 2026" in value.lower() for value in output.deadlines)


def test_extract_action_items_detects_owner_and_verb_lines() -> None:
    output = extract_action_items(
        ExtractActionItemsInput(
            text=(
                "Prepare release notes. "
                "Owner: Alice Chen to validate deployment checklist. "
                "Context line that is not an action."
            )
        )
    )
    assert any(item.lower().startswith("prepare") for item in output.action_items)
    assert any("owner:" in item.lower() for item in output.action_items)


def test_classify_priority_detects_critical_signals() -> None:
    output = classify_priority(
        ClassifyPriorityInput(
            text="Production down due to outage and sev1 incident in checkout flow."
        )
    )
    assert output.priority == "critical"
    assert "outage" in output.reasons


def test_executor_includes_tool_timing_metadata() -> None:
    executor = Executor(tool_timeout_s=2.0, retry_policy={"max_retries": 0})
    plan = Plan(
        steps=[
            Step(
                step_id="extract",
                description="Extract entities",
                tool_calls=[ToolCall(tool="extract_entities", args={"text": "Atlas Orion"})],
            ),
            Step(
                step_id="summarize",
                description="Summarize text",
                tool_calls=[
                    ToolCall(tool="summarize", args={"text": "Atlas Orion", "max_words": 10})
                ],
            ),
        ]
    )

    result = executor.execute_plan(plan)
    metadata = result["execution_metadata"]
    assert metadata["total_tools"] == 2
    assert metadata["error_count"] == 0
    assert isinstance(metadata["total_duration_ms"], (int, float))
    assert metadata["total_duration_ms"] >= 0

    for step in result["steps"]:
        for tool_result in step["tool_results"]:
            assert isinstance(tool_result["attempts"], int)
            assert tool_result["attempts"] >= 1
            assert isinstance(tool_result["duration_ms"], (int, float))
            assert tool_result["duration_ms"] >= 0
