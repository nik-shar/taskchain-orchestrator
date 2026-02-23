from __future__ import annotations

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from company_sim.mock_systems.common import in_time_window, load_seed_json


class MetricPoint(BaseModel):
    timestamp: str
    service: str
    latency_p95_ms: float = Field(..., ge=0)
    error_rate: float = Field(..., ge=0)


class MetricsQueryResponse(BaseModel):
    service: str
    start_time: str
    end_time: str
    points_count: int
    latency_p95_ms_avg: float
    latency_p95_ms_max: float
    error_rate_avg: float
    error_rate_max: float
    points: list[MetricPoint]


app = FastAPI(
    title="Metrics Mock API",
    version="1.0.0",
    description="Deterministic service metrics API backed by seeded JSON data.",
)
_seed = load_seed_json("metrics_timeseries.json")
_METRIC_POINTS = _seed["points"]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "system": "metrics-mock"}


@app.get("/metrics/query", response_model=MetricsQueryResponse)
def query_metrics(
    service: str = Query(..., description="Service name, e.g. saas-api"),
    start_time: str = Query(..., description="Inclusive UTC ISO timestamp"),
    end_time: str = Query(..., description="Inclusive UTC ISO timestamp"),
) -> MetricsQueryResponse:
    filtered = [
        point
        for point in _METRIC_POINTS
        if point["service"] == service and in_time_window(point["timestamp"], start_time, end_time)
    ]

    ordered_points = sorted(filtered, key=lambda item: item["timestamp"])

    if not ordered_points:
        return MetricsQueryResponse(
            service=service,
            start_time=start_time,
            end_time=end_time,
            points_count=0,
            latency_p95_ms_avg=0.0,
            latency_p95_ms_max=0.0,
            error_rate_avg=0.0,
            error_rate_max=0.0,
            points=[],
        )

    latency_values = [point["latency_p95_ms"] for point in ordered_points]
    error_values = [point["error_rate"] for point in ordered_points]

    return MetricsQueryResponse(
        service=service,
        start_time=start_time,
        end_time=end_time,
        points_count=len(ordered_points),
        latency_p95_ms_avg=round(sum(latency_values) / len(latency_values), 3),
        latency_p95_ms_max=max(latency_values),
        error_rate_avg=round(sum(error_values) / len(error_values), 3),
        error_rate_max=max(error_values),
        points=[MetricPoint(**point) for point in ordered_points],
    )
