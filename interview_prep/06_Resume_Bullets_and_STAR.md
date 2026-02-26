# Resume Bullets and STAR Stories

tags: #resume #star #behavioral

## Resume Bullets (Ready to Customize)
- Built a FastAPI orchestration service implementing a strict `planner -> executor -> verifier` pipeline with PostgreSQL-backed task artifact persistence.
- Designed dual execution modes (deterministic + OpenAI-augmented) with typed schema validation, fallback logic, and argument-repair safeguards.
- Implemented incident-focused retrieval tooling (policy references + prior issue search with citations) and verification gates that enforce evidence quality.
- Added layered tests (unit, integration, optional live LLM) to validate lifecycle behavior, failure handling, and reliability controls.

## STAR Story 1 - Reliability-First Architecture
Situation:
- Needed an interview-grade AI orchestration project that behaved predictably under failures.

Task:
- Build an end-to-end service where LLM quality gains do not compromise reliability.

Action:
- Implemented deterministic planner/tools as baseline.
- Added optional LLM planner/tool routing with strict schema validation.
- Added fallback from LLM to deterministic planning.
- Added verifier gate and persisted execution artifacts in Postgres.

Result:
- Produced a robust orchestration flow with reproducible behavior and clear failure diagnostics.
- Use your real metric here: `<test pass rate / latency / task success uplift>`.

## STAR Story 2 - Grounded Incident Responses
Situation:
- Needed responses for incident tasks to be evidence-backed, not just fluent summaries.

Task:
- Ensure incident outputs include usable evidence and policy citations.

Action:
- Added incident retrieval tools and previous-issues RAG search.
- Enforced citation fields in retrieval hits.
- Implemented verifier checks that fail runs missing evidence/governance references.

Result:
- Incident outputs became auditable and policy-grounded.
- Use your metric here: `<fewer invalid outputs / better reviewer acceptance>`.

## STAR Story 3 - Test Strategy and Dev Velocity
Situation:
- Needed confidence across deterministic and LLM paths.

Task:
- Build tests that isolate failures quickly.

Action:
- Added fast unit tests per layer.
- Added API lifecycle tests with storage double.
- Added integration tests with real Postgres + optional live LLM.

Result:
- Reduced regression risk while keeping local development fast.
- Use your metric here: `<faster debugging time / fewer regressions>`.

> [!tip]
> Replace placeholder metrics before interviews. Interviewers trust numbers when you can explain exactly how you measured them.

