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


def test_ask_without_ingestion():
    response = client.post(
        "/repos/owner/repo/ask",
        json={"question": "What does this repo do?"},
    )
    assert response.status_code == 500


def test_fix_without_ingestion():
    response = client.post(
        "/repos/owner/repo/fix",
        json={"issue_description": "Bug"},
    )
    assert response.status_code == 400
