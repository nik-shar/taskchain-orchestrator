from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate tasks from a SQLite DB file to a PostgreSQL database."
    )
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=Path("data/tasks.db"),
        help="Path to source SQLite database file (default: data/tasks.db).",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        required=True,
        help="PostgreSQL connection URL.",
    )
    return parser.parse_args()


def _parse_json(raw: str | None, *, default: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if raw is None:
        return default
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        return parsed
    raise TypeError(f"Expected JSON object, received {type(parsed)!r}")


def _load_rows(sqlite_path: Path) -> list[sqlite3.Row]:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT
                task_id,
                input_task,
                status,
                context_json,
                plan_json,
                result_json,
                verification_json,
                created_at,
                updated_at
            FROM tasks
            """).fetchall()
    return rows


def _ensure_postgres_schema(conn: Any) -> None:
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


def migrate(*, sqlite_path: Path, database_url: str) -> int:
    rows = _load_rows(sqlite_path)

    import psycopg
    from psycopg.types.json import Json

    with psycopg.connect(database_url) as conn:
        _ensure_postgres_schema(conn)

        for row in rows:
            context_payload = _parse_json(row["context_json"], default={}) or {}
            plan_payload = _parse_json(row["plan_json"])
            result_payload = _parse_json(row["result_json"])
            verification_payload = _parse_json(row["verification_json"])
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
                ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                ON CONFLICT (task_id) DO UPDATE
                SET input_task = EXCLUDED.input_task,
                    status = EXCLUDED.status,
                    context_json = EXCLUDED.context_json,
                    plan_json = EXCLUDED.plan_json,
                    result_json = EXCLUDED.result_json,
                    verification_json = EXCLUDED.verification_json,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    row["task_id"],
                    row["input_task"],
                    row["status"],
                    Json(context_payload),
                    Json(plan_payload) if plan_payload is not None else None,
                    Json(result_payload) if result_payload is not None else None,
                    Json(verification_payload) if verification_payload is not None else None,
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        conn.commit()

    return len(rows)


def main() -> None:
    args = _parse_args()
    migrated = migrate(sqlite_path=args.sqlite_path, database_url=args.database_url)
    print(f"Migrated {migrated} task row(s) from {args.sqlite_path} " "to PostgreSQL database.")


if __name__ == "__main__":
    main()
