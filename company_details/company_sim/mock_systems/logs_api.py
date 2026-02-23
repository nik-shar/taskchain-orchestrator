from __future__ import annotations

from fastapi import FastAPI, Query
from pydantic import BaseModel

from company_sim.mock_systems.common import in_time_window, load_seed_json


class LogEvent(BaseModel):
    timestamp: str
    service: str
    level: str
    pattern: str
    message: str
    trace_id: str


class LogSearchResponse(BaseModel):
    service: str
    start_time: str
    end_time: str
    pattern: str
    total: int
    events: list[LogEvent]


app = FastAPI(
    title="Logs Mock API",
    version="1.0.0",
    description="Deterministic log search API backed by seeded JSON data.",
)
_seed = load_seed_json("log_events.json")
_LOG_EVENTS = _seed["events"]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "system": "logs-mock"}


@app.get("/logs/search", response_model=LogSearchResponse)
def search_logs(
    service: str = Query(..., description="Service name"),
    start_time: str = Query(..., description="Inclusive UTC ISO timestamp"),
    end_time: str = Query(..., description="Inclusive UTC ISO timestamp"),
    pattern: str = Query("", description="Case-insensitive message substring filter"),
) -> LogSearchResponse:
    needle = pattern.lower()
    filtered = [
        event
        for event in _LOG_EVENTS
        if event["service"] == service
        and in_time_window(event["timestamp"], start_time, end_time)
        and (needle in event["message"].lower() if needle else True)
    ]

    ordered_events = sorted(filtered, key=lambda item: item["timestamp"])

    return LogSearchResponse(
        service=service,
        start_time=start_time,
        end_time=end_time,
        pattern=pattern,
        total=len(ordered_events),
        events=[LogEvent(**event) for event in ordered_events],
    )
