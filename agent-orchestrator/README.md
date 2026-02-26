# agent-orchestrator

Agentic orchestration track using FastAPI + LangGraph, developed in a separate repo path to protect the current production-style orchestrator.

## Why we are moving on this path
- Keep the existing service stable while we experiment with agentic behavior.
- Preserve a known-good deterministic baseline for comparison and rollback.
- Validate whether graph-based orchestration improves retrieval quality, recovery, and complex task handling before merging ideas back.
- Avoid high-risk refactors in the original repository.

## Why LangGraph (not only LangChain)
- We already require explicit stages (`plan -> retrieve -> execute -> verify`) and controlled retries.
- We need strict workflow control, deterministic fallbacks, and clear routing on verification failure.
- We need durable per-run state that can later map cleanly to PostgreSQL artifacts.
- LangChain is still useful inside nodes (model/tool abstractions), but LangGraph is the right orchestration layer.

## Decision principles
- Reuse existing company resources and datasets.
- Keep strict schema validation at tool boundaries.
- Keep verifier gates as non-negotiable reliability controls.
- Maintain API compatibility where practical (`/tasks`, `/tasks/{id}/run`, `/tasks/{id}`).
- Build incrementally with measurable parity checks against the current orchestrator.

## V1 roadmap (how we are executing)
1. Step 1: Bootstrap service and workflow skeleton.
2. Step 2: Add PostgreSQL persistence (`tasks` + `task_runs` JSONB artifacts).
3. Step 3: Implement strict schema-validated tool gateway in `execute`. ✅
4. Step 4: Add verifier gates, retry budgets, and deterministic fallback routing. ✅
5. Step 5: Integrate retrieval adapters for company docs/policies and previous issues index. ✅
6. Step 6: Add integration and parity tests against representative prompts. ✅
7. Step 7: Controlled LLM planner enablement with strict fallback. ✅

## Current status
Steps 1, 2, 3, 4, 5, 6, and 7 are complete in this repo.

Implemented:
- FastAPI endpoints: `/tasks`, `/tasks/{id}/run`, `/tasks/{id}`, `/tools`, `/health`
- Typed LangGraph state and compiled workflow
- Node placeholders: `plan`, `retrieve`, `execute`, `verify`, `finalize`
- PostgreSQL-backed storage with auto-migration for `tasks` and `task_runs`
- `task_runs` JSONB persistence for state, plan, tool outputs, and verification artifacts
- Runtime-safe storage initialization for both lifespan-started servers and direct test app usage
- Strict Pydantic tool schemas and deterministic registry for core tools
- Tool execution gateway with timeout/retry controls and per-tool timing/attempt telemetry
- Verifier gates for missing/failed tools, summary-entity consistency, and incident evidence/policy checks
- Retry-budget tracking in workflow state and verification output
- Deterministic fallback routing when planner mode is set to `llm` but LLM planner is unavailable
- OpenAI-backed LLM planner path enabled for `AGENT_ORCHESTRATOR_PLANNER_MODE=llm`
- Optional LLM-backed executor mode for `summarize` and `build_incident_brief` via `AGENT_ORCHESTRATOR_EXECUTOR_MODE=llm`
- Strict deterministic fallback remains active on missing API key, request failure, or invalid plan output
- Retrieval adapters wired to shared datasets:
  - `company_details/company_sim` for incident knowledge (docs/policies + seeded Jira tickets)
  - `data/rag_index.sqlite` for previous-issue search (SQLite FTS with relaxed fallback)
- Citation-ready retrieval metadata in tool outputs (`source_id`, `chunk_id`, `score`, `why_selected`)
- Incident brief synthesis tool (`build_incident_brief`) that converts retrieved evidence into causes/actions/escalation
- Pipeline Explorer UI citation panel for trust/debugging (`/`)
- Retrieval A/B benchmark script for `lexical`, `vector`, and `hybrid_rerank` modes
- In-memory storage adapter retained for unit tests only
- Unit + integration tests covering:
  - tool gateway behavior
  - planner/verifier/retry controls
  - retrieval adapters over shared datasets
  - representative real-world and incident graph flows
  - parity checks against legacy planner tool coverage

## Repository layout
```text
src/agent_orchestrator/
  api/main.py
  config/settings.py
  graph/state.py
  graph/workflow.py
  graph/nodes/{plan,retrieve,execute,verify,finalize}.py
  retrieval/{shared_paths,incident_knowledge,previous_issues}.py
  tools/{schemas,deterministic,registry,gateway}.py
  storage/{base,memory,models,postgres}.py
tests/unit/
tests/integration/
```

## Quick start
```bash
cd agent-orchestrator
python -m pip install -e ".[dev]"
uvicorn agent_orchestrator.api.main:app --reload --port 8010
```
Operational runbook: `RUNBOOK.md` (local + Cloud Run + troubleshooting).

Settings are loaded automatically from `.env` / `.env.local` at repo root.
Set `AGENT_ORCHESTRATOR_DATABASE_URL` in `.env` before startup.
`ORCHESTRATOR_DATABASE_URL` is also accepted as a fallback for compatibility with the main repo.
Optional execution tuning:
`AGENT_ORCHESTRATOR_TOOL_TIMEOUT_S`, `AGENT_ORCHESTRATOR_TOOL_MAX_RETRIES`, `AGENT_ORCHESTRATOR_TOOL_RETRY_BACKOFF_S`.
Optional LLM planner tuning:
`AGENT_ORCHESTRATOR_PLANNER_MODE=llm`, `OPENAI_API_KEY` (or `AGENT_ORCHESTRATOR_OPENAI_API_KEY`),
`AGENT_ORCHESTRATOR_LLM_MODEL`, `AGENT_ORCHESTRATOR_LLM_BASE_URL`,
`AGENT_ORCHESTRATOR_LLM_TIMEOUT_S`, `AGENT_ORCHESTRATOR_LLM_MAX_RETRIES`,
`AGENT_ORCHESTRATOR_LLM_BACKOFF_S`.
Executor mode:
`AGENT_ORCHESTRATOR_EXECUTOR_MODE=deterministic|llm`.
Optional retrieval path overrides:
`AGENT_ORCHESTRATOR_COMPANY_SIM_ROOT`, `AGENT_ORCHESTRATOR_RAG_INDEX_PATH`.
Compatibility fallbacks are supported:
`ORCHESTRATOR_COMPANY_SIM_ROOT`, `ORCHESTRATOR_RAG_INDEX_PATH`.

Run tests:
```bash
pytest -q
```
Note: unit tests use `create_app(storage=InMemoryTaskStorage())` and do not require PostgreSQL.

Run retrieval A/B benchmark:
```bash
make eval-retrieval
```

Optional overrides:
```bash
make eval-retrieval RETRIEVAL_MODE=lexical
make eval-retrieval RETRIEVAL_MODE=vector
make eval-retrieval RETRIEVAL_MODE=hybrid_rerank
make eval-retrieval EVAL_DATASET=../data/retrieval_eval_queries.sample.jsonl
```

## RAG pipeline tutorial (beginner-friendly, code-level)

This section explains Retrieval-Augmented Generation (RAG) in this repo from first principles,
then maps each concept to the exact implementation files.

### 1) What "RAG" means in this project

RAG here is:
1. Retrieve evidence from local sources.
2. Generate a final response using tool outputs, not only model memory.
3. Verify that evidence gates are satisfied before accepting the run.

In this codebase, retrieval is deterministic and local-first:
- `search_incident_knowledge` retrieves policy/docs/ticket evidence from `company_sim`.
- `search_previous_issues` retrieves prior Jira/incident chunks from SQLite FTS (`data/rag_index.sqlite`).

Generation uses:
- `summarize` for a baseline concise response
- `build_incident_brief` (incident tasks) for structured, evidence-driven synthesis

### 2) End-to-end graph flow for RAG

Workflow stages are `plan -> retrieve -> execute -> verify -> finalize`.

Code path:
- Planner decides whether retrieval tools are needed:
  `src/agent_orchestrator/graph/nodes/plan.py`
- Retrieve node records retrieval telemetry only:
  `src/agent_orchestrator/graph/nodes/retrieve.py`
- Execute node actually runs retrieval tools through strict schemas:
  `src/agent_orchestrator/graph/nodes/execute.py`
- Verifier enforces evidence gates:
  `src/agent_orchestrator/graph/nodes/verify.py`

Important behavior:
- If prompt contains any hint in `("incident", "outage", "sev", "latency", "error")`,
  planner includes retrieval tools plus `build_incident_brief`.
- Verifier then requires:
  - non-empty `search_incident_knowledge` results
  - non-empty `search_previous_issues` results
  - at least one policy/runbook-like citation in incident knowledge titles

### 3) Data sources and path resolution

Path resolution is centralized in:
`src/agent_orchestrator/retrieval/shared_paths.py`

Incident corpus root:
- `AGENT_ORCHESTRATOR_COMPANY_SIM_ROOT` (preferred)
- fallback `ORCHESTRATOR_COMPANY_SIM_ROOT`
- default `company_details/company_sim`

SQLite index path:
- `AGENT_ORCHESTRATOR_RAG_INDEX_PATH` (preferred)
- fallback `ORCHESTRATOR_RAG_INDEX_PATH`
- default `data/rag_index.sqlite`

### 4) Retriever A: incident knowledge (`search_incident_knowledge`)

Implementation:
`src/agent_orchestrator/retrieval/incident_knowledge.py`

How it works:
1. Build/load corpus from:
   - `company_sim/policies/*.md`
   - `company_sim/docs/*.md`
   - `company_sim/mock_systems/data/jira_tickets.json`
2. Chunk markdown by paragraph into `KnowledgeChunk` records.
3. Tokenize query + each chunk.
4. Score with lexical overlap:
   `overlap / sqrt(len(query_tokens) * len(chunk_tokens))`
5. Sort descending and return top `limit`.
6. Safety rule: ensure at least one policy/runbook item is present when possible.

Tool contract (schema):
- Input (`SearchIncidentKnowledgeInput`):
  `query`, `limit`, optional `service`, optional `severity`
- Output (`SearchIncidentKnowledgeOutput`):
  `results: [{title, snippet, source_type, source_id, score, why_selected}]`

Schema file:
`src/agent_orchestrator/tools/schemas.py`

### 5) Retriever B: previous issues (`search_previous_issues`)

Implementation:
`src/agent_orchestrator/retrieval/previous_issues.py`

How it works:
1. Query SQLite FTS5 index (`chunks_fts` joined with `chunks`).
2. Build prefix query from tokens:
   - strict pass uses `AND` (higher precision)
   - relaxed pass uses `OR` (higher recall)
3. Apply filters if provided (`service`, `severity`).
4. If no hits, relax filters in order:
   - keep service/severity
   - drop severity
   - drop service + severity
5. Convert FTS `bm25` to relevance in `[0, 1]`.
6. Deduplicate by ticket key and return top `limit`.

Filter semantics in SQL:
- `service` matches project or chunk text
- `severity` matches priority or chunk text

Tool contract:
- Input (`SearchPreviousIssuesInput`):
  `query`, `limit`, optional `service`, optional `severity`, optional `use_llm_rerank`
- Output (`SearchPreviousIssuesOutput`):
  `results: [{ticket, summary, relevance, source, doc_id, chunk_id, score, retrieval_mode, why_selected}]`

### 6) Planner + schema normalization (why runs are stable)

In LLM planner mode, raw model steps are normalized in:
`src/agent_orchestrator/graph/nodes/plan.py`

Normalization guarantees:
1. Required core tools exist (`extract_entities`, `classify_priority`, `summarize`).
2. Retrieval tools and `build_incident_brief` are auto-added for incident-like prompts.
3. Tool args are merged with defaults (for example `query`, `text`, `limit`).
4. Unknown args are dropped to satisfy strict Pydantic schemas.
5. Final summarize step is forced to use original user input text.

This is critical for RAG reliability, especially when LLM planner outputs sparse or noisy args.

### 7) Execute and verify stages (what can fail and why)

Execution layer:
- `src/agent_orchestrator/tools/gateway.py`
- strict input/output validation
- timeout/retry per tool
- per-tool telemetry (`attempts`, `duration_ms`, implementation mode)

Verification layer:
- `src/agent_orchestrator/graph/nodes/verify.py`
- checks missing/failed required tools
- checks summary-entity consistency
- enforces incident evidence gates when incident hints are present
- tracks retry budget (`count`, `remaining`, `budget_exhausted`)

### 8) Hands-on walkthrough

Run the service:
```bash
cd agent-orchestrator
make run
```

Create a task:
```bash
curl -s -X POST "http://127.0.0.1:8010/tasks" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"P1 incident: user profile picture errors causing latency and failures.","context":{"service":"profile-media-api","priority":"Major","severity":"SEV2","status":"Long Term Backlog"}}'
```

`context` is optional, but recommended for better retrieval filtering and deterministic priority classification.

Run it:
```bash
curl -s -X POST "http://127.0.0.1:8010/tasks/<TASK_ID>/run"
```

Fetch final task state:
```bash
curl -s "http://127.0.0.1:8010/tasks/<TASK_ID>"
```

Inspect detailed run artifacts from PostgreSQL (`task_runs` stores full graph state):
```sql
SELECT run_id, status, created_at
FROM task_runs
WHERE task_id = '<TASK_ID>'::uuid
ORDER BY run_id DESC;

SELECT plan_json, tool_results_json, verification_json
FROM task_runs
WHERE task_id = '<TASK_ID>'::uuid
ORDER BY run_id DESC
LIMIT 1;
```

### 9) Debugging checklist for RAG issues

If a run fails incident gates:
1. Check `verification.incident_gate.required`.
2. If `true`, inspect `verification.incident_gate.failures`.
3. Query latest `task_runs.tool_results_json` to inspect retrieval outputs.

Common causes:
- SQLite index missing at `data/rag_index.sqlite` -> previous-issue hits empty.
- Overly narrow query terms -> sparse lexical overlap.
- Service/severity mismatch with corpus values.
- No policy/runbook-titled hit in incident knowledge results.

### 10) Practical tuning guidelines

Use these levers first:
1. Prompt quality:
   include system/component terms (`profile`, `api`, `latency`, `timeout`, `P1`).
2. Retrieval defaults:
   current tool defaults use `limit=3`; increase when needed in plan args.
3. Corpus/index path:
   ensure env overrides point to expected datasets.
4. Execution mode:
   keep planner `llm` if desired; use deterministic executor when isolating retrieval behavior.

### 11) Mental model summary

In this repo, RAG is not a single function. It is a controlled graph behavior:
1. Planner decides retrieval requirements.
2. Retrieval tools gather evidence from two local retrieval systems.
3. Executor enforces strict schemas and runtime controls.
4. Verifier enforces quality/evidence gates before accepting output.

That structure is why the pipeline remains debuggable and production-lean even with optional LLM modes.

### 12) From raw tabular files to searchable RAG (your "two CSV files" question)

If you start with two tabular datasets, the pipeline is:
1. Normalize each row into a canonical document JSON record.
2. Write all records to one JSONL corpus (`one doc per line`).
3. Chunk document text.
4. Build SQLite FTS index over chunks.
5. Query index during tool execution.

In this repository, source inputs are:
- Jira subset export (from Mongo archive; conceptually same as a Jira CSV export)
- Incident CSV (`company_details/incident+management+process+enriched+event+log/incident_event_log.csv`)

The canonical corpus output is:
- `data/rag_corpus_subset_v1.jsonl`

#### 12.1 Canonical document format

Every source row becomes:
```json
{
  "doc_id": "string",
  "source": "jira | incident_event_log",
  "text": "searchable combined text",
  "metadata": { "key": "value", "...": "..." }
}
```

Think of this as your "contract" between data preparation and retrieval:
- Anything that can be mapped to this schema can be indexed.
- Retrieval code does not care whether the original source was CSV, JSON, or Mongo export.

Where this is done:
- `scripts/prepare_rag_subset.py`
  - Jira row -> `_build_jira_text(...)`
  - Incident row -> `_build_incident_text(...)`
  - incident dedup -> `_dedup_incidents(...)` by latest `sys_mod_count`

#### 12.1.1 Concrete row-to-document mapping (CSV mental model)

If your first CSV row is:
- `ticket_id=WLC-43, summary="User profile picture doesn't display", priority=Minor`

Then one indexed document looks like:
```json
{
  "doc_id": "jira:JiraEcosystem:WLC-43",
  "source": "jira",
  "text": "Project: WLC\nIssueType: Bug\nPriority: Minor\nStatus: ...\nSummary: User profile picture doesn't display\nDescription: ...",
  "metadata": {
    "collection": "JiraEcosystem",
    "issue_key": "WLC-43",
    "priority": "Minor",
    "project": "WLC",
    "created": "...",
    "updated": "..."
  }
}
```

If your second CSV row is:
- `number=INC00123, incident_state=Resolved, priority=P1, opened_at=..., closed_at=...`

Then one indexed document looks like:
```json
{
  "doc_id": "incident:INC00123",
  "source": "incident_event_log",
  "text": "Incident: INC00123\nState: Resolved\nPriority: P1\nOpenedAt: ...\nClosedAt: ...",
  "metadata": {
    "incident_number": "INC00123",
    "state": "Resolved",
    "priority": "P1",
    "opened_at": "...",
    "closed_at": "..."
  }
}
```

#### 12.2 What happens to your two datasets

Dataset A (Jira-like):
- Extract selected columns/fields (summary, description, type, priority, status, project, dates, labels).
- Build one normalized text block per issue.
- Attach metadata (`issue_key`, `project`, `priority`, etc.).

Dataset B (incident CSV):
- Deduplicate to one latest row per incident id (`number`).
- Build one normalized text block with fields like state/priority/opened_at/closed_at.
- Attach metadata (`incident_number`, `state`, `priority`, timestamps).

Then both are concatenated into one JSONL corpus.

Script stage mapping:
1. `scripts/prepare_rag_subset.py`:
   extracts + normalizes source rows into canonical JSONL docs.
2. `scripts/build_rag_index.py`:
   chunks canonical docs and builds SQLite FTS index.
3. Runtime retrieval tools:
   query the index/corpus and return evidence for the graph.

Current corpus stats in this repo:
- `data/rag_corpus_subset_v1.jsonl`: `13,230` docs total
- source mix: `3,230 jira` + `10,000 incident_event_log`

#### 12.3 JSONL -> SQLite FTS index

Index build command:
```bash
python scripts/build_rag_index.py \
  --corpus data/rag_corpus_subset_v1.jsonl \
  --index data/rag_index.sqlite
```

What it does internally:
- Calls `orchestrator_api.app.rag_sqlite.build_rag_sqlite_index(...)`
- Splits `text` into chunks (`chunk_chars=900`, `overlap_chars=120` by default)
- Stores chunk rows in `chunks`
- Stores searchable text in FTS5 table `chunks_fts`
- Adds metadata columns for filtering (source, project, priority, dates, etc.)

Current index stats in this repo:
- `data/rag_index.sqlite`
- `chunks`: `14,884`
- source chunk mix: `4,884 jira` + `10,000 incident_event_log`

Why chunk count is larger than doc count:
- long Jira documents split into multiple chunks
- many incident rows are short enough to stay single-chunk

#### 12.4 Query-time path (what happens during a task run)

For `search_previous_issues`:
1. Build FTS query tokens.
2. Try strict search (`AND`) with filters.
3. If zero hits, relax query/filter constraints.
4. Convert `bm25` (lower is better) to normalized relevance.
5. Return top deduped issue hits.

Code:
- `src/agent_orchestrator/retrieval/previous_issues.py`

For `search_incident_knowledge`:
1. Build in-memory corpus from company policies/docs + seeded Jira tickets.
2. Score lexical token overlap.
3. Keep top hits; ensure at least one policy/runbook-like hit when possible.

Code:
- `src/agent_orchestrator/retrieval/incident_knowledge.py`

#### 12.5 If your actual starting point is literally two CSV files

You have two options:
1. Quick path: convert both CSVs to the canonical JSONL schema (`doc_id/source/text/metadata`) and run `build_rag_index.py`.
2. Structured path: adapt `scripts/prepare_rag_subset.py` with source-specific row-to-text builders (same pattern used for incident rows now).

As long as you produce valid canonical JSONL, the rest of the RAG pipeline (chunking/index/query/tools/verification) works unchanged.

#### 12.6 Minimal "from two CSVs" execution checklist

Run these commands from the repository root (`project/`), not from `agent-orchestrator/`.

1. Produce canonical JSONL:
```bash
python scripts/prepare_rag_subset.py \
  --spec-file data/rag_subset_spec_v1.json \
  --output data/rag_corpus_subset_v1.jsonl
```

2. Build index:
```bash
python scripts/build_rag_index.py \
  --corpus data/rag_corpus_subset_v1.jsonl \
  --index data/rag_index.sqlite
```

3. Smoke-test retrieval:
```bash
python scripts/query_rag.py \
  --index data/rag_index.sqlite \
  --query "profile picture errors P1 incident"
```

#### 12.7 Hybrid retrieval with Chroma (implemented)

`search_previous_issues` now supports hybrid retrieval:
- lexical branch: SQLite FTS (`data/rag_index.sqlite`)
- vector branch: Chroma collection (default path `data/rag_chroma`)
- fusion: Reciprocal Rank Fusion (RRF), then optional deterministic rerank

Hybrid mode switch:
- `AGENT_ORCHESTRATOR_RAG_RETRIEVAL_MODE=hybrid` (default behavior)
- set `AGENT_ORCHESTRATOR_RAG_RETRIEVAL_MODE=lexical` to force FTS-only

Chroma settings:
- `AGENT_ORCHESTRATOR_CHROMA_PERSIST_PATH` (default `data/rag_chroma`)
- `AGENT_ORCHESTRATOR_CHROMA_COLLECTION` (default `rag_chunks_v1`)
- `AGENT_ORCHESTRATOR_EMBEDDING_MODEL` (default `text-embedding-3-small`)
- `AGENT_ORCHESTRATOR_EMBEDDING_BASE_URL` (default OpenAI base URL)

Build Chroma vectors from existing SQLite chunks:
```bash
cd agent-orchestrator
make build-chroma-index
```

The builder script is:
- `agent-orchestrator/scripts/build_chroma_index.py`

Runtime notes:
- If Chroma is unavailable/missing, retrieval automatically falls back to lexical hits.
- If embeddings are unavailable, hybrid gracefully degrades instead of failing the task run.

## How to confirm response source (LLM vs deterministic)
After `POST /tasks/{id}/run`, inspect:
- `verification.runtime.planner.effective_mode`
- `verification.runtime.executor.effective_mode`

If fallback happened, `verification.runtime.*.fallback_used` is `true` and
`verification.runtime.*.fallback_reason` explains why.

## Expected evolution
- Short term: reach functional parity on core flows with stronger observability.
- Mid term: add production-grade reliability hardening and richer tooling.
- Long term: evaluate selective backporting of proven agentic components into the main orchestrator.
