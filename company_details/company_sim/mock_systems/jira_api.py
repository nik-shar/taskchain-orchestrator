from __future__ import annotations

from datetime import timedelta, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Path, Query
from pydantic import BaseModel, Field

from company_sim.mock_systems.common import load_seed_json, parse_utc_timestamp

SEVERITY = Literal["P1", "P2", "P3"]


class Ticket(BaseModel):
    key: str = Field(..., description="Ticket key, for example OPS-101")
    project_key: str = Field(..., description="Jira project key")
    issue_type: str = Field(..., description="Issue type, for example Incident/Change")
    summary: str
    description: str
    severity: SEVERITY
    status: str
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CreateTicketRequest(BaseModel):
    project_key: str = Field(..., min_length=2, max_length=10)
    issue_type: str
    summary: str = Field(..., min_length=3)
    description: str = ""
    severity: SEVERITY = "P3"
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)


class UpdateTicketRequest(BaseModel):
    summary: str | None = None
    description: str | None = None
    severity: SEVERITY | None = None
    status: str | None = None
    assignee: str | None = None
    labels: list[str] | None = None


class TicketListResponse(BaseModel):
    total: int
    tickets: list[Ticket]


class JiraStore:
    def __init__(self) -> None:
        data = load_seed_json("jira_tickets.json")
        self._tickets: dict[str, dict] = {ticket["key"]: ticket for ticket in data["tickets"]}
        latest_seed_time = max(parse_utc_timestamp(t["updated_at"]) for t in self._tickets.values())
        self._logical_clock = latest_seed_time

    def _next_key_for_project(self, project_key: str) -> str:
        project_key = project_key.upper()
        max_id = 0
        prefix = f"{project_key}-"
        for key in self._tickets:
            if key.startswith(prefix):
                suffix = key.split("-", 1)[1]
                if suffix.isdigit():
                    max_id = max(max_id, int(suffix))
        return f"{project_key}-{max_id + 1}"

    def _next_timestamp(self) -> str:
        # Deterministic logical clock derived from seed data.
        self._logical_clock = self._logical_clock + timedelta(seconds=1)
        return self._logical_clock.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def create_ticket(self, payload: CreateTicketRequest) -> dict:
        new_key = self._next_key_for_project(payload.project_key)
        now = self._next_timestamp()
        new_ticket = {
            "key": new_key,
            "project_key": payload.project_key.upper(),
            "issue_type": payload.issue_type,
            "summary": payload.summary,
            "description": payload.description,
            "severity": payload.severity,
            "status": "New",
            "assignee": payload.assignee,
            "labels": payload.labels,
            "created_at": now,
            "updated_at": now,
        }
        self._tickets[new_key] = new_ticket
        return new_ticket

    def update_ticket(self, key: str, payload: UpdateTicketRequest) -> dict:
        ticket = self._tickets.get(key)
        if ticket is None:
            raise KeyError(key)

        for field in ("summary", "description", "severity", "status", "assignee", "labels"):
            value = getattr(payload, field)
            if value is not None:
                ticket[field] = value

        ticket["updated_at"] = self._next_timestamp()
        return ticket

    def search(
        self,
        project_key: str | None,
        status: str | None,
        severity: str | None,
        text: str | None,
    ) -> list[dict]:
        results = list(self._tickets.values())

        if project_key:
            results = [t for t in results if t["project_key"] == project_key.upper()]
        if status:
            results = [t for t in results if t["status"].lower() == status.lower()]
        if severity:
            results = [t for t in results if t["severity"] == severity]
        if text:
            q = text.lower()
            results = [
                t
                for t in results
                if q in t["summary"].lower() or q in t.get("description", "").lower()
            ]

        return sorted(results, key=lambda item: item["key"])


app = FastAPI(
    title="Jira Mock API",
    version="1.0.0",
    description="Deterministic Jira-like ticket API backed by seeded JSON data.",
)
store = JiraStore()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "system": "jira-mock"}


@app.post("/tickets", response_model=Ticket, status_code=201)
def create_ticket(payload: CreateTicketRequest) -> Ticket:
    ticket = store.create_ticket(payload)
    return Ticket(**ticket)


@app.patch("/tickets/{ticket_key}", response_model=Ticket)
def update_ticket(
    payload: UpdateTicketRequest,
    ticket_key: str = Path(..., description="Jira ticket key, e.g. OPS-101"),
) -> Ticket:
    try:
        ticket = store.update_ticket(ticket_key, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ticket not found") from exc
    return Ticket(**ticket)


@app.get("/tickets/search", response_model=TicketListResponse)
def search_tickets(
    project_key: str | None = Query(None),
    status: str | None = Query(None),
    severity: SEVERITY | None = Query(None),
    text: str | None = Query(None),
) -> TicketListResponse:
    tickets = store.search(project_key=project_key, status=status, severity=severity, text=text)
    return TicketListResponse(total=len(tickets), tickets=[Ticket(**ticket) for ticket in tickets])
