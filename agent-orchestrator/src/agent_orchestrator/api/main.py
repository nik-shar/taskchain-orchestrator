"""FastAPI app entrypoint for agent-orchestrator."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agent_orchestrator.api.ui import render_homepage
from agent_orchestrator.config.settings import Settings, get_settings
from agent_orchestrator.graph.state import initial_state
from agent_orchestrator.graph.workflow import build_graph
from agent_orchestrator.storage.base import TaskStorage
from agent_orchestrator.storage.models import TaskRecord, TaskRunRecord
from agent_orchestrator.storage.postgres import PostgresTaskStorage
from agent_orchestrator.tools import list_tools


class CreateTaskRequest(BaseModel):
    prompt: str = Field(min_length=1)


def _ensure_runtime_state(
    app: FastAPI,
    *,
    settings: Settings,
    workflow: Any,
    storage_override: TaskStorage | None,
) -> None:
    if not hasattr(app.state, "storage"):
        database_url = settings.resolved_database_url()
        if storage_override is None and not database_url:
            raise RuntimeError(
                "Missing database URL. Set AGENT_ORCHESTRATOR_DATABASE_URL "
                "or ORCHESTRATOR_DATABASE_URL before starting the app."
            )
        app.state.storage = storage_override or PostgresTaskStorage(database_url)
        app.state.storage.migrate()

    if not hasattr(app.state, "settings"):
        app.state.settings = settings

    if not hasattr(app.state, "workflow"):
        app.state.workflow = workflow


def create_app(
    *,
    storage: TaskStorage | None = None,
    settings_override: Settings | None = None,
) -> FastAPI:
    settings = settings_override or get_settings()
    workflow = build_graph(max_graph_loops=settings.max_graph_loops)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _ensure_runtime_state(
            app,
            settings=settings,
            workflow=workflow,
            storage_override=storage,
        )
        yield

    app_lifespan = lifespan if storage is None else None
    app = FastAPI(title=settings.app_name, lifespan=app_lifespan)

    # Keep test paths reliable when lifespan is not executed by the client.
    if storage is not None:
        _ensure_runtime_state(
            app,
            settings=settings,
            workflow=workflow,
            storage_override=storage,
        )

    def _get_task_storage(request: Request) -> TaskStorage:
        if not hasattr(request.app.state, "storage"):
            _ensure_runtime_state(
                request.app,
                settings=settings,
                workflow=workflow,
                storage_override=storage,
            )
        return request.app.state.storage

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return render_homepage(app_name=settings.app_name)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    @app.get("/tools")
    def tools() -> dict[str, list[str]]:
        return {"tools": list_tools()}

    @app.post("/tasks", response_model=TaskRecord)
    def create_task(payload: CreateTaskRequest, request: Request) -> TaskRecord:
        task_storage: TaskStorage = _get_task_storage(request)
        return task_storage.create_task(prompt=payload.prompt)

    @app.post("/tasks/{task_id}/run", response_model=TaskRecord)
    def run_task(task_id: str, request: Request) -> TaskRecord:
        task_storage: TaskStorage = _get_task_storage(request)
        record = task_storage.get_task(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")

        state = initial_state(
            task_id=task_id,
            user_input=record.prompt,
            mode=settings.planner_mode,
            executor_mode=settings.executor_mode,
            retry_budget=settings.max_graph_loops,
        )

        try:
            result: dict[str, Any] = request.app.state.workflow.invoke(state)
        except Exception as exc:  # pragma: no cover
            task_storage.create_task_run(
                task_id=task_id,
                status="failed",
                state_json={"error": str(exc)},
                plan_json=None,
                tool_results_json=None,
                verification_json={"passed": False, "error": "execution_error"},
                output=None,
            )
            task_storage.update_task(
                task_id,
                status="failed",
                output=None,
                verification={"passed": False, "error": "execution_error"},
            )
            raise HTTPException(status_code=500, detail="Task run failed") from exc

        verification_payload = _build_verification_payload(result)
        task_storage.create_task_run(
            task_id=task_id,
            status="completed",
            state_json=result,
            plan_json=result.get("plan_steps"),
            tool_results_json=result.get("tool_results"),
            verification_json=verification_payload,
            output=result.get("final_output"),
        )
        return task_storage.update_task(
            task_id,
            status="completed",
            output=result.get("final_output"),
            verification=verification_payload,
        )

    @app.get("/tasks/{task_id}", response_model=TaskRecord)
    def get_task(task_id: str, request: Request) -> TaskRecord:
        task_storage: TaskStorage = _get_task_storage(request)
        record = task_storage.get_task(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return record

    @app.get("/tasks/{task_id}/runs/latest", response_model=TaskRunRecord)
    def get_latest_task_run(task_id: str, request: Request) -> TaskRunRecord:
        task_storage: TaskStorage = _get_task_storage(request)
        record = task_storage.get_task(task_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Task not found")

        run = task_storage.get_latest_task_run(task_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Task run not found")
        return run

    return app


app = create_app()


def _build_verification_payload(result: dict[str, Any]) -> dict[str, Any]:
    verification = result.get("verification")
    verification_payload = dict(verification) if isinstance(verification, dict) else {}
    telemetry = result.get("telemetry")
    telemetry_payload = telemetry if isinstance(telemetry, dict) else {}

    planner = telemetry_payload.get("planner")
    executor = telemetry_payload.get("executor")
    verification_payload["runtime"] = {
        "planner": planner if isinstance(planner, dict) else {},
        "executor": executor if isinstance(executor, dict) else {},
    }
    return verification_payload
