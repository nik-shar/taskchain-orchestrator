# Orchestrator API Summary

## 1) Project in one line

This repository is a FastAPI service that executes tasks through a strict pipeline:

`Planner -> Executor -> Verifier -> Storage`

It supports deterministic behavior by default and optional OpenAI-backed planning/tool execution with safe fallback.

## 2) Current progress snapshot

- Phase 1: complete
  Local vertical slice, API/UI, deterministic orchestration, PostgreSQL persistence.
- Phase 2: complete
  OpenAI adapter integration, mode-based planner/tool routing, fallback behavior, test scaffolding.
- Phase 3: in progress
  Incident retrieval slice implemented (local knowledge search, RAG previous-issues search, verifier evidence gates, telemetry). Hardening and observability expansion still pending.
- Phase 4: planned
  Cloud Run deployment + managed Postgres/Cloud SQL.

## 3) Architecture map

- API entrypoint: `src/orchestrator_api/main.py`
- Domain models: `src/orchestrator_api/app/models.py`
- Planner (deterministic + LLM): `src/orchestrator_api/app/planner.py`
- Executor/tool runtime: `src/orchestrator_api/app/executor.py`
- Verifier gates: `src/orchestrator_api/app/verifier.py`
- PostgreSQL backend: `src/orchestrator_api/app/storage.py`
- Company tools and adapters: `src/orchestrator_api/app/company_tools.py`
- Incident retrieval core: `src/orchestrator_api/app/retrieval.py`
- Local RAG index/search: `src/orchestrator_api/app/rag_sqlite.py`
- OpenAI adapter: `src/orchestrator_api/app/llm.py`
- Built-in browser UI: `src/orchestrator_api/app/ui.py`
- Manual proxy tester: `src/orchestrator_api/manual_tool.py`

## 4) Runtime flow

1. `POST /tasks` creates a queued task row.
2. `POST /tasks/{task_id}/run` sets status to `running`.
3. Planner builds typed `Plan` steps.
4. Executor validates + runs each tool call with timeout/retry.
5. Verifier checks output consistency and incident evidence rules.
6. Task is stored as `succeeded` or `failed` with `plan_json`, `result_json`, `verification_json`.

## 5) Technology stack

- Python 3.13+
- FastAPI
- Pydantic v2 (strict schemas)
- PostgreSQL + psycopg3 (JSONB task artifacts)
- SQLite FTS5 (local RAG for previous issues)
- OpenAI Chat Completions API (structured JSON mode)
- Uvicorn
- Docker / Docker Compose (local infra and mock services)
- pytest, Black, Ruff

## 6) Topics and theory index (quick brief)

1. API contracts and schema-first design
   FastAPI + Pydantic enforce valid inputs/outputs and typed responses.
2. Orchestration pipeline design
   Planner decides what to do, executor does it, verifier decides if it is good enough.
3. Deterministic NLP tools
   Rule-based extraction/classification/summarization gives stable baseline behavior.
4. LLM integration with graceful degradation
   LLM path is optional; deterministic path remains the reliability anchor.
5. Strict tool boundaries
   Each tool has explicit input/output schema, timeout, retries, and structured errors.
6. Retrieval fundamentals
   Chunking, tokenization, lexical overlap scoring, confidence thresholds, fallback flags.
7. Local RAG with SQLite FTS5
   Indexing JSONL docs, metadata filtering, BM25 ranking, snippet generation.
8. Optional LLM reranking
   Candidate set from deterministic retrieval, then relevance re-scored by model.
9. Verification as a quality gate
   Incident tasks must include evidence and policy/governance citation signals.
10. Persistence and auditability
    Full execution artifacts are stored in Postgres for traceability.
11. Integration testing strategy
    Unit tests for modules + integration tests for API flows + optional live LLM test.
12. Data preparation pipeline
    Scripts normalize Jira + incident data into a canonical RAG corpus and build indexes.

## 7) Main API/tool capabilities

- Core tools:
  `extract_entities`, `extract_deadlines`, `extract_action_items`, `classify_priority`, `summarize`
- Company tools:
  `fetch_company_reference`, `jira_search_tickets`, `metrics_query`, `logs_search`
- Retrieval tools:
  `search_incident_knowledge` (incident corpus search),
  `search_previous_issues` (SQLite RAG over Jira + incident subset)

## 8) Test and script landscape

- Unit tests: `tests/test_*.py`
- Integration tests: `tests/integration/`
- Live LLM test (opt-in): `tests/integration/test_live_llm_flow.py`
- Data/index scripts: `scripts/prepare_rag_subset.py`, `scripts/build_rag_index.py`,
  `scripts/query_rag.py`, `scripts/rag_answer.py`, `scripts/migrate_sqlite_to_postgres.py`

## 9) Learning path pointer

Read `TUTORIAL.md` for a chunked, step-by-step deep dive with theory + examples + code walkthroughs.
