# Taskchain Orchestrator

FastAPI-based task orchestration service for AI-agent workflows with a strict `planner -> executor -> verifier` pipeline and PostgreSQL task persistence.

## Why this project

This project demonstrates production-style AI engineering patterns:

- Deterministic baseline behavior with optional LLM augmentation.
- Typed schemas across planning, tool execution, and verification (Pydantic v2).
- Reliability-oriented execution with retries, timeouts, and verification gates.
- API + storage + tests integrated in a clean `src/` layout.

## Architecture

```text
Client/API
   |
POST /tasks/{id}/run
   |
Planner (deterministic or LLM)
   |
Executor (tool registry + retries/timeouts)
   |
Verifier (structural + quality checks)
   |
PostgreSQL (task state + artifacts)
```

Execution artifacts are persisted for each task:

- `plan_json`
- `result_json`
- `verification_json`

## Tech stack

- Python 3.13
- FastAPI
- Pydantic v2
- PostgreSQL + psycopg3
- pytest, Ruff, Black
- Optional OpenAI integration for LLM planner/tool behavior

## Repository layout

- `src/orchestrator_api/`: application package and API entrypoint.
- `src/orchestrator_api/app/`: planner, executor, verifier, storage, UI, and adapters.
- `tests/`: unit tests.
- `tests/integration/`: integration and optional live-LLM tests.
- `company_details/company_sim/`: company/policy simulation data used by tools.
- `data/`: local retrieval corpus/index assets.

## Quick start

1. Create and activate a virtual environment.

```bash
python -m venv venv
source venv/bin/activate
```

2. Install project and dev dependencies.

```bash
python -m pip install -e ".[dev]"
```

3. Set required environment variables.

```bash
export ORCHESTRATOR_DATABASE_URL="postgresql://user:pass@127.0.0.1:5432/orchestrator"
```

4. Run the API.

```bash
make run
```

Service starts at `http://127.0.0.1:8000`.

## API endpoints

- `GET /health` (`/healthz`, `/live` aliases): liveness.
- `GET /`: minimal UI homepage.
- `GET /tools`: list available executor tools.
- `POST /tasks`: create a task.
- `GET /tasks/{task_id}`: fetch task status and artifacts.
- `POST /tasks/{task_id}/run`: execute planner -> executor -> verifier pipeline.

## Example API usage

Create a task:

```bash
curl -sS -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Prepare an executive update for Atlas Checkout migration and include risks.",
    "context": {"project": "Atlas Checkout", "priority": "high"}
  }'
```

Run a task:

```bash
curl -sS -X POST http://127.0.0.1:8000/tasks/<TASK_ID>/run \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Testing and quality

Run full test suite:

```bash
make test
```

Run deterministic PostgreSQL integration flow:

```bash
RUN_POSTGRES_INTEGRATION_TESTS=1 python -m pytest tests/integration/test_api_real_world_flow.py
```

Run live LLM integration flow (optional):

```bash
RUN_POSTGRES_INTEGRATION_TESTS=1 RUN_LIVE_LLM_TESTS=1 OPENAI_API_KEY=<key> \
python -m pytest tests/integration/test_live_llm_flow.py
```

Formatting/linting:

```bash
make fmt
make lint
```

## Configuration

Core runtime:

- `ORCHESTRATOR_DATABASE_URL` (required)
- `ORCHESTRATOR_PLANNER_MODE` = `deterministic` | `llm`
- `ORCHESTRATOR_EXECUTOR_MODE` = `deterministic` | `llm`

LLM settings:

- `ORCHESTRATOR_LLM_PROVIDER` (default: `openai`)
- `OPENAI_API_KEY`
- `ORCHESTRATOR_LLM_MODEL` (default: `gpt-4o-mini`)
- `ORCHESTRATOR_LLM_BASE_URL`
- `ORCHESTRATOR_LLM_MAX_RETRIES`
- `ORCHESTRATOR_LLM_BACKOFF_S`
- `ORCHESTRATOR_LLM_TRACE` (`1` to enable request tracing logs)

Timeouts and retries:

- `ORCHESTRATOR_PLANNER_TIMEOUT_S`
- `ORCHESTRATOR_EXECUTOR_LLM_TIMEOUT_S`
- `ORCHESTRATOR_TOOL_TIMEOUT_S`
- `ORCHESTRATOR_TOOL_MAX_RETRIES`
- `ORCHESTRATOR_TOOL_BACKOFF_S`

Retrieval and company data:

- `ORCHESTRATOR_COMPANY_SIM_ROOT`
- `ORCHESTRATOR_RAG_INDEX_PATH`
- `ORCHESTRATOR_RAG_RERANK_MODE` = `auto` | `deterministic` | `llm`
- `ORCHESTRATOR_RAG_RERANK_TIMEOUT_S`

## Current status and roadmap

- Phase 1: complete (local + Docker vertical slice, API/UI, PostgreSQL task persistence).
- Phase 2: complete (optional OpenAI-backed planner/tool paths with deterministic fallback).
- Phase 3: in progress (expanded toolset, stronger verification, reliability hardening, observability).
- Phase 4: planned (Cloud Run deployment + managed Postgres/Cloud SQL).

## License

Choose a license before publishing publicly (MIT is common for portfolio projects).
