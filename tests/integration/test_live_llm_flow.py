from __future__ import annotations


def test_live_llm_task_flow(api_base_url_live_llm: str, post_json) -> None:
    create_status, create_body = post_json(
        api_base_url_live_llm,
        "/tasks",
        {
            "task": (
                "Draft a short executive brief about Atlas Checkout launch readiness. "
                "Reference Alice Chen and Raj Patel and include top risks."
            ),
            "context": {"project": "Atlas Checkout", "priority": "high"},
        },
    )
    assert create_status == 200
    task_id = create_body["task_id"]

    run_status, run_payload = post_json(
        api_base_url_live_llm,
        f"/tasks/{task_id}/run",
        {},
    )
    assert run_status == 200
    assert run_payload["status"] == "succeeded"
    assert run_payload["verification_json"]["passed"] is True
