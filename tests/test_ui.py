from __future__ import annotations

from fastapi.testclient import TestClient


def test_home_page_serves_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Orchestrator API Console" in response.text


def test_tools_endpoint_lists_registered_tools(client: TestClient) -> None:
    response = client.get("/tools")
    assert response.status_code == 200
    payload = response.json()
    tools = payload["tools"]
    assert "extract_entities" in tools
    assert "extract_deadlines" in tools
    assert "extract_action_items" in tools
    assert "classify_priority" in tools
    assert "summarize" in tools
    assert "fetch_company_reference" in tools
    assert "jira_search_tickets" in tools
    assert "metrics_query" in tools
    assert "logs_search" in tools
    assert "search_previous_issues" in tools
