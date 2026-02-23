import time

from agent_orchestrator.graph.nodes import execute
from agent_orchestrator.tools.gateway import ToolExecutor
from agent_orchestrator.tools.registry import ToolSpec
from agent_orchestrator.tools.schemas import SummarizeInput, SummarizeOutput


def test_tool_executor_success_validates_schema() -> None:
    executor = ToolExecutor()
    result = executor.execute("summarize", {"text": "alpha beta gamma", "max_words": 2})

    assert result["status"] == "ok"
    assert result["output"]["summary"] == "alpha beta"
    assert result["attempts"] == 1
    assert result["duration_ms"] >= 0


def test_tool_executor_timeout_and_retry() -> None:
    def slow_summary(_: SummarizeInput) -> SummarizeOutput:
        time.sleep(0.05)
        return SummarizeOutput(summary="too slow")

    registry = {
        "slow_tool": ToolSpec(
            input_model=SummarizeInput,
            output_model=SummarizeOutput,
            fn=slow_summary,
        )
    }

    executor = ToolExecutor(
        registry=registry,
        tool_timeout_s=0.01,
        max_retries=1,
        backoff_s=0.0,
    )
    result = executor.execute("slow_tool", {"text": "hello", "max_words": 5})

    assert result["status"] == "failed"
    assert result["attempts"] == 2
    assert "timed out" in result["error"]


def test_execute_node_records_tool_telemetry() -> None:
    state = {
        "task_id": "t1",
        "user_input": "Investigate payment latency incident",
        "executor_mode": "deterministic",
        "plan_steps": [
            {"id": "summarize_input", "tool": "summarize", "status": "pending"},
            {"id": "extract_entities", "tool": "extract_entities", "status": "pending"},
        ],
        "tool_results": {},
        "telemetry": {},
    }

    result = execute.run(state)

    assert result["tool_results"]["summarize"]["status"] == "ok"
    assert result["tool_results"]["extract_entities"]["status"] == "ok"

    summary = result["telemetry"]["tool_execution"]["summary"]
    assert summary["executed_tools"] == 2
    assert summary["failed_tools"] == 0
