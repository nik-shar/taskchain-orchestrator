# Orchestrator API Tutorial (Step-by-Step)

This tutorial teaches the project as a sequence of small learning chunks.
Each chunk has:

- What you learn
- Theory
- Where it exists in this repo
- Example (with code)
- Quick practice

Use this file as your long-term study guide so we do not need to load the full repository repeatedly.

---

## Chunk 0: Project Mental Model

### What you learn

- What this system is trying to solve
- Why it uses a planner/executor/verifier pipeline

### Theory

This project is an orchestration backend. A user sends a task. The system:

1. Plans the work (`Plan`)
2. Executes tool calls (`Executor`)
3. Verifies output quality (`Verifier`)
4. Stores everything for auditability (`PostgreSQL`)

This is different from "single LLM response" architecture. Here, each stage has explicit structure and validation.

### Where in code

- `src/orchestrator_api/main.py`
- `src/orchestrator_api/app/models.py`

### Example flow

```text
POST /tasks  -> task row created (queued)
POST /tasks/{id}/run -> planner builds steps
                     -> executor runs tools
                     -> verifier validates
                     -> storage updates status
GET /tasks/{id} -> full plan/result/verification artifact
```

### Quick practice

1. Start app: `make run`
2. Open `http://127.0.0.1:8000/`
3. Create, run, and fetch one task.

---

## Chunk 1: API + Schema-First Contracts

### What you learn

- How FastAPI + Pydantic enforce strict contracts
- Why schema validation is central to reliability

### Theory

Schema-first design means all external and internal boundaries are typed:

- Request payloads (`CreateTaskRequest`)
- Plan shapes (`Plan`, `Step`, `ToolCall`)
- Verification results (`VerificationResult`)
- Tool IO models (strict, `extra="forbid"`)

If a payload is invalid, it fails early with a clear error.

### Where in code

- `src/orchestrator_api/app/models.py`
- `src/orchestrator_api/app/executor.py` (`StrictModel` and per-tool input/output)

### Example code

```python
class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)

class Step(BaseModel):
    step_id: str
    description: str
    tool_calls: list[ToolCall] = Field(default_factory=list)

class Plan(BaseModel):
    steps: list[Step] = Field(default_factory=list)
```

### API behavior examples

- Empty task rejected (422): tested in `tests/integration/test_api_real_world_flow.py`
- Wrong context type rejected (422): same integration test

### Quick practice

Send an invalid create payload:

```bash
curl -s -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"task":"","context":{}}'
```

---

## Chunk 2: Persistence Layer (PostgreSQL + JSONB)

### What you learn

- How task lifecycle state is persisted
- Why JSONB is used for plan/result/verification

### Theory

The system stores structured artifacts:

- `plan_json`: what it decided to do
- `result_json`: what happened
- `verification_json`: whether the result is acceptable

This creates auditable runs and easy debugging.

### Where in code

- `src/orchestrator_api/app/storage.py`

### Schema (simplified)

```sql
CREATE TABLE IF NOT EXISTS tasks (
  task_id UUID PRIMARY KEY,
  input_task TEXT NOT NULL,
  status TEXT NOT NULL,
  context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  plan_json JSONB,
  result_json JSONB,
  verification_json JSONB,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
```

### Key design details

- Migration runs automatically on startup.
- Thread lock protects storage operations.
- `update_task` merges new status/artifacts and returns refreshed row.

### Quick practice

After running one task, fetch it:

```bash
curl -s http://127.0.0.1:8000/tasks/<TASK_ID>
```

Look at `plan_json`, `result_json`, `verification_json`.

---

## Chunk 3: Planner Design (Deterministic + LLM)

### What you learn

- How plans are constructed
- How planner mode switches work
- How argument normalization prevents invalid tool calls

### Theory

Planner modes:

- `deterministic`: rule-based fixed step construction
- `llm`: model generates plan, then tool names/args are validated and normalized
- If LLM fails, planner falls back to deterministic mode

This preserves system availability even when the model path is unstable.

### Where in code

- `src/orchestrator_api/app/planner.py`

### Deterministic strategy

Base steps:

1. `extract_entities`
2. `extract_deadlines`
3. `extract_action_items`
4. `classify_priority`
5. `summarize`

Incident/issue-like tasks add retrieval steps:

- `search_previous_issues`
- `search_incident_knowledge`
- `fetch_company_reference` for policy evidence

### Example code (planner routing)

```python
if self.mode == "llm" and self.llm_planner is not None:
    try:
        return self.llm_planner.build_plan(task_text, context=context)
    except Exception:
        return build_plan(task_text, context=context)
return build_plan(task_text, context=context)
```

### Argument normalization concept

LLM plans often miss required args. Normalization auto-fills from context:

- `metrics_query`: inject `service/start_time/end_time`
- `summarize`: inject `text` and fallback `max_words`
- `search_incident_knowledge`: inject query/time/service/severity defaults
- `jira_search_tickets`: remove unsupported args

### Quick practice

Compare deterministic plan outputs for:

1. Normal text task
2. Incident task (`P1`, `outage`, `alert`)

You should see retrieval steps added only for incident/issue signals.

---

## Chunk 4: Executor and Tool Runtime

### What you learn

- How tools are registered and executed
- Timeout/retry strategy
- Structured execution telemetry

### Theory

Executor responsibilities:

1. Validate tool args against input schema
2. Run tool with timeout (`ThreadPoolExecutor`)
3. Validate tool output schema
4. Retry on failure using configured policy
5. Return per-tool result with timing and attempts

### Where in code

- `src/orchestrator_api/app/executor.py`

### Tool result shape

```json
{
  "tool": "summarize",
  "status": "ok",
  "output": {"summary": "..."},
  "attempts": 1,
  "duration_ms": 3.42
}
```

### Plan-level telemetry

`result_json.execution_metadata` includes:

- `total_tools`
- `total_duration_ms`
- `error_count`

### Built-in deterministic tools

- `extract_entities`
- `extract_deadlines`
- `extract_action_items`
- `classify_priority`
- `summarize`

These are simple and predictable baselines for reliability.

### Quick practice

Run any task and inspect:

`result_json.steps[*].tool_results[*].attempts/duration_ms`

---

## Chunk 5: Verifier as a Reliability Gate

### What you learn

- Why execution success is not enough
- How business-specific quality checks are enforced

### Theory

Verifier checks:

1. Every planned step has a matching result
2. Every tool call has a matching tool result
3. No tool failed
4. Summary exists
5. Summary references extracted entities (quality heuristic)

Incident-specific gates:

- Must include at least one successful incident evidence source:
  `search_incident_knowledge` or `search_previous_issues` or `jira_search_tickets`
- Must include at least one successful policy/governance citation via `fetch_company_reference`

### Where in code

- `src/orchestrator_api/app/verifier.py`
- Tests: `tests/test_verifier.py`

### Example failure reason

```text
Incident plan requires at least one successful evidence source ...
```

### Quick practice

Read these tests:

- `tests/test_verifier.py`
- `tests/test_tasks.py` (`Summary does not reference extracted entities.`)

They show how verifier can force final task status to `failed` even when execution ran.

---

## Chunk 6: Company Tool Integrations

### What you learn

- How orchestration tools connect to external/mock systems
- How policy/config retrieval is handled

### Theory

Company tools include:

- Static references from files (`fetch_company_reference`)
- HTTP tools (`jira_search_tickets`, `metrics_query`, `logs_search`)
- Retrieval wrappers (`search_incident_knowledge`, `search_previous_issues`)

Each tool has strict input/output Pydantic models.

### Where in code

- `src/orchestrator_api/app/company_tools.py`

### Static reference retrieval concept

`source` is mapped to a controlled path:

- `policy_v1`, `policy_v2`, `governance_notes`, `oncall_rota`, etc.

Then `_extract_excerpt` finds relevant nearby lines based on query terms.

### HTTP tool concept

`_request_json` builds URL + query params, sends GET, and validates JSON.
Base URLs are environment-configurable:

- `COMPANY_JIRA_BASE_URL`
- `COMPANY_METRICS_BASE_URL`
- `COMPANY_LOGS_BASE_URL`

### Quick practice

Call tool list endpoint and verify availability:

```bash
curl -s http://127.0.0.1:8000/tools
```

---

## Chunk 7: Incident Retrieval Theory (Deterministic Local Search)

### What you learn

- How incident knowledge retrieval works without vector DB
- Scoring and confidence/fallback logic

### Theory

`search_incident_knowledge` pipeline:

1. Build corpus from:
   - `company_sim/policies/*.md`
   - `company_sim/docs/*.md`
   - `company_sim/mock_systems/data/jira_tickets.json`
2. Chunk documents
3. Tokenize query and chunks
4. Score with lexical overlap:

```text
score = overlap / sqrt(len(query_tokens) * len(chunk_tokens))
```

5. Apply metadata filters (`service`, `severity`, time window)
6. Return top-k hits + confidence + fallback recommendation

### Where in code

- `src/orchestrator_api/app/retrieval.py`

### Confidence thresholds

- High: top score >= 0.5
- Medium: >= 0.22
- Low: below that, with fallback recommendation

### Quick practice

Run retrieval unit tests:

```bash
python -m pytest tests/test_retrieval.py -q
```

---

## Chunk 8: RAG with SQLite FTS5 (`search_previous_issues`)

### What you learn

- How local RAG index is built and queried
- How metadata filters and BM25 ranking work
- How fallback broadening works

### Theory

This project uses SQLite FTS5 as a lightweight local retrieval engine:

- Build index from canonical JSONL corpus
- Store text chunks + metadata columns
- Query with FTS and optional filters
- Rank by BM25 score (`ORDER BY bm25(...) ASC`)

Benefits:

- Fast local development
- No external vector infrastructure required
- Deterministic and inspectable

### Where in code

- `src/orchestrator_api/app/rag_sqlite.py`
- `src/orchestrator_api/app/company_tools.py` (`search_previous_issues`)

### Query-time filter broadening

If strict filters produce zero hits, `_search_rag_with_relaxation` progressively relaxes constraints:

1. Source-specific relax
2. Drop source/time constraints
3. Drop project constraint

This reduces false-zero retrieval.

### Output semantics

`SearchPreviousIssuesOutput` includes:

- `ranking_mode`: `deterministic` or `llm`
- `confidence`
- `recommend_fallback`
- citation fields per hit

### Quick practice

Build and query index:

```bash
python scripts/build_rag_index.py
python scripts/query_rag.py --query "checkout timeout incident" --top-k 5
```

---

## Chunk 9: Optional LLM Reranking for Retrieval

### What you learn

- How model reranking is layered on deterministic retrieval
- Why it remains optional

### Theory

Reranking is a second-stage operation:

1. Deterministic retrieval collects candidates
2. LLM receives query + candidate snippets
3. LLM returns relevance scores `[0..1]`
4. Hits reorder by relevance

If LLM fails or is unavailable, system falls back to deterministic ranking.

### Where in code

- `src/orchestrator_api/app/company_tools.py` (`_apply_llm_rerank`)

### Controls

- `ORCHESTRATOR_RAG_RERANK_MODE=auto|deterministic|llm`
- `ORCHESTRATOR_RAG_RERANK_TIMEOUT_S`

### Quick practice

See reranking behavior in:

- `tests/test_company_tools.py` (`test_search_previous_issues_can_use_llm_reranking`)

---

## Chunk 10: LLM Adapter and Structured Outputs

### What you learn

- How OpenAI integration is implemented
- Why structured response mode is used

### Theory

Adapter pattern decouples orchestration logic from provider SDK details.

`OpenAIChatCompletionsAdapter`:

- Sends chat-completions request
- Uses JSON schema response format
- Validates parsed response with Pydantic model
- Handles retries and backoff

Structured output is key because planner/tool outputs must fit strict schemas.

### Where in code

- `src/orchestrator_api/app/llm.py`
- Planner and executor mode routing in `src/orchestrator_api/main.py`

### Important runtime rule

If planner/executor mode is `llm` but adapter is not configured (no key/provider), app startup fails fast.

### Quick practice

Read LLM scaffold tests:

- `tests/test_phase2_scaffold.py`

Then optionally run live integration test:

```bash
RUN_POSTGRES_INTEGRATION_TESTS=1 \
RUN_LIVE_LLM_TESTS=1 \
ORCHESTRATOR_PLANNER_MODE=llm \
ORCHESTRATOR_EXECUTOR_MODE=llm \
python -m pytest tests/integration/test_live_llm_flow.py
```

---

## Chunk 11: UI and Manual Tool Proxy

### What you learn

- Purpose of the built-in UI
- Why there is a separate manual proxy service

### Theory

Two interfaces exist:

1. Main app UI (`/`) in `ui.py`
   - Create task
   - Run task
   - Fetch task
2. Manual proxy app (`manual_tool.py`)
   - Single Swagger for Jira/Metrics/Logs mock APIs
   - Useful for direct tool endpoint testing

### Where in code

- `src/orchestrator_api/app/ui.py`
- `src/orchestrator_api/manual_tool.py`

### Quick practice

Start manual proxy:

```bash
make run-manual-tool
```

Open:

- `http://127.0.0.1:8010/docs`

---

## Chunk 12: Testing Strategy (Confidence Layers)

### What you learn

- How tests are layered
- What each layer protects

### Theory

1. Unit tests: individual modules and tool behavior
2. Integration tests: full API flow against running app + Postgres
3. Optional live LLM integration: end-to-end with real model

This layered strategy catches both logic bugs and integration regressions.

### Where in tests

- Unit:
  `tests/test_planner.py`,
  `tests/test_tools.py`,
  `tests/test_verifier.py`,
  `tests/test_company_tools.py`,
  `tests/test_rag_sqlite.py`
- Integration:
  `tests/integration/test_api_real_world_flow.py`,
  `tests/integration/test_incident_rag_flow.py`

### Quick practice

```bash
make test
python -m pytest tests/integration/test_incident_rag_flow.py
```

---

## Chunk 13: Data Pipeline and RAG Scripts

### What you learn

- How corpus files are prepared
- How indexes are built/queried
- How old SQLite task data migrates to Postgres

### Theory

Main scripts:

- `scripts/prepare_rag_subset.py`
  Builds canonical JSONL corpus from Jira subset + incident CSV
- `scripts/build_rag_index.py`
  Builds SQLite FTS index from corpus
- `scripts/query_rag.py`
  Queries local index with filters
- `scripts/rag_answer.py`
  Retrieval + optional LLM grounded answer generation
- `scripts/migrate_sqlite_to_postgres.py`
  Moves old task rows from SQLite to PostgreSQL

Canonical corpus document shape:

```json
{"doc_id":"...","source":"jira|incident_event_log","text":"...","metadata":{...}}
```

### Where in docs

- `data/RAG_SUBSET_SPEC.md`
- `data/rag_subset_spec_v1.json`

### Quick practice

```bash
python scripts/prepare_rag_subset.py \
  --spec-file data/rag_subset_spec_v1.json \
  --output data/rag_corpus_subset_v1.jsonl
python scripts/build_rag_index.py --corpus data/rag_corpus_subset_v1.jsonl
```

---

## Chunk 14: Operational Modes and Config Concepts

### What you learn

- Which env vars matter most
- How runtime behavior changes by mode

### Theory

Core mode switches:

- `ORCHESTRATOR_PLANNER_MODE=deterministic|llm`
- `ORCHESTRATOR_EXECUTOR_MODE=deterministic|llm`

Timeout/retry controls:

- Planner timeout
- LLM timeout/retries/backoff
- Tool timeout/retries/backoff
- Company tool timeout

Data/retrieval controls:

- `ORCHESTRATOR_COMPANY_SIM_ROOT`
- `ORCHESTRATOR_RAG_INDEX_PATH`
- `ORCHESTRATOR_RAG_RERANK_MODE`

### Quick practice

Run deterministic first, then llm mode. Compare `plan_json` and `result_json`.

---

## Chunk 15: What Is Done vs Pending (Roadmap Reality)

### Implemented

- Deterministic orchestration pipeline
- PostgreSQL persistence and migration
- Optional OpenAI planner/executor route
- Incident knowledge retrieval
- Previous-issues local RAG search
- Verifier incident evidence gates
- Execution telemetry metadata

### Still pending / future

- Broader enterprise tool surface
- Stronger self-correction loops for planner/tool arg issues
- Deeper observability and audit traces
- Production cloud deployment stack (Cloud Run + managed DB)

---

## Recommended Study Order (Fast)

1. Chunk 0-3 for architecture + planning basics
2. Chunk 4-6 for execution/verifier/tool boundaries
3. Chunk 7-9 for retrieval and RAG
4. Chunk 10 for LLM integration details
5. Chunk 11-13 for UI/testing/scripts
6. Chunk 14-15 for operations and roadmap

---

## Practice Milestones

### Milestone A (Core)

- Run app
- Create/run/fetch task
- Read `plan_json` and `verification_json`

### Milestone B (Incident path)

- Run incident-style task
- Confirm `search_previous_issues`, `search_incident_knowledge`, `fetch_incident_policy` appear in plan
- Inspect retrieval hits and citation fields

### Milestone C (RAG tooling)

- Build/query SQLite index using scripts
- Try strict filters and observe relaxation behavior

### Milestone D (LLM modes)

- Enable planner/executor llm mode
- Compare outputs vs deterministic
- Observe fallback behavior when LLM path fails

---

## Final Takeaway

This codebase is a practical example of "LLM-optional orchestration":

- deterministic core for reliability
- strict schemas for safety
- retrieval + verification for evidence quality
- LLM added as controlled augmentation, not as a single point of failure
