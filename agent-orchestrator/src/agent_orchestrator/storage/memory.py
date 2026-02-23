"""In-memory storage backend for tests only."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent_orchestrator.storage.models import TaskRecord, TaskRunRecord


class InMemoryTaskStorage:
    """Simple in-memory implementation for unit tests."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._task_runs: list[dict[str, Any]] = []
        self._next_run_id = 1

    def migrate(self) -> None:
        return None

    def create_task(self, prompt: str) -> TaskRecord:
        now = datetime.now(UTC)
        record = TaskRecord(
            task_id=str(uuid4()),
            prompt=prompt,
            status="created",
            output=None,
            verification=None,
            created_at=now,
            updated_at=now,
        )
        self._tasks[record.task_id] = record
        return record

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def get_latest_task_run(self, task_id: str) -> TaskRunRecord | None:
        for item in reversed(self._task_runs):
            if item.get("task_id") != task_id:
                continue
            return TaskRunRecord.model_validate(item)
        return None

    def update_task(
        self,
        task_id: str,
        *,
        status: str,
        output: str | None,
        verification: dict[str, Any] | None,
    ) -> TaskRecord:
        current = self._tasks.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} does not exist")
        updated = current.model_copy(
            update={
                "status": status,
                "output": output,
                "verification": verification,
                "updated_at": datetime.now(UTC),
            }
        )
        self._tasks[task_id] = updated
        return updated

    def create_task_run(
        self,
        *,
        task_id: str,
        status: str,
        state_json: dict[str, Any],
        plan_json: list[dict[str, Any]] | None,
        tool_results_json: dict[str, Any] | None,
        verification_json: dict[str, Any] | None,
        output: str | None,
    ) -> int:
        run_id = self._next_run_id
        self._next_run_id += 1
        now = datetime.now(UTC)
        self._task_runs.append(
            {
                "run_id": run_id,
                "task_id": task_id,
                "status": status,
                "state_json": state_json,
                "plan_json": plan_json,
                "tool_results_json": tool_results_json,
                "verification_json": verification_json,
                "output": output,
                "created_at": now,
                "updated_at": now,
            }
        )
        return run_id
