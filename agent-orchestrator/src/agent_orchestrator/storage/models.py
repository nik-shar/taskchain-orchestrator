"""Storage models shared by API and persistence backends."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TaskRecord(BaseModel):
    """Persisted task record."""

    task_id: str
    prompt: str
    status: str
    created_at: datetime
    updated_at: datetime
    output: str | None = None
    verification: dict[str, Any] | None = None


class TaskRunRecord(BaseModel):
    """Persisted run artifacts for one workflow invocation."""

    run_id: int
    task_id: str
    status: str
    state_json: dict[str, Any]
    plan_json: list[dict[str, Any]] | None = None
    tool_results_json: dict[str, Any] | None = None
    verification_json: dict[str, Any] | None = None
    output: str | None = None
    created_at: datetime
    updated_at: datetime
