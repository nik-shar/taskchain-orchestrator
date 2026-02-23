from __future__ import annotations


def test_incident_rag_flow_succeeds(api_base_url: str, post_json) -> None:
    create_status, create_body = post_json(
        api_base_url,
        "/tasks",
        {
            "task": (
                "P2 alert: intermittent API gateway errors impacting checkout. "
                "Investigate incident evidence and propose escalation with policy citations."
            ),
            "context": {
                "service": "saas-api",
                "severity": "P2",
                "start_time": "2026-02-14T09:59:00Z",
                "end_time": "2026-02-14T10:04:00Z",
            },
        },
    )
    assert create_status == 200
    task_id = create_body["task_id"]

    run_status, run_payload = post_json(api_base_url, f"/tasks/{task_id}/run", {})
    assert run_status == 200
    assert run_payload["status"] == "succeeded"

    step_ids = [step["step_id"] for step in run_payload["plan_json"]["steps"]]
    assert "search_incident_knowledge" in step_ids
    assert "fetch_incident_policy" in step_ids
    assert run_payload["verification_json"]["passed"] is True

    retrieval_results = []
    for step in run_payload["result_json"]["steps"]:
        for tool_result in step["tool_results"]:
            if tool_result.get("tool") == "search_incident_knowledge":
                retrieval_results.append(tool_result)

    assert retrieval_results
    retrieval_output = retrieval_results[0]
    assert retrieval_output["status"] == "ok"
    assert retrieval_output["output"]["total"] >= 1
    assert len(retrieval_output["output"]["hits"]) >= 1
