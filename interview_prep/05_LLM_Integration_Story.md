# LLM Integration Story

tags: #llm #openai #reliability

## Core Message
LLM integration is an augmentation layer, not a single point of failure.

## How It Works
1. App reads planner/executor modes from env.
2. If LLM mode is enabled and adapter exists, planner/tools can use LLM.
3. LLM planner output is validated, sanitized, and normalized.
4. If LLM planner fails, system falls back to deterministic planning.
5. Executor still enforces typed input/output schemas either way.

## Adapter Design
- File: `src/orchestrator_api/app/llm.py`
- Uses OpenAI Chat Completions REST API.
- Requests structured JSON via model schema.
- Has retry/backoff around network/model failures.

## Safety and Reliability Controls
- Allowlist tool validation in planner.
- Tool argument sanitization and defaults.
- Executor argument repair on validation failures.
- Timeout + retry per tool call.
- Verification gate after execution.

## Retrieval + LLM Rerank
- `search_previous_issues` primarily uses deterministic SQLite FTS retrieval.
- Optional LLM reranking can reorder candidates.
- If rerank fails, falls back to deterministic ranking.

## Interview Framing
Use this structure:
1. "Deterministic first for reliability."
2. "LLM used where it adds planning/ranking quality."
3. "Fallback and schema validation protect production behavior."
4. "Verification prevents low-quality outputs from being accepted."

## Crisp Answer for "Why not pure LLM?"
- Determinism gives predictable baseline behavior and easier debugging.
- Typed contracts reduce hidden format drift.
- Fallback keeps service available when model or network fails.

See: [[03_Key_Design_Decisions]], [[04_Testing_Strategy]]

