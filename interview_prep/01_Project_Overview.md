# Project Overview

tags: #overview #system-design

## 30-second Pitch
Taskchain Orchestrator is a FastAPI service that runs tasks through a strict `planner -> executor -> verifier` pipeline, persists all artifacts in PostgreSQL, and supports two modes:
- deterministic (reliable baseline)
- LLM-augmented (optional intelligence layer with deterministic fallback)

## Problem It Solves
- Teams need repeatable task automation, not one-off prompts.
- Pure LLM pipelines are brittle for production workflows.
- This service enforces typed schemas, tool boundaries, verification gates, and traceable storage.

## Current Scope You Can State in Interviews
- Phase 1 complete: API/UI + deterministic orchestration + PostgreSQL persistence.
- Phase 2 complete: OpenAI-backed planner/tool mode with graceful fallback.
- Phase 3 in progress: expanded tools, stronger verification, reliability hardening, observability.
- Phase 4 planned: production deployment (Cloud Run + managed database).

## Core Flow
1. `POST /tasks` creates a queued task.
2. `POST /tasks/{task_id}/run` executes planner, executor, verifier.
3. Task status moves to `succeeded` or `failed`.
4. `plan_json`, `result_json`, `verification_json` are persisted.

## Tech Stack
- Python 3.13
- FastAPI + Pydantic v2
- PostgreSQL + psycopg3
- SQLite FTS5 for local RAG over prior issues/incidents
- Optional OpenAI Chat Completions adapter
- pytest, Ruff, Black

## Fast Facts to Memorize
- Modes: `ORCHESTRATOR_PLANNER_MODE`, `ORCHESTRATOR_EXECUTOR_MODE` (`deterministic|llm`)
- Reliability levers: timeout, retries, fail-fast, argument repair, plan arg normalization
- Evidence quality: incident-style plans require retrieval evidence plus policy/governance citation

See also: [[02_Architecture_Deep_Dive]], [[05_LLM_Integration_Story]], [[04_Testing_Strategy]]

