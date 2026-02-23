# orchestrator_api

FastAPI service for task orchestration with a planner -> executor -> verifier pipeline, PostgreSQL task persistence, and optional OpenAI-backed planning/tool execution.

This repository currently supports:
- Deterministic planner/executor/verifier flow
- Optional LLM planner and LLM tool routing (with deterministic fallback)
- Company simulation tools for Jira, Metrics, Logs, and policy/config references
- API + browser UI + manual proxy tester for company mock APIs

## Project status

- Phase 1: complete
  Local vertical slice, FastAPI API/UI, PostgreSQL-backed persistence, deterministic execution
- Phase 2: complete
  OpenAI adapter integration, planner/tool routing by mode, LLM scaffolding tests
- Phase 3: in progress
  Implemented slice: incident retrieval toolchain, incident-aware planning, verifier gates, and run telemetry; remaining hardening and observability expansion continue
- Phase 4: planned
  Cloud Run production deployment with managed Postgres/Cloud SQL

## Phase 3

Commit messages for current Phase 3 implementation increments:

- `feat(retrieval): add deterministic local incident knowledge search core and index builder`
- `feat(company-tools): expose strict incident knowledge retrieval tool with citation-ready ranked output`
- `feat(executor): register incident knowledge tool and add execution telemetry metadata`
- `feat(planner): add incident-aware retrieval steps and llm support for search_incident_knowledge`
- `feat(verifier): enforce incident evidence and policy citation verification gates`
- `feat(main): add structured run lifecycle logs with execution metadata`
- `test(integration): add deterministic incident retrieval end-to-end flow`

## Architecture

### Core modules

- `src/orchestrator_api/main.py`
  App wiring, env loading, mode selection, API routes
- `src/orchestrator_api/app/planner.py`
  Deterministic planner + LLM planner route/fallback
- `src/orchestrator_api/app/executor.py`
  Tool registry, strict input/output validation, timeout/retry execution
- `src/orchestrator_api/app/verifier.py`
  Post-execution checks and pass/fail reasons
- `src/orchestrator_api/app/storage.py`
  PostgreSQL storage and schema migration
- `src/orchestrator_api/app/company_tools.py`
  Company reference retrieval + Jira/Metrics/Logs query tools
- `src/orchestrator_api/app/ui.py`
  Built-in HTML UI for task create/run/fetch
- `src/orchestrator_api/manual_tool.py`
  Swagger-friendly proxy for manual testing of company mock APIs

### Runtime flow (exact)

1. `POST /tasks` creates a queued task row.
2. `POST /tasks/{task_id}/run` sets status to `running`.
3. Planner builds `plan_json`.
4. Executor runs each tool call in order with validation/timeout/retries.
5. Verifier inspects execution result and returns `passed/reasons`.
6. Task is persisted as `succeeded` or `failed` with plan/result/verification.

## Repository layout

- `src/orchestrator_api/`: main application package
- `tests/`: unit + integration tests
- `scripts/`: utility scripts (including SQLite -> PostgreSQL migration)
- `company_details/company_sim/`: company dataset, policies, configs, deterministic mock APIs

## Prerequisites

- Python `3.13+`
- Docker (recommended for local Postgres and company mocks)
- `make`

## Setup

1. Create and activate virtual environment

```bash
python -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
```

2. Install package + dev dependencies

```bash
python -m pip install -e ".[dev]"
```

## Run dependencies

### PostgreSQL (required)

```bash
docker run --name orchestrator-postgres \
  -e POSTGRES_USER=orchestrator \
  -e POSTGRES_PASSWORD=orchestrator \
  -e POSTGRES_DB=orchestrator_db \
  -p 5432:5432 \
  -d postgres:16
```

Set DB URL in your shell:

```bash
export ORCHESTRATOR_DATABASE_URL=postgresql://orchestrator:orchestrator@127.0.0.1:5432/orchestrator_db
```

### Company mock APIs (recommended for company tools)

```bash
docker compose -f company_details/company_sim/mock_systems/docker-compose.yml up -d --build
```

Health checks:

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8003/health
```

## Run the app

```bash
make run
```

- API base URL: `http://127.0.0.1:8000`
- UI: `http://127.0.0.1:8000/`
- Tool list: `http://127.0.0.1:8000/tools`

## API quickstart

Create task:

```bash
curl -s -X POST "http://127.0.0.1:8000/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "P1 alert: Checkout API latency and errors increased. Analyze metrics/logs and propose escalation with citations.",
    "context": {
      "service": "saas-api",
      "project_key": "OPS",
      "start_time": "2026-02-14T10:00:00Z",
      "end_time": "2026-02-14T10:30:00Z",
      "severity": "P1",
      "required_citations": ["policy_v2", "oncall_rota", "slack_config"]
    }
  }'
```

Run task:

```bash
curl -s -X POST "http://127.0.0.1:8000/tasks/<TASK_ID>/run" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Fetch task:

```bash
curl -s "http://127.0.0.1:8000/tasks/<TASK_ID>"
```

## Planner and executor modes

### Planner mode

- `ORCHESTRATOR_PLANNER_MODE=deterministic`
  Uses fixed extraction/summarization plan
- `ORCHESTRATOR_PLANNER_MODE=llm`
  Uses OpenAI planner with strict schema target; falls back to deterministic on LLM failure

### Executor mode

- `ORCHESTRATOR_EXECUTOR_MODE=deterministic`
  Uses deterministic built-in tools (plus company query tools)
- `ORCHESTRATOR_EXECUTOR_MODE=llm`
  Uses LLM-backed implementations for built-in NLP-style tools while company query tools remain deterministic HTTP/file tools

## Available tools

### Core built-in tools

- `extract_entities` `{text}` -> `{entities}`
- `extract_deadlines` `{text}` -> `{deadlines}`
- `extract_action_items` `{text}` -> `{action_items}`
- `classify_priority` `{text}` -> `{priority, reasons}`
- `summarize` `{text, max_words}` -> `{summary}`

### Company tools

- `fetch_company_reference` `{source, query?, max_chars?}` -> excerpt from policy/config files
  - sources: `policy_v1`, `policy_v2`, `governance_notes`, `company_profile`, `jira_config`, `slack_config`, `oncall_rota`, `github_actions`, `postgres_config`
- `jira_search_tickets` `{project_key?, status?, severity?, text?}`
- `metrics_query` `{service, start_time, end_time}`
- `logs_search` `{service, start_time, end_time, pattern?}`
- `search_incident_knowledge` `{query, service?, severity?, time_start?, time_end?, top_k?, max_snippet_chars?}`
  - returns ranked evidence hits with `source_id`, `snippet`, `score`, `metadata`, and citation-ready fields (`citation_id`, `citation_source`)
  - returns retrieval confidence and fallback recommendation (`confidence`, `recommend_fallback`, `fallback_reason`)
- `search_previous_issues` `{query, source?, collection?, issue_type?, priority?, project?, incident_state?, created_from?, created_to?, opened_from?, opened_to?, top_k?, max_snippet_chars?, index_path?, use_llm_rerank?}`
  - searches the local SQLite RAG index (default `data/rag_index.sqlite`) over Jira + incident subset docs
  - returns ranked previous-issue hits with chunk citations and retrieval confidence/fallback flags
  - supports optional OpenAI reranking (env: `ORCHESTRATOR_RAG_RERANK_MODE=auto|deterministic|llm`)
  - if strict filters return zero matches, tool automatically retries with relaxed filters

## Incident retrieval behavior (Phase 3 slice)

- Retrieval is deterministic and local-first.
- Corpus is loaded from:
  - `company_details/company_sim/policies/*.md`
  - `company_details/company_sim/docs/*.md`
  - `company_details/company_sim/mock_systems/data/jira_tickets.json`
- Retrieval uses chunking + lexical token-overlap ranking with optional metadata filters (`service`, `severity`, `time_start`, `time_end`).
- For issue/incident-like tasks (`issue`, `ticket`, `bug`, `incident`, `alert`), deterministic planning prepends:
  - `search_previous_issues`
- For incident-like tasks, `search_previous_issues` is intentionally broad (no forced project/time filters) to avoid accidental zero-hit retrieval.
- For incident-like tasks (`alert`, `incident`, `sev`, `p1`, `outage`), deterministic planning also prepends:
  - `search_incident_knowledge`
  - `fetch_company_reference` policy evidence step
- Verifier now gates incident plans on:
  - at least one successful evidence source (`search_incident_knowledge`, `search_previous_issues`, or `jira_search_tickets`)
  - at least one successful policy/governance citation via `fetch_company_reference`

## Execution telemetry (Phase 3 slice)

- Each tool result includes:
  - `attempts`
  - `duration_ms`
- Plan-level result includes:
  - `result_json.execution_metadata.total_tools`
  - `result_json.execution_metadata.total_duration_ms`
  - `result_json.execution_metadata.error_count`
- Run lifecycle logs include structured entries for start, plan built, and completion with `task_id`, planner/executor mode, status, and `execution_metadata`.

## Example tasks (company environment)

1. `A P1 alert fired for saas-api. Check metrics and logs for 2026-02-14T10:00:00Z to 2026-02-14T10:30:00Z, find related OPS incidents, and recommend escalation timing with citations from policy_v2 and oncall_rota.`
2. `Validate whether rollback is mandatory when error rate exceeded 2.5% for 6 minutes. Use metrics evidence and cite policy_v2 and github_actions config.`
3. `Find open OPS incident tickets mentioning checkout timeout, summarize ownership gaps, and propose next communication channels using slack_config and policy_v2.`
4. `Compare P1 escalation obligations between policy_v1 and policy_v2 and summarize what tightened.`
5. `For week starting 2026-02-16, identify primary/secondary on-call and define response steps for an unowned P2 at +25 minutes.`

## Configuration reference

### Required

- `ORCHESTRATOR_DATABASE_URL`

### Core runtime

- `ORCHESTRATOR_PLANNER_MODE=deterministic|llm`
- `ORCHESTRATOR_EXECUTOR_MODE=deterministic|llm`
- `ORCHESTRATOR_TOOL_TIMEOUT_S`
- `ORCHESTRATOR_TOOL_MAX_RETRIES`
- `ORCHESTRATOR_TOOL_BACKOFF_S`

### LLM

- `OPENAI_API_KEY`
- `ORCHESTRATOR_LLM_PROVIDER` (default: `openai`)
- `ORCHESTRATOR_LLM_MODEL` (default: `gpt-4o-mini`)
- `ORCHESTRATOR_LLM_BASE_URL` (default: `https://api.openai.com/v1`)
- `ORCHESTRATOR_LLM_MAX_RETRIES`
- `ORCHESTRATOR_LLM_BACKOFF_S`
- `ORCHESTRATOR_LLM_TRACE=0|1`
- `ORCHESTRATOR_PLANNER_TIMEOUT_S`
- `ORCHESTRATOR_EXECUTOR_LLM_TIMEOUT_S`

### Company tool endpoints

- `COMPANY_JIRA_BASE_URL` (default: `http://127.0.0.1:8001`)
- `COMPANY_METRICS_BASE_URL` (default: `http://127.0.0.1:8002`)
- `COMPANY_LOGS_BASE_URL` (default: `http://127.0.0.1:8003`)
- `ORCHESTRATOR_COMPANY_TOOL_TIMEOUT_S` (default: `10.0`)
- `ORCHESTRATOR_COMPANY_SIM_ROOT` (optional override for policy/config root)
- `ORCHESTRATOR_RAG_INDEX_PATH` (optional override for `search_previous_issues`; default: `data/rag_index.sqlite`)
- `ORCHESTRATOR_RAG_RERANK_MODE` (`auto` default, `deterministic`, or `llm`)
- `ORCHESTRATOR_RAG_RERANK_TIMEOUT_S` (default: `8.0`)

### Manual tool app

- `MANUAL_TOOL_TIMEOUT_S` (default: `10.0`)

## PostgreSQL details

- Storage backend: `PostgresTaskStorage`
- Table: `tasks`
- Columns:
  - `task_id`, `input_task`, `status`
  - `context_json`, `plan_json`, `result_json`, `verification_json`
  - `created_at`, `updated_at`

Migrations are auto-applied on app startup.

## SQLite -> PostgreSQL migration

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-path data/tasks.db \
  --database-url postgresql://orchestrator:orchestrator@127.0.0.1:5432/orchestrator_db
```

## Manual Company API tester

Start proxy API:

```bash
make run-manual-tool
```

- Swagger: `http://127.0.0.1:8010/docs`
- Endpoint fan-out:
  - `/jira/*` -> Jira mock
  - `/metrics/*` -> Metrics mock
  - `/logs/*` -> Logs mock

## Testing

Run all tests:

```bash
make test
```

Focused runs:

```bash
python -m pytest tests/test_company_tools.py -q
python -m pytest tests/integration/test_api_real_world_flow.py
python -m pytest tests/integration/test_incident_rag_flow.py
```

Incident integration prerequisites:

```bash
export RUN_POSTGRES_INTEGRATION_TESTS=1
export ORCHESTRATOR_DATABASE_URL=postgresql://orchestrator:orchestrator@127.0.0.1:5432/orchestrator_db
python -m pytest tests/integration/test_incident_rag_flow.py
```

Live LLM integration (optional):

```bash
export RUN_POSTGRES_INTEGRATION_TESTS=1
export RUN_LIVE_LLM_TESTS=1
export OPENAI_API_KEY=<your_key>
export ORCHESTRATOR_PLANNER_MODE=llm
export ORCHESTRATOR_EXECUTOR_MODE=llm
python -m pytest tests/integration/test_live_llm_flow.py
```

## Development commands

- `make run`
- `make run-manual-tool`
- `make test`
- `make fmt`
- `make lint`

## Troubleshooting

### `ORCHESTRATOR_DATABASE_URL is required`

Set and export a valid PostgreSQL URL before starting the app.

### `connection refused` for `metrics_query`/`logs_search`/`jira_search_tickets`

Company mock APIs are not running or wrong base URL env vars are set.

### `extra_forbidden` or `missing` tool validation errors

The LLM planner produced invalid tool args. This is expected occasionally with strict schemas. Re-run, refine task/context, or use deterministic planner mode.

### Task status is `failed`

Check:
- `result_json.steps[*].tool_results[*].error`
- `verification_json.reasons`

## Security notes

- Never commit real secrets.
- Keep secret values only in local `.env` (git-ignored).
- Validate external inputs at API/tool boundaries.

## Future roadmap

- Expand enterprise tool coverage
- Improve LLM argument reliability and planner correction
- Add richer observability and audit traces
- Cloud Run production deployment in later phase
