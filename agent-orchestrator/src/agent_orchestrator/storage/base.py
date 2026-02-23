"""Storage interfaces for agent orchestration task lifecycle."""

from __future__ import annotations

from typing import Any, Protocol

from agent_orchestrator.storage.models import TaskRecord, TaskRunRecord


class TaskStorage(Protocol):
    def migrate(self) -> None: ...

    def create_task(self, prompt: str) -> TaskRecord: ...

    def get_task(self, task_id: str) -> TaskRecord | None: ...

    def get_latest_task_run(self, task_id: str) -> TaskRunRecord | None: ...

    def update_task(
        self,
        task_id: str,
        *,
        status: str,
        output: str | None,
        verification: dict[str, Any] | None,
    ) -> TaskRecord: ...

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
    ) -> int: ...
