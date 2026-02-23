# Repository Guidelines

This project is a FastAPI task-orchestration service in a `src/` layout with tests under `tests/` and PostgreSQL-backed task data.

## Current Project Context (as of latest repo state)
- Phase 1 is complete: local/Docker vertical slice, FastAPI API/UI, PostgreSQL-backed task persistence, deterministic planner/executor/verifier flow.
- Phase 2 is complete: optional OpenAI-backed LLM planner + tool execution via adapter routing, with deterministic fallback behavior and LLM integration test scaffolding.
- Phase 3 is not complete yet: broader toolset, stronger verification, reliability hardening, and observability expansion remain roadmap work.
- Phase 4 is not complete yet: Cloud Run production deployment and managed Postgres/Cloud SQL are planned later.

## Repository Layout
- `src/orchestrator_api/`: application package and API entrypoint.
- `src/orchestrator_api/app/`: planner, executor, verifier, storage, UI, and LLM adapter modules.
- `tests/`: unit/integration tests, including optional live LLM integration test.
- PostgreSQL connection is configured via `ORCHESTRATOR_DATABASE_URL` (see `.env.example`).
- `venv/`: local virtual environment only; do not commit.

## Environment Setup
- Activate environment: `source venv/bin/activate`.
- Install project + dev dependencies: `python -m pip install -e ".[dev]"`.
- Use `.env.example` as the configuration template; keep secrets in `.env` only.

## Build, Test, and Development Commands
- Run app: `make run` (uvicorn on `127.0.0.1:8000`).
- Run all tests: `make test` or `python -m pytest tests`.
- Run deterministic integration flow: `python -m pytest tests/integration/test_api_real_world_flow.py`.
- Run live LLM integration flow (optional): set `RUN_LIVE_LLM_TESTS=1` and `OPENAI_API_KEY`, then run `python -m pytest tests/integration/test_live_llm_flow.py`.
- Format: `make fmt` (Black).
- Lint: `make lint` (Ruff).

## Runtime Configuration Notes
- Planner mode: `ORCHESTRATOR_PLANNER_MODE=deterministic|llm`.
- Executor mode: `ORCHESTRATOR_EXECUTOR_MODE=deterministic|llm`.
- LLM provider defaults to OpenAI via `ORCHESTRATOR_LLM_PROVIDER=openai`.
- Core LLM settings: `OPENAI_API_KEY`, `ORCHESTRATOR_LLM_MODEL`, `ORCHESTRATOR_LLM_BASE_URL`.
- Timeout/retry settings exist for planner, LLM executor, and deterministic tool calls (see `.env.example`).

## Coding Style & Naming
- Follow PEP 8, 4-space indentation, and type hints on public functions.
- Keep public models strict and schema-driven (Pydantic v2).
- Prefer `pathlib.Path` for file paths and short docstrings for modules/classes/functions.

## Testing Guidelines
- Use `test_*.py` files and `test_*` function names.
- Keep fast unit tests in `tests/` and slower end-to-end scenarios in `tests/integration/`.
- Add regression tests with each bug fix, especially around planner/executor/verifier interactions and API validation behavior.

## Security & Configuration Tips
- Never commit real secrets; `.env` must remain git-ignored.
- Agent rule: do not read `.env` or `.env.example` without explicit user permission in the current conversation.
- Validate and constrain external inputs at API and tool boundaries.
- Keep dependency updates scoped and rerun test suites after updates.

## Dataset Handling Rule (Context-Safe)
- For dataset files, use a metadata-first workflow and avoid full-file reads by default.
- Always start with lightweight inspection only: file size, row count, schema/header, and small samples.
- Never load or print entire large datasets into context (CSV/JSON/archives/binaries); read bounded slices/chunks only.
- Prefer streaming/chunked commands and aggregated summaries over raw dumps.
- If deeper reads are required, ask for explicit user approval and define strict limits first (target columns, row cap, chunk size).
- For compressed database dumps (e.g., Mongo archives), inspect metadata and restore/export only scoped subsets needed for the task.
