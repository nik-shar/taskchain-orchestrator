"""FastAPI application wiring for the orchestration service.

Beginner terms used in this file:
- FastAPI app: the main web application object.
- Route/path operation: a function exposed over HTTP (for example, GET /health).
- response_model: Pydantic model used to validate/shape API responses.
- app.state: a place to store shared runtime objects (storage, planner, executor).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .app.executor import Executor, build_tool_registry
from .app.llm import build_llm_adapter_from_env
from .app.models import CreateTaskRequest, CreateTaskResponse, Task, VerificationResult
from .app.planner import Planner
from .app.storage import PostgresTaskStorage
from .app.ui import render_homepage
from .app.verifier import verify_execution

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Application factory.

    This pattern builds and returns a fully configured FastAPI app instance.
    It is useful for tests because each test can create a fresh app.
    """
    # Load local .env values into process environment if keys are not already set.
    _load_env_file(Path(".env"))

    # Fail fast if required configuration is missing.
    database_url = os.getenv("ORCHESTRATOR_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("ORCHESTRATOR_DATABASE_URL is required.")
    storage = PostgresTaskStorage(database_url=database_url)

    llm_adapter = build_llm_adapter_from_env()

    # "mode" controls whether planner/executor uses deterministic logic or LLM logic.
    planner_mode = os.getenv("ORCHESTRATOR_PLANNER_MODE", "deterministic")
    executor_mode = os.getenv("ORCHESTRATOR_EXECUTOR_MODE", "deterministic").lower()
    if (planner_mode.lower() == "llm" or executor_mode == "llm") and llm_adapter is None:
        raise RuntimeError(
            "LLM mode requested but no adapter is configured. "
            "Set OPENAI_API_KEY and ORCHESTRATOR_LLM_PROVIDER=openai."
        )

    planner_timeout_s = _env_float("ORCHESTRATOR_PLANNER_TIMEOUT_S", default=8.0)
    planner = Planner(mode=planner_mode, llm_adapter=llm_adapter, timeout_s=planner_timeout_s)

    # Core "NLP-style" tools can switch to LLM implementations in llm executor mode.
    # Company tools remain deterministic HTTP/file tools.
    use_llm_tools = executor_mode == "llm" and llm_adapter is not None
    tool_registry = build_tool_registry(
        llm_adapter=llm_adapter if use_llm_tools else None,
        llm_timeout_s=_env_float("ORCHESTRATOR_EXECUTOR_LLM_TIMEOUT_S", default=8.0),
    )
    executor = Executor(
        registry=tool_registry,
        tool_timeout_s=_env_float("ORCHESTRATOR_TOOL_TIMEOUT_S", default=2.0),
        retry_policy={
            "max_retries": _env_int("ORCHESTRATOR_TOOL_MAX_RETRIES", default=1),
            "backoff_s": _env_float("ORCHESTRATOR_TOOL_BACKOFF_S", default=0.05),
        },
        fail_fast=os.getenv("ORCHESTRATOR_EXECUTOR_FAIL_FAST", "0").strip() == "1",
    )

    app = FastAPI(title="orchestrator_api", version="0.1.0")
    # Shared objects live in app.state so route handlers can reuse them.
    app.state.storage = storage
    app.state.planner = planner
    app.state.executor = executor

    # Multiple health endpoints map to the same function for compatibility with
    # different probes/load balancers.
    @app.get("/health")
    @app.get("/healthz")
    @app.get("/live")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return render_homepage()

    @app.get("/tools")
    def list_tools() -> dict[str, list[str]]:
        return {"tools": sorted(app.state.executor.registry.keys())}

    # Request body is validated against CreateTaskRequest.
    # Response is validated against CreateTaskResponse.
    @app.post("/tasks", response_model=CreateTaskResponse)
    def create_task(payload: CreateTaskRequest) -> CreateTaskResponse:
        task_id = app.state.storage.create_task(payload.task, context=payload.context)
        return CreateTaskResponse(task_id=task_id)

    @app.get("/tasks/{task_id}", response_model=Task)
    def get_task(task_id: str) -> Task:
        task = app.state.storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.post("/tasks/{task_id}/run", response_model=Task)
    def run_task(task_id: str) -> Task:
        # 1) Load task and guard for missing task id.
        task = app.state.storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        # 2) Mark task running and write lifecycle log.
        logger.info(
            "task_run event=start task_id=%s planner_mode=%s executor_mode=%s status=%s",
            task_id,
            planner_mode,
            executor_mode,
            "running",
        )
        app.state.storage.update_task(task_id, status="running")

        # 3) Planner produces a typed execution plan from task text + context.
        plan = app.state.planner.build_plan(task.input_task, context=task.context)
        logger.info(
            "task_run event=plan_built task_id=%s planner_mode=%s executor_mode=%s status=%s",
            task_id,
            planner_mode,
            executor_mode,
            "running",
        )
        result: dict[str, Any]
        verification: VerificationResult
        try:
            # 4) Executor runs tool calls in plan order.
            result = app.state.executor.execute_plan(plan)
            # 5) Verifier checks structural and quality/evidence gates.
            verification = verify_execution(plan, result)
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}
            verification = VerificationResult(
                passed=False,
                reasons=[f"Unexpected run failure: {exc}"],
            )

        # 6) Persist final status with all artifacts for traceability.
        status = "succeeded" if verification.passed else "failed"
        execution_metadata = _execution_metadata_from_result(result)
        logger.info(
            "task_run event=completed task_id=%s planner_mode=%s "
            "executor_mode=%s status=%s execution_metadata=%s",
            task_id,
            planner_mode,
            executor_mode,
            status,
            execution_metadata,
        )
        updated = app.state.storage.update_task(
            task_id,
            status=status,
            plan=plan,
            result=result,
            verification=verification,
        )
        return updated

    return app


def _env_int(name: str, *, default: int) -> int:
    """Read integer env var; return default when unset/invalid."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, *, default: float) -> float:
    """Read float env var; return default when unset/invalid."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _load_env_file(path: Path) -> None:
    """Minimal .env loader used to avoid an external dependency for this project."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _execution_metadata_from_result(result: dict[str, Any]) -> dict[str, Any]:
    """Safely fetch execution metadata from executor output."""
    metadata = result.get("execution_metadata", {})
    if isinstance(metadata, dict):
        return metadata
    return {}


# Module-level app for `uvicorn orchestrator_api.main:app`.
app = create_app()
