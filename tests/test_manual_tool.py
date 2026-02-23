from __future__ import annotations

from fastapi.testclient import TestClient

from orchestrator_api import manual_tool


def test_targets_use_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_JIRA_BASE_URL", "http://jira.local:9001")
    monkeypatch.setenv("COMPANY_METRICS_BASE_URL", "http://metrics.local:9002")
    monkeypatch.setenv("COMPANY_LOGS_BASE_URL", "http://logs.local:9003")

    app = manual_tool.create_app()
    with TestClient(app) as client:
        response = client.get("/targets")

    assert response.status_code == 200
    assert response.json() == {
        "jira": "http://jira.local:9001",
        "metrics": "http://metrics.local:9002",
        "logs": "http://logs.local:9003",
    }


def test_create_ticket_proxies_payload(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_JIRA_BASE_URL", "http://jira.local:9001")
    captured: dict[str, object] = {}

    def fake_request(*, method: str, url: str, payload: dict[str, object] | None = None):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return 201, {"key": "OPS-999", "status": "New"}

    monkeypatch.setattr(manual_tool, "_request_json", fake_request)
    app = manual_tool.create_app()

    with TestClient(app) as client:
        response = client.post(
            "/jira/tickets",
            json={
                "project_key": "OPS",
                "issue_type": "Incident",
                "summary": "Synthetic outage event",
                "description": "Simulated create for manual testing",
                "severity": "P1",
                "labels": ["manual-test"],
            },
        )

    assert response.status_code == 201
    assert response.json()["key"] == "OPS-999"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://jira.local:9001/tickets"
    assert captured["payload"] == {
        "project_key": "OPS",
        "issue_type": "Incident",
        "summary": "Synthetic outage event",
        "description": "Simulated create for manual testing",
        "severity": "P1",
        "assignee": None,
        "labels": ["manual-test"],
    }


def test_logs_search_forwards_query_params(monkeypatch) -> None:
    monkeypatch.setenv("COMPANY_LOGS_BASE_URL", "http://logs.local:9003")
    captured: dict[str, object] = {}

    def fake_request(*, method: str, url: str, payload: dict[str, object] | None = None):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return 200, {"total": 1, "events": []}

    monkeypatch.setattr(manual_tool, "_request_json", fake_request)
    app = manual_tool.create_app()

    with TestClient(app) as client:
        response = client.get(
            "/logs/search",
            params={
                "service": "saas-api",
                "start_time": "2026-02-14T00:00:00Z",
                "end_time": "2026-02-14T01:00:00Z",
                "pattern": "timeout",
            },
        )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert captured["method"] == "GET"
    assert captured["payload"] is None
    assert captured["url"] == (
        "http://logs.local:9003/logs/search?service=saas-api"
        "&start_time=2026-02-14T00%3A00%3A00Z"
        "&end_time=2026-02-14T01%3A00%3A00Z"
        "&pattern=timeout"
    )
