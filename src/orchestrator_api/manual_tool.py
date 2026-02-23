from __future__ import annotations

import json
import os
from typing import Any, Literal
from urllib import error, parse, request

from fastapi import FastAPI, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

Severity = Literal["P1", "P2", "P3"]


class CreateTicketRequest(BaseModel):
    project_key: str = Field(..., min_length=2, max_length=10)
    issue_type: str
    summary: str = Field(..., min_length=3)
    description: str = ""
    severity: Severity = "P3"
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)


class UpdateTicketRequest(BaseModel):
    summary: str | None = None
    description: str | None = None
    severity: Severity | None = None
    status: str | None = None
    assignee: str | None = None
    labels: list[str] | None = None


def create_app() -> FastAPI:
    app = FastAPI(
        title="Company API Manual Tester",
        version="0.1.0",
        description=(
            "Manual proxy for testing mock company APIs from one Swagger UI. "
            "Configure upstream URLs with COMPANY_JIRA_BASE_URL, COMPANY_METRICS_BASE_URL, "
            "and COMPANY_LOGS_BASE_URL."
        ),
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "manual-tool"}

    @app.get("/targets")
    def targets() -> dict[str, str]:
        return {
            "jira": _base_url("jira"),
            "metrics": _base_url("metrics"),
            "logs": _base_url("logs"),
        }

    @app.get("/jira/health")
    def jira_health() -> JSONResponse:
        return _relay("GET", _url_for("jira", "/health"))

    @app.post("/jira/tickets")
    def jira_create_ticket(payload: CreateTicketRequest) -> JSONResponse:
        return _relay("POST", _url_for("jira", "/tickets"), payload=payload.model_dump())

    @app.patch("/jira/tickets/{ticket_key}")
    def jira_update_ticket(
        payload: UpdateTicketRequest,
        ticket_key: str = Path(..., description="Ticket key like OPS-101"),
    ) -> JSONResponse:
        return _relay(
            "PATCH",
            _url_for("jira", f"/tickets/{ticket_key}"),
            payload=payload.model_dump(exclude_none=True),
        )

    @app.get("/jira/tickets/search")
    def jira_search_tickets(
        project_key: str | None = Query(None),
        status: str | None = Query(None),
        severity: Severity | None = Query(None),
        text: str | None = Query(None),
    ) -> JSONResponse:
        params = {
            "project_key": project_key,
            "status": status,
            "severity": severity,
            "text": text,
        }
        return _relay("GET", _url_for("jira", "/tickets/search", params=params))

    @app.get("/metrics/query")
    def metrics_query(
        service: str = Query(..., description="Service name, e.g. saas-api"),
        start_time: str = Query(..., description="Inclusive UTC ISO timestamp"),
        end_time: str = Query(..., description="Inclusive UTC ISO timestamp"),
    ) -> JSONResponse:
        params = {"service": service, "start_time": start_time, "end_time": end_time}
        return _relay("GET", _url_for("metrics", "/metrics/query", params=params))

    @app.get("/logs/search")
    def logs_search(
        service: str = Query(..., description="Service name"),
        start_time: str = Query(..., description="Inclusive UTC ISO timestamp"),
        end_time: str = Query(..., description="Inclusive UTC ISO timestamp"),
        pattern: str = Query("", description="Optional case-insensitive substring"),
    ) -> JSONResponse:
        params = {
            "service": service,
            "start_time": start_time,
            "end_time": end_time,
            "pattern": pattern,
        }
        return _relay("GET", _url_for("logs", "/logs/search", params=params))

    return app


def _base_url(service: Literal["jira", "metrics", "logs"]) -> str:
    defaults = {
        "jira": "http://127.0.0.1:8001",
        "metrics": "http://127.0.0.1:8002",
        "logs": "http://127.0.0.1:8003",
    }
    env_vars = {
        "jira": "COMPANY_JIRA_BASE_URL",
        "metrics": "COMPANY_METRICS_BASE_URL",
        "logs": "COMPANY_LOGS_BASE_URL",
    }
    return os.getenv(env_vars[service], defaults[service]).rstrip("/")


def _url_for(
    service: Literal["jira", "metrics", "logs"],
    path: str,
    params: dict[str, object] | None = None,
) -> str:
    url = f"{_base_url(service)}{path}"
    if params:
        encoded = parse.urlencode(
            {key: value for key, value in params.items() if value is not None},
            doseq=True,
        )
        if encoded:
            return f"{url}?{encoded}"
    return url


def _relay(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
) -> JSONResponse:
    status_code, data = _request_json(method=method, url=url, payload=payload)
    if isinstance(data, (dict, list, int, float, bool)) or data is None:
        return JSONResponse(status_code=status_code, content=data)
    return JSONResponse(status_code=status_code, content={"raw": str(data)})


def _request_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    raw_payload: bytes | None = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        raw_payload = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, method=method, data=raw_payload, headers=headers)
    timeout_s = _env_float("MANUAL_TOOL_TIMEOUT_S", default=10.0)

    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
            return response.status, _decode_body(body)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, _decode_body(body)
    except error.URLError as exc:
        return 502, {"detail": f"upstream request failed: {exc.reason}"}


def _decode_body(body: str) -> Any:
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def _env_float(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


app = create_app()
