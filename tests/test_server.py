import pytest
from fastapi.testclient import TestClient

from api.server import app

client = TestClient(app)

# Editing is out of scope for TaskChain: agents perform edits through the MCP server,
# so these REST routes must not exist. Guarding them keeps the scope from creeping back.
REMOVED_EDITING_ROUTES = ["fix", "refine", "dispatch", "pulls"]


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ingest_invalid_url():
    response = client.post("/repos/ingest", json={"repo_url": "not-a-url"})
    assert response.status_code == 400


def test_ask_without_ingestion(mock_llm):
    """Q&A degrades gracefully: with no ingestion every context tier is empty, so
    the pipeline still answers rather than erroring, reporting empty sources."""
    response = client.post(
        "/repos/owner/repo/ask",
        json={"question": "What does this repo do?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["repo_id"] == "owner/repo"
    assert body["answer"] == "Stubbed answer."
    assert body["sources"]["code_files_read"] == []
    assert body["sources"]["history"] == []
    # Exactly one LLM call: the answering step (file selection is skipped because
    # there is no workspace for this repo).
    mock_llm.chat.completions.create.assert_called_once()


@pytest.mark.parametrize("route", REMOVED_EDITING_ROUTES)
def test_editing_routes_are_not_exposed(route):
    response = client.post(f"/repos/owner/repo/{route}", json={})
    assert response.status_code == 404
