from __future__ import annotations

import importlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orchestrator_api.app.models import Plan, Task, TaskStatus, VerificationResult


class InMemoryPostgresStorage:
    """Test-only storage double that matches PostgresTaskStorage behavior."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._tasks: dict[str, Task] = {}

    def create_task(self, input_task: str, context: dict[str, Any] | None = None) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC)
        task = Task(
            task_id=task_id,
            input_task=input_task,
            context=context or {},
            status="queued",
            plan_json=None,
            result_json=None,
            verification_json=None,
            created_at=now,
            updated_at=now,
        )
        self._tasks[task_id] = task
        return task_id

    def get_task(self, task_id: str) -> Task | None:
        task = self._tasks.get(task_id)
        return task.model_copy(deep=True) if task else None

    def update_task(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        plan: Plan | None = None,
        result: dict[str, Any] | None = None,
        verification: VerificationResult | None = None,
    ) -> Task:
        current = self._tasks.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} does not exist")

        updated = current.model_copy(deep=True)
        if status is not None:
            updated.status = status
        if plan is not None:
            updated.plan_json = plan
        if result is not None:
            updated.result_json = result
        if verification is not None:
            updated.verification_json = verification
        updated.updated_at = datetime.now(tz=UTC)
        self._tasks[task_id] = updated
        return updated.model_copy(deep=True)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(
        "ORCHESTRATOR_DATABASE_URL",
        "postgresql://test:test@127.0.0.1:5432/orchestrator_test",
    )
    monkeypatch.setenv("ORCHESTRATOR_PLANNER_MODE", "deterministic")
    monkeypatch.setenv("ORCHESTRATOR_EXECUTOR_MODE", "deterministic")
    from orchestrator_api.app import storage as storage_module

    monkeypatch.setattr(storage_module, "PostgresTaskStorage", InMemoryPostgresStorage)
    from orchestrator_api import main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()
    with TestClient(app) as test_client:
        yield test_client
