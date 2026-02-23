# Repository Agent Guide

This file is the single onboarding reference for the entire repository.

## 1. What This Repo Contains

This repository is a fictional enterprise AI operations simulation for a mid-size SaaS company (`Northstar Metrics`).

It includes:

- Company governance and operational policy docs.
- Tool configuration files (Slack, Jira, Postgres, GitHub Actions, on-call rota).
- Scenario datasets for AI operations tasks and expected outcomes.
- FastAPI-based mock systems for Jira, Metrics, and Logs.

## 2. Top-Level Structure

```text
.
├── AGENT.md
├── Makefile
├── docker-compose.yml
├── company_sim/
│   ├── README.md
│   ├── docs/
│   │   ├── company_profile.md
│   │   └── governance_notes.md
│   ├── policies/
│   │   ├── policy_v1.md
│   │   └── policy_v2.md
│   ├── scenarios/
│   │   ├── tasks.jsonl
│   │   └── expected_outcomes.jsonl
│   ├── tool_configs/
│   │   ├── slack.yaml
│   │   ├── jira.yaml
│   │   ├── postgres.yaml
│   │   ├── github_actions.yaml
│   │   └── oncall_rota.yaml
│   └── mock_systems/
│       ├── README.md
│       ├── Dockerfile
│       ├── docker-compose.yml
│       ├── requirements.txt
│       ├── common.py
│       ├── jira_api.py
│       ├── metrics_api.py
│       ├── logs_api.py
│       ├── data/
│       │   ├── jira_tickets.json
│       │   ├── metrics_timeseries.json
│       │   └── log_events.json
│       └── tests/
│           ├── test_jira_api.py
│           ├── test_metrics_api.py
│           └── test_logs_api.py
└── <reference PDFs>
```

## 3. Dataset and Policy Layer

### Core docs

- `company_sim/docs/company_profile.md`: business profile and operating model.
- `company_sim/docs/governance_notes.md`: evidence/citation rules for AI operations behavior.

### Policies

- `company_sim/policies/policy_v1.md`: baseline rules.
- `company_sim/policies/policy_v2.md`: updated rules with tighter controls.

Key policy controls defined:

- Severity handling: `P1/P2/P3`.
- Escalation timelines.
- Incident communication channels and cadence.
- Change windows and freeze logic.
- Rollback triggers.
- Approval requirements.
- Audit logging SLAs.

### Tool configs

- `company_sim/tool_configs/slack.yaml`: channel names and reporting defaults.
- `company_sim/tool_configs/jira.yaml`: project keys, issue types, required fields, workflows.
- `company_sim/tool_configs/postgres.yaml`: DB clusters and audit table requirements.
- `company_sim/tool_configs/github_actions.yaml`: CI/CD and rollback workflow constraints.
- `company_sim/tool_configs/oncall_rota.yaml`: weekly primary/secondary on-call and escalation order.

### Scenario dataset

- `company_sim/scenarios/tasks.jsonl`: 30 operational tasks.
- `company_sim/scenarios/expected_outcomes.jsonl`: expected properties + citation requirements for those tasks.

## 4. Mock APIs (FastAPI)

All mock APIs are deterministic and read from seeded JSON in `company_sim/mock_systems/data/`.

Common deterministic helpers live in `company_sim/mock_systems/common.py`.

### 4.1 Jira Mock

Source: `company_sim/mock_systems/jira_api.py`

Base URL (compose): `http://localhost:8001`

Endpoints:

1. `POST /tickets`
- Purpose: create ticket.
- Request body fields: `project_key`, `issue_type`, `summary`, `description`, `severity`, `assignee`, `labels`.
- Behavior: assigns deterministic sequential key (e.g. `OPS-103`) and logical timestamp.

2. `PATCH /tickets/{ticket_key}`
- Purpose: update existing ticket fields.
- Updatable fields: `summary`, `description`, `severity`, `status`, `assignee`, `labels`.

3. `GET /tickets/search`
- Purpose: query tickets.
- Query params: `project_key`, `status`, `severity`, `text`.

4. `GET /health`
- Health probe.

OpenAPI: `GET /openapi.json`

### 4.2 Metrics Mock

Source: `company_sim/mock_systems/metrics_api.py`

Base URL (compose): `http://localhost:8002`

Endpoints:

1. `GET /metrics/query`
- Purpose: query latency/error metrics for a service in a time window.
- Query params: `service`, `start_time`, `end_time` (ISO UTC).
- Returns:
  - matching points,
  - `latency_p95_ms_avg`, `latency_p95_ms_max`,
  - `error_rate_avg`, `error_rate_max`,
  - deterministic values from seed data.

2. `GET /health`
- Health probe.

OpenAPI: `GET /openapi.json`

### 4.3 Logs Mock

Source: `company_sim/mock_systems/logs_api.py`

Base URL (compose): `http://localhost:8003`

Endpoints:

1. `GET /logs/search`
- Purpose: search logs by service + time window + optional pattern.
- Query params: `service`, `start_time`, `end_time`, `pattern`.
- Pattern logic: case-insensitive substring against log message.

2. `GET /health`
- Health probe.

OpenAPI: `GET /openapi.json`

## 5. How to Run

### Run all mocks with Docker Compose

From repo root:

```bash
docker compose up --build
```

Services/ports:

- Jira mock: `8001 -> 8000`
- Metrics mock: `8002 -> 8000`
- Logs mock: `8003 -> 8000`

Alternative compose file also exists at `company_sim/mock_systems/docker-compose.yml`.

### Run tests

```bash
make test
```

`Makefile` behavior:

- Uses `.venv`.
- Installs `company_sim/mock_systems/requirements.txt`.
- Runs integration tests in `company_sim/mock_systems/tests/`.

## 6. OpenAPI and Contract Notes

Each mock defines typed Pydantic models for request/response bodies, so OpenAPI schemas are available by default.

- Jira schema: `http://localhost:8001/openapi.json`
- Metrics schema: `http://localhost:8002/openapi.json`
- Logs schema: `http://localhost:8003/openapi.json`

## 7. Determinism Rules

- Seed data lives in JSON files under `company_sim/mock_systems/data/`.
- Query endpoints do pure filtering/aggregation over that data.
- Jira create/update uses a deterministic logical clock derived from seed timestamps.
- For identical seed state and call sequence, outputs are stable.

## 8. Where to Extend Next

- Add auth middleware if consumer tests need token simulation.
- Add pagination to Jira search and logs search.
- Add baseline comparison endpoint in metrics mock.
- Add fixtures for additional services and edge-case incident payloads.

