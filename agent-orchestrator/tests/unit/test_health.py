from fastapi.testclient import TestClient
from agent_orchestrator.api.main import create_app
from agent_orchestrator.storage.memory import InMemoryTaskStorage


def test_health_endpoint() -> None:
    app = create_app(storage=InMemoryTaskStorage())
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_homepage_pipeline_ui_renders() -> None:
    app = create_app(storage=InMemoryTaskStorage())
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "Pipeline Explorer" in response.text
    assert "Step-by-Step Timeline" in response.text
    assert "Citations" in response.text
    assert "Incident Brief Trace" in response.text
