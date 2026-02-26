# Mock Interview Q and A

tags: #mock-interview #qa

## Architecture
Q: Why split planner, executor, and verifier?
A: It isolates responsibilities. Planner decides steps, executor runs tools with runtime controls, verifier enforces output quality. This separation made fallback logic and testing straightforward.

Q: Why store `plan_json`, `result_json`, and `verification_json`?
A: Auditability and debugging. I can inspect exactly what was planned, executed, and why it passed or failed.

Q: Why FastAPI + Pydantic?
A: Strong request/response validation, typed contracts, and fast development for service-oriented APIs.

## Reliability
Q: What happens if LLM is down?
A: Planner falls back to deterministic planning; tool execution remains schema-validated and verifier-gated.

Q: How do you prevent bad tool payloads?
A: Input/output schemas per tool, planner arg sanitization, and executor arg repair for common LLM mismatch patterns.

Q: How do you handle long or flaky tool calls?
A: Per-tool timeout, retry/backoff policy, and fail-fast option in executor.

## Retrieval and Verification
Q: How do you ensure incident answers are grounded?
A: Incident plans use retrieval tools and policy references, then verifier requires successful evidence and policy/governance citations.

Q: Why combine deterministic retrieval with optional LLM rerank?
A: Deterministic retrieval gives stable recall and traceability; LLM rerank improves ordering quality when available without becoming mandatory.

## Testing
Q: How do you test this system?
A: Layered approach: unit tests for modules, API lifecycle tests, Postgres integration tests, and optional live LLM tests behind env flags.

Q: What regression did tests catch?
A: Argument-shape and verifier quality issues, especially around summary entity coverage and incident evidence requirements.

## Behavioral
Q: Describe a hard tradeoff.
A: I chose deterministic-first architecture over pure LLM flexibility to optimize reliability and debuggability.

Q: What would you do next?
A: Expand observability, add stronger semantic verification, and productionize deployment on managed cloud infrastructure.

## 60-second Closing Pitch
"I built this project to show production-style AI orchestration, not only prompt demos. The system has typed boundaries, fallback behavior, verification gates, and integration tests. I can explain each tradeoff, and I can demo deterministic and LLM modes with clear reliability controls."

