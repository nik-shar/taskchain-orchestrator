# RAG Pipeline Tutorial (Beginner-Friendly)

This guide shows how to run a complete local RAG pipeline on:
- `data/rag_corpus_subset_v1.jsonl` (your combined Jira + incident corpus)

You already completed extraction, so this tutorial starts from that point.

## 1. What You Are Building

RAG has 3 practical stages:

1. **Indexing**
   - Convert raw documents into searchable chunks.
   - Store them in an index (here: SQLite + FTS).
2. **Retrieval**
   - For a user question, fetch the most relevant chunks.
3. **Generation**
   - Produce an answer grounded in retrieved chunks, with citations.

In this repo, those are implemented with:
- `scripts/build_rag_index.py` (indexing)
- `scripts/query_rag.py` (retrieval inspection)
- `scripts/rag_answer.py` (answer generation with deterministic fallback or optional LLM)

## 2. Files and Roles

- Input corpus:
  - `data/rag_corpus_subset_v1.jsonl`
- Built index:
  - `data/rag_index.sqlite`
- Core retrieval library:
  - `src/orchestrator_api/app/rag_sqlite.py`

## 3. Step-by-Step Setup

## Step 1: Activate environment

```bash
source venv/bin/activate
```

## Step 2: Build the RAG index

```bash
python scripts/build_rag_index.py \
  --corpus data/rag_corpus_subset_v1.jsonl \
  --index data/rag_index.sqlite \
  --chunk-chars 900 \
  --overlap-chars 120
```

What this does:
- Reads each JSONL document.
- Chunks long text.
- Stores chunk text + metadata in SQLite.
- Creates an FTS table for fast retrieval.

Expected output:
- document count
- chunk count
- source counts

## Step 3: Run a retrieval-only query

```bash
python scripts/query_rag.py \
  --index data/rag_index.sqlite \
  --query "login failure root cause and repeated bug reports" \
  --top-k 8
```

This prints:
- grounded summary from hits
- hit metadata
- snippets

## Step 4: Use metadata filters (important in practice)

### Jira-only example

```bash
python scripts/query_rag.py \
  --index data/rag_index.sqlite \
  --query "username changes are not applied correctly" \
  --source jira \
  --issue-type Bug \
  --project WLC \
  --top-k 10
```

### Incident-only example

```bash
python scripts/query_rag.py \
  --index data/rag_index.sqlite \
  --query "high priority incidents in category 56" \
  --source incident_event_log \
  --priority "2 - High" \
  --top-k 10
```

Why filters matter:
- They reduce noisy cross-source matches.
- They improve precision and make outputs more explainable.

## Step 5: Generate an answer from retrieved evidence

### Deterministic answer mode (no API key required)

```bash
python scripts/rag_answer.py \
  --index data/rag_index.sqlite \
  --query "What are common causes and handling patterns for repeated username-related bugs?" \
  --top-k 8 \
  --source jira
```

If no LLM is configured, this returns deterministic grounded bullets with citations.

### Optional LLM grounded mode

If `OPENAI_API_KEY` and related LLM settings are configured in your shell, the same command uses LLM synthesis over retrieved evidence and prints:
- answer
- key points
- citations

## 4. How To Ask Meaningful Questions

Good RAG questions are:
- specific
- scoped by source/time/priority when possible
- evidence-seeking, not open-ended speculation

Examples:
- "Find similar closed incidents with priority 2 - High and summarize repeated categories."
- "For WLC Jira bugs, what recurring summary patterns indicate duplicate defects?"
- "Show incidents and Jira bugs that might map to user profile display failures."

Avoid:
- "Tell me everything about the dataset."
- "Predict future outages from this alone."

## 5. Practical Quality Loop

Use this loop:

1. Query with filters.
2. Inspect top hits manually.
3. Adjust query terms and filters.
4. Re-run.
5. Save known-good query templates for repeated tasks.

If quality is weak:
- Increase `top-k` from 8 to 15.
- Narrow source (`jira` vs `incident_event_log`).
- Add project / issue type / priority filters.
- Rebuild with different chunk size (example below).

```bash
python scripts/build_rag_index.py \
  --corpus data/rag_corpus_subset_v1.jsonl \
  --index data/rag_index.sqlite \
  --chunk-chars 700 \
  --overlap-chars 100
```

## 6. Troubleshooting

## "No evidence retrieved"
- Query may be too narrow.
- Remove one or two filters.
- Use terms that appear in summaries/descriptions.

## Too many irrelevant results
- Add `--source`.
- Add `--issue-type`, `--project`, or `--priority`.
- Lower `top-k`.

## Output seems repetitive
- This is common with duplicate Jira issues.
- Add stronger filters or dedupe/merge step before indexing.

## 7. Suggested Next Improvements

1. Add a reranker over top retrieval hits.
2. Add query expansion rules for synonyms (bug/error/failure/outage).
3. Add lightweight evaluation set (20-30 QA pairs with expected citations).
4. Add API endpoint so your app can call this RAG index directly.
