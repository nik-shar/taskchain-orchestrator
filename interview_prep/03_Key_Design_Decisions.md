# Key Design Decisions

tags: #tradeoffs #design

## 1) Deterministic Baseline First
Decision:
- Keep a deterministic planner and deterministic tool implementations as the default path.

Why:
- Stable and predictable behavior for tests, demos, and production fallback.

Tradeoff:
- Lower language flexibility than fully LLM-native orchestration.

## 2) Optional LLM Routing, Not Mandatory LLM Dependency
Decision:
- Enable LLM modes for planner and selected tools only when configured.

Why:
- Supports gradual adoption and reliability under degraded conditions.

Tradeoff:
- Dual-path complexity (deterministic + LLM code paths).

## 3) Strict Tool Boundaries via Pydantic Models
Decision:
- Validate tool inputs and outputs with explicit schemas.

Why:
- Prevents malformed tool payloads from propagating downstream.

Tradeoff:
- More boilerplate when adding new tools.

## 4) Argument Normalization and Repair
Decision:
- Normalize LLM plan arguments and repair common executor arg-shape mistakes.

Why:
- Improves success rate when model output is close-but-not-perfect.

Tradeoff:
- Must carefully avoid over-repairing invalid requests.

## 5) Verification as a Gate, Not a Log
Decision:
- Mark task `failed` when verification fails (for example, missing summary entities or missing incident evidence).

Why:
- Makes quality first-class and measurable.

Tradeoff:
- More tasks may fail initially, requiring better prompts/tooling.

## 6) Retrieval + Citation Discipline for Incident Workflows
Decision:
- Incident plans require evidence tools and policy/governance citation support.

Why:
- Aligns outputs with operational and audit expectations.

Tradeoff:
- Stricter checks can reject plausible but weakly grounded responses.

## How to Answer "What Would You Improve Next?"
1. Add stronger semantic verification (cross-step consistency checks).
2. Add richer observability traces (structured logs per attempt + tool payload hashes).
3. Add asynchronous/queued execution for long-running tools.
4. Expand production hardening for Cloud Run + managed Postgres.

See also: [[09_Roadmap_and_Risks]]

