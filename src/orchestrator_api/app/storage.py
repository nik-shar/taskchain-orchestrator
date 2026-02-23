"""PostgreSQL storage backend for orchestration tasks.

Beginner terms:
- Migration: creating/updating database tables before normal reads/writes.
- JSONB: PostgreSQL JSON type used for structured artifacts.
- CRUD: create, read, update, delete operations.
- Row factory: returns query rows as dict-like objects instead of tuples.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from .models import Plan, Task, TaskStatus, VerificationResult


class PostgresTaskStorage:
    """Thread-safe PostgreSQL-backed storage for Task records."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        self.database_url = database_url
        # Lock guards DB operations done through this storage instance.
        self._lock = threading.Lock()
        # Lazy import helper keeps error message clear if psycopg is missing.
        self._psycopg, self._dict_row, self._json_wrapper = self._load_psycopg()
        # Ensure schema exists before serving requests.
        self.migrate()

    def migrate(self) -> None:
        """Create required table and indexes if they do not already exist."""
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id UUID PRIMARY KEY,
                    input_task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    plan_json JSONB,
                    result_json JSONB,
                    verification_json JSONB,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status
                ON tasks(status)
                """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_updated_at
                ON tasks(updated_at DESC)
                """)
            conn.commit()

    def create_task(self, input_task: str, context: dict[str, Any] | None = None) -> str:
        """Insert a new queued task row and return its UUID string."""
        task_id = uuid.uuid4()
        now = datetime.now(tz=UTC)
        payload_context = context or {}
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id,
                    input_task,
                    status,
                    context_json,
                    plan_json,
                    result_json,
                    verification_json,
                    created_at,
                    updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    task_id,
                    input_task,
                    "queued",
                    self._json_wrapper(payload_context),
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            conn.commit()
        return str(task_id)

    def get_task(self, task_id: str) -> Task | None:
        """Read one task by id and convert DB row to typed Task model."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id::text = %s",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def update_task(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        plan: Plan | None = None,
        result: dict[str, Any] | None = None,
        verification: VerificationResult | None = None,
    ) -> Task:
        """Update selected task fields while keeping unspecified fields unchanged."""
        current = self.get_task(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} does not exist")

        # Merge partial updates with current values.
        next_status = status if status is not None else current.status
        next_plan = plan if plan is not None else current.plan_json
        next_result = result if result is not None else current.result_json
        next_verification = verification if verification is not None else current.verification_json
        updated_at = datetime.now(tz=UTC)

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = %s,
                    plan_json = %s,
                    result_json = %s,
                    verification_json = %s,
                    updated_at = %s
                WHERE task_id::text = %s
                """,
                (
                    next_status,
                    self._json_wrapper(next_plan.model_dump(mode="json")) if next_plan else None,
                    self._json_wrapper(next_result) if next_result is not None else None,
                    (
                        self._json_wrapper(next_verification.model_dump(mode="json"))
                        if next_verification
                        else None
                    ),
                    updated_at,
                    task_id,
                ),
            )
            conn.commit()

        refreshed = self.get_task(task_id)
        if refreshed is None:
            raise KeyError(f"Task {task_id} no longer exists")
        return refreshed

    def _connect(self) -> Any:
        """Open a psycopg connection that yields dict-like rows."""
        return self._psycopg.connect(self.database_url, row_factory=self._dict_row)

    @staticmethod
    def _load_psycopg() -> tuple[Any, Any, Any]:
        """Import psycopg and helpers with a friendly install hint on failure."""
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Json
        except ImportError as exc:  # pragma: no cover - exercised only without dependency
            raise RuntimeError(
                "PostgreSQL backend requires psycopg. Install with: "
                'python -m pip install "psycopg[binary]>=3.2,<4.0"'
            ) from exc
        return psycopg, dict_row, Json

    @staticmethod
    def _parse_json_object(raw: Any) -> dict[str, Any]:
        """Parse JSON-like value into dict; fall back to empty dict."""
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw
        if isinstance(parsed, dict):
            return parsed
        return {}

    @staticmethod
    def _parse_json_optional(raw: Any) -> dict[str, Any] | None:
        """Parse optional JSON-like value into dict or None."""
        if raw is None:
            return None
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw
        if isinstance(parsed, dict):
            return parsed
        return None

    @staticmethod
    def _parse_datetime(raw: Any) -> datetime:
        """Parse datetime value from database driver output."""
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            return datetime.fromisoformat(raw)
        raise TypeError(f"Unsupported datetime value: {type(raw)!r}")

    @classmethod
    def _row_to_task(cls, row: Any) -> Task:
        """Map one DB row to the canonical Task Pydantic model."""
        plan_raw = row["plan_json"]
        verification_raw = row["verification_json"]
        return Task(
            task_id=str(row["task_id"]),
            input_task=row["input_task"],
            context=cls._parse_json_object(row["context_json"]),
            status=row["status"],
            plan_json=(
                (
                    Plan.model_validate_json(plan_raw)
                    if isinstance(plan_raw, str)
                    else Plan.model_validate(plan_raw)
                )
                if plan_raw is not None
                else None
            ),
            result_json=cls._parse_json_optional(row["result_json"]),
            verification_json=(
                (
                    VerificationResult.model_validate_json(verification_raw)
                    if isinstance(verification_raw, str)
                    else VerificationResult.model_validate(verification_raw)
                )
                if verification_raw is not None
                else None
            ),
            created_at=cls._parse_datetime(row["created_at"]),
            updated_at=cls._parse_datetime(row["updated_at"]),
        )
