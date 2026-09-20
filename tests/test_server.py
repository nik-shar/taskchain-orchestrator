from fastapi.testclient import TestClient

from api.server import app

client = TestClient(app)


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


def test_fix_without_ingestion():
    response = client.post(
        "/repos/owner/repo/fix",
        json={"issue_description": "Bug"},
    )
    assert response.status_code == 400
