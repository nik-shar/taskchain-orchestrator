from fastapi.testclient import TestClient
from agent_orchestrator.api.main import create_app
from agent_orchestrator.config.settings import Settings
from agent_orchestrator.storage.memory import InMemoryTaskStorage


def test_task_create_run_get_roundtrip() -> None:
    app = create_app(
        storage=InMemoryTaskStorage(),
        settings_override=Settings(
            planner_mode="deterministic",
            executor_mode="deterministic",
        ),
    )
    client = TestClient(app)

    create_resp = client.post("/tasks", json={"prompt": "Investigate incident in payments service"})
    assert create_resp.status_code == 200
    task_id = create_resp.json()["task_id"]

    run_resp = client.post(f"/tasks/{task_id}/run")
    assert run_resp.status_code == 200
    payload = run_resp.json()
    assert payload["status"] == "completed"
    assert payload["output"]

    get_resp = client.get(f"/tasks/{task_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["task_id"] == task_id


def test_task_run_includes_runtime_mode_metadata() -> None:
    app = create_app(
        storage=InMemoryTaskStorage(),
        settings_override=Settings(
            planner_mode="deterministic",
            executor_mode="deterministic",
        ),
    )
    client = TestClient(app)

    create_resp = client.post("/tasks", json={"prompt": "Investigate incident in payments service"})
    task_id = create_resp.json()["task_id"]

    run_resp = client.post(f"/tasks/{task_id}/run")
    payload = run_resp.json()
    runtime = payload["verification"]["runtime"]

    assert runtime["planner"]["effective_mode"] == "deterministic"
    assert runtime["executor"]["effective_mode"] == "deterministic"


def test_task_run_latest_endpoint_returns_pipeline_artifacts() -> None:
    app = create_app(
        storage=InMemoryTaskStorage(),
        settings_override=Settings(
            planner_mode="deterministic",
            executor_mode="deterministic",
        ),
    )
    client = TestClient(app)

    create_resp = client.post(
        "/tasks", json={"prompt": "Investigate profile picture outage incident"}
    )
    task_id = create_resp.json()["task_id"]

    run_resp = client.post(f"/tasks/{task_id}/run")
    assert run_resp.status_code == 200

    latest_resp = client.get(f"/tasks/{task_id}/runs/latest")
    assert latest_resp.status_code == 200
    latest = latest_resp.json()
    assert latest["task_id"] == task_id
    assert isinstance(latest["state_json"], dict)
    assert isinstance(latest.get("plan_json"), list)
    assert isinstance(latest.get("tool_results_json"), dict)
    assert isinstance(latest.get("verification_json"), dict)
