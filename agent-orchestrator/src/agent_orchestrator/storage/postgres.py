"""PostgreSQL-backed storage with automatic table migration."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from agent_orchestrator.storage.models import TaskRecord, TaskRunRecord


class PostgresTaskStorage:
    """Persist tasks and run artifacts in PostgreSQL."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("AGENT_ORCHESTRATOR_DATABASE_URL is required")
        self.database_url = database_url
        self._lock = threading.Lock()
        self._psycopg, self._dict_row, self._json_wrapper = self._load_psycopg()

    def migrate(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id UUID PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    context_json JSONB,
                    status TEXT NOT NULL,
                    output TEXT,
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
            # Compatibility path: if reusing the main orchestrator database, tasks may
            # still use `input_task` from the legacy schema.
            conn.execute("""
                ALTER TABLE tasks
                ADD COLUMN IF NOT EXISTS prompt TEXT
                """)
            conn.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = ANY (current_schemas(false))
                          AND table_name = 'tasks'
                          AND column_name = 'input_task'
                    ) THEN
                        UPDATE tasks
                        SET prompt = input_task
                        WHERE prompt IS NULL;
                    END IF;
                END $$;
                """)
            # Ensure columns used by this repo exist when attached to pre-existing tables.
            conn.execute("""
                ALTER TABLE tasks
                ADD COLUMN IF NOT EXISTS output TEXT
                """)
            conn.execute("""
                ALTER TABLE tasks
                ADD COLUMN IF NOT EXISTS context_json JSONB
                """)
            conn.execute("""
                ALTER TABLE tasks
                ADD COLUMN IF NOT EXISTS verification_json JSONB
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_runs (
                    run_id BIGSERIAL PRIMARY KEY,
                    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    plan_json JSONB,
                    tool_results_json JSONB,
                    verification_json JSONB,
                    output TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_runs_task_id
                ON task_runs(task_id)
                """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_runs_created_at
                ON task_runs(created_at DESC)
                """)
            conn.commit()

    def create_task(self, prompt: str, context: dict[str, str] | None = None) -> TaskRecord:
        task_id = uuid.uuid4()
        now = datetime.now(tz=UTC)
        context_payload = self._json_wrapper(context) if context else None
        with self._lock, self._connect() as conn:
            if self._has_input_task_column(conn):
                conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id,
                        prompt,
                        input_task,
                        context_json,
                        status,
                        output,
                        verification_json,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (task_id, prompt, prompt, context_payload, "created", None, None, now, now),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id,
                        prompt,
                        context_json,
                        status,
                        output,
                        verification_json,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (task_id, prompt, context_payload, "created", None, None, now, now),
                )
            conn.commit()
        created = self.get_task(str(task_id))
        if created is None:
            raise RuntimeError("Failed to load created task")
        return created

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id::text = %s",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def get_latest_task_run(self, task_id: str) -> TaskRunRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM task_runs
                WHERE task_id::text = %s
                ORDER BY run_id DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_task_run(row)

    def update_task(
        self,
        task_id: str,
        *,
        status: str,
        output: str | None,
        verification: dict[str, Any] | None,
    ) -> TaskRecord:
        updated_at = datetime.now(tz=UTC)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = %s,
                    output = %s,
                    verification_json = %s,
                    updated_at = %s
                WHERE task_id::text = %s
                """,
                (
                    status,
                    output,
                    self._json_wrapper(verification) if verification is not None else None,
                    updated_at,
                    task_id,
                ),
            )
            conn.commit()
        refreshed = self.get_task(task_id)
        if refreshed is None:
            raise KeyError(f"Task {task_id} does not exist")
        return refreshed

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
        now = datetime.now(tz=UTC)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO task_runs (
                    task_id,
                    status,
                    state_json,
                    plan_json,
                    tool_results_json,
                    verification_json,
                    output,
                    created_at,
                    updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING run_id
                """,
                (
                    task_id,
                    status,
                    self._json_wrapper(state_json),
                    self._json_wrapper(plan_json) if plan_json is not None else None,
                    (
                        self._json_wrapper(tool_results_json)
                        if tool_results_json is not None
                        else None
                    ),
                    (
                        self._json_wrapper(verification_json)
                        if verification_json is not None
                        else None
                    ),
                    output,
                    now,
                    now,
                ),
            ).fetchone()
            conn.commit()

        if row is None or row.get("run_id") is None:
            raise RuntimeError("Failed to persist task run")
        return int(row["run_id"])

    def _connect(self) -> Any:
        return self._psycopg.connect(self.database_url, row_factory=self._dict_row)

    @staticmethod
    def _has_input_task_column(conn: Any) -> bool:
        row = conn.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = ANY (current_schemas(false))
                  AND table_name = 'tasks'
                  AND column_name = 'input_task'
            ) AS present
            """).fetchone()
        return bool(row and row.get("present"))

    @staticmethod
    def _load_psycopg() -> tuple[Any, Any, Any]:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Json
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "PostgreSQL storage requires psycopg. "
                'Install with: python -m pip install "psycopg[binary]>=3.2,<4.0"'
            ) from exc
        return psycopg, dict_row, Json

    @staticmethod
    def _parse_json_optional(raw: Any) -> dict[str, Any] | None:
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
    def _parse_json_list_optional(raw: Any) -> list[dict[str, Any]] | None:
        if raw is None:
            return None
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw
        if not isinstance(parsed, list):
            return None
        output: list[dict[str, Any]] = []
        for item in parsed:
            if isinstance(item, dict):
                output.append(item)
        return output

    @staticmethod
    def _parse_datetime(raw: Any) -> datetime:
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            return datetime.fromisoformat(raw)
        raise TypeError(f"Unsupported datetime value: {type(raw)!r}")

    @classmethod
    def _row_to_task(cls, row: Any) -> TaskRecord:
        prompt = row.get("prompt")
        if prompt is None:
            prompt = row.get("input_task", "")
        return TaskRecord(
            task_id=str(row["task_id"]),
            prompt=prompt,
            context=cls._parse_json_optional(row.get("context_json")),
            status=row["status"],
            output=row["output"],
            verification=cls._parse_json_optional(row["verification_json"]),
            created_at=cls._parse_datetime(row["created_at"]),
            updated_at=cls._parse_datetime(row["updated_at"]),
        )

    @classmethod
    def _row_to_task_run(cls, row: Any) -> TaskRunRecord:
        return TaskRunRecord(
            run_id=int(row["run_id"]),
            task_id=str(row["task_id"]),
            status=str(row["status"]),
            state_json=cls._parse_json_optional(row["state_json"]) or {},
            plan_json=cls._parse_json_list_optional(row["plan_json"]),
            tool_results_json=cls._parse_json_optional(row["tool_results_json"]),
            verification_json=cls._parse_json_optional(row["verification_json"]),
            output=row["output"],
            created_at=cls._parse_datetime(row["created_at"]),
            updated_at=cls._parse_datetime(row["updated_at"]),
        )
