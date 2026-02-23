from __future__ import annotations


def test_real_world_task_flow_succeeds(api_base_url: str, post_json) -> None:
    payload = {
        "task": (
            "Prepare an executive update for the Atlas Checkout migration. "
            "Stakeholders: Alice Chen, Raj Patel, Finance Ops. "
            "Include risks, mitigation owners, and next 30-day milestones."
        ),
        "context": {
            "project": "Atlas Checkout",
            "priority": "high",
            "deadline": "2026-03-31",
            "audience": "executive_leadership",
            "region": "us-central1",
        },
    }
    create_status, create_body = post_json(api_base_url, "/tasks", payload)
    assert create_status == 200
    task_id = create_body["task_id"]

    run_status, run_payload = post_json(api_base_url, f"/tasks/{task_id}/run", {})
    assert run_status == 200
    assert run_payload["status"] == "succeeded"
    assert run_payload["verification_json"]["passed"] is True
    assert len(run_payload["result_json"]["steps"]) >= 2


def test_create_task_rejects_empty_task(api_base_url: str, post_json) -> None:
    status, body = post_json(api_base_url, "/tasks", {"task": "", "context": {}})
    assert status == 422
    detail = body["detail"]
    assert any(item["loc"] == ["body", "task"] for item in detail)


def test_create_task_rejects_wrong_context_type(api_base_url: str, post_json) -> None:
    status, body = post_json(
        api_base_url,
        "/tasks",
        {"task": "Valid text", "context": ["not", "a", "dict"]},
    )
    assert status == 422
    detail = body["detail"]
    assert any(item["loc"] == ["body", "context"] for item in detail)


def test_run_unknown_task_returns_404(api_base_url: str, post_json, get_json) -> None:
    status, body = post_json(api_base_url, "/tasks/does-not-exist/run", {})
    assert status == 404
    assert body["detail"] == "Task not found"

    get_status, get_body = get_json(api_base_url, "/tasks/does-not-exist")
    assert get_status == 404
    assert get_body["detail"] == "Task not found"
