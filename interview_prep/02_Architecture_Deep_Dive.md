# Architecture Deep Dive

tags: #architecture #fastapi #backend

## High-level Diagram
```mermaid
flowchart TD
    A[Client] --> B[POST /tasks]
    A --> C[POST /tasks/{id}/run]
    B --> S[(PostgreSQL tasks table)]
    C --> P[Planner]
    P --> E[Executor]
    E --> V[Verifier]
    V --> S
    S --> A
```

## Main Components
- API wiring: `src/orchestrator_api/main.py`
- Schemas: `src/orchestrator_api/app/models.py`
- Planner: `src/orchestrator_api/app/planner.py`
- Executor + tool registry: `src/orchestrator_api/app/executor.py`
- Verifier: `src/orchestrator_api/app/verifier.py`
- Storage: `src/orchestrator_api/app/storage.py`
- LLM adapter: `src/orchestrator_api/app/llm.py`
- Company/retrieval tools: `src/orchestrator_api/app/company_tools.py`, `src/orchestrator_api/app/retrieval.py`, `src/orchestrator_api/app/rag_sqlite.py`

## Runtime Lifecycle
1. App boots, loads env values, validates DB URL, constructs storage/planner/executor.
2. Planner creates typed `Plan(steps=[...])`.
3. Executor validates each tool call input/output through Pydantic models.
4. Verifier checks structural completeness plus quality/evidence rules.
5. Storage writes final task state and artifacts.

## Why This Design Works
- Separation of concerns keeps each layer testable.
- Typed contracts reduce silent failures between components.
- Verification layer prevents "successful but low-quality" outputs from being marked done.
- Persisted artifacts make debugging and auditing straightforward.

## Important Endpoint Behaviors
- `/health`, `/healthz`, `/live` all report liveness.
- `/tools` exposes available executor tools.
- `/tasks/{id}` returns current status plus stored artifacts.
- `/tasks/{id}/run` captures run metadata (duration, retries, per-step/tool timing).

## Interview Talking Point
> [!note]
> "I intentionally used a pipeline where planner decides, executor does, verifier judges. This made it easy to add LLM behavior without compromising deterministic reliability."

See: [[03_Key_Design_Decisions]], [[04_Testing_Strategy]]

