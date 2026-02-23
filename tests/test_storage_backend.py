from __future__ import annotations

import importlib

import pytest


def test_create_app_rejects_missing_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePostgresStorage:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url

    monkeypatch.setenv("ORCHESTRATOR_DATABASE_URL", "postgresql://user:pass@localhost:5432/demo")
    monkeypatch.setenv("ORCHESTRATOR_PLANNER_MODE", "deterministic")
    monkeypatch.setenv("ORCHESTRATOR_EXECUTOR_MODE", "deterministic")
    from orchestrator_api.app import storage as storage_module

    monkeypatch.setattr(storage_module, "PostgresTaskStorage", FakePostgresStorage)
    from orchestrator_api import main as main_module

    importlib.reload(main_module)
    monkeypatch.setattr(main_module, "_load_env_file", lambda _path: None)
    monkeypatch.delenv("ORCHESTRATOR_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="ORCHESTRATOR_DATABASE_URL is required"):
        main_module.create_app()


def test_create_app_uses_postgres_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePostgresStorage:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url

    monkeypatch.setenv("ORCHESTRATOR_DATABASE_URL", "postgresql://user:pass@localhost:5432/demo")
    monkeypatch.setenv("ORCHESTRATOR_PLANNER_MODE", "deterministic")
    monkeypatch.setenv("ORCHESTRATOR_EXECUTOR_MODE", "deterministic")
    from orchestrator_api.app import storage as storage_module

    monkeypatch.setattr(storage_module, "PostgresTaskStorage", FakePostgresStorage)
    from orchestrator_api import main as main_module

    importlib.reload(main_module)
    monkeypatch.setattr(main_module, "PostgresTaskStorage", FakePostgresStorage)

    app = main_module.create_app()
    assert isinstance(app.state.storage, FakePostgresStorage)
    assert app.state.storage.database_url == "postgresql://user:pass@localhost:5432/demo"
