from __future__ import annotations

from fastapi.testclient import TestClient

from orchestrator_api.app.executor import SummarizeInput, SummarizeOutput, ToolSpec


def test_task_lifecycle(client: TestClient) -> None:
    create_response = client.post(
        "/tasks",
        json={"task": "Prepare summary for Project Atlas and Team Orion."},
    )
    assert create_response.status_code == 200
    task_id = create_response.json()["task_id"]

    queued = client.get(f"/tasks/{task_id}")
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"

    run_response = client.post(f"/tasks/{task_id}/run")
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["status"] == "succeeded"
    assert "execution_metadata" in run_payload["result_json"]
    assert run_payload["result_json"]["execution_metadata"]["total_tools"] >= 1
    step_ids = [step["step_id"] for step in run_payload["plan_json"]["steps"]]
    assert step_ids == [
        "extract_entities",
        "extract_deadlines",
        "extract_action_items",
        "classify_priority",
        "summarize",
    ]
    assert run_payload["verification_json"]["passed"] is True

    fetched = client.get(f"/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "succeeded"


def test_failed_verification_when_summary_omits_entities(client: TestClient) -> None:
    def bad_summary(_: SummarizeInput) -> SummarizeOutput:
        return SummarizeOutput(summary="short output without named references")

    client.app.state.executor.registry["summarize"] = ToolSpec(
        input_model=SummarizeInput,
        output_model=SummarizeOutput,
        fn=bad_summary,
    )

    create_response = client.post(
        "/tasks",
        json={"task": "Analyze Jupiter Program and Neptune Milestone."},
    )
    task_id = create_response.json()["task_id"]

    run_response = client.post(f"/tasks/{task_id}/run")
    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["status"] == "failed"
    assert payload["verification_json"]["passed"] is False
    assert (
        "Summary does not reference extracted entities." in payload["verification_json"]["reasons"]
    )
