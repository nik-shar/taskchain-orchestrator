# TaskChain — Autonomous Repository Agent

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![LLM-OpenAI-green.svg)](https://openai.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**TaskChain** is an autonomous developer agent that understands a GitHub repository end-to-end — its code, issues, and pull requests — and can answer questions about it, fix issues, and refine its own patches based on feedback.

Paste a public repo. Ask it anything. Point it at an issue and let it ship a fix.

---

## 🎯 Core Use Cases

These are the features that define v1 — everything else is a stretch goal (see [Roadmap](#-roadmap)).

### 1. Repo-Aware Q&A
Ask natural-language questions about the codebase, its issues, or its pull requests:
- *"What does this repo do?"*
- *"Where is authentication handled?"*
- *"What's issue #42 about, and has anyone attempted a fix?"*
- *"Summarize the changes in PR #17."*

Powered by the RAG index — read-only, fast, works on any repo with zero setup. This is the first thing a user should be able to try.

### 2. Issue → Pull Request
Paste an issue link (or describe a bug/feature in plain English). The **Planner → Executor → Verifier** pipeline:
1. Plans a fix using indexed repo context
2. Applies the code changes
3. Verifies the patch against the issue **and runs the repo's actual test suite / linter** — not just an LLM's opinion of its own work
4. Opens a real GitHub pull request with the fix and a summary of what changed

### 3. Conversational Patch Refinement
After a patch is generated, the user can steer it without starting over:
- *"Don't touch the config file, only the handler."*
- *"Also cover the case where the input is empty."*

The agent re-runs Executor → Verifier against the feedback instead of regenerating from scratch. This demonstrates agent steerability, not just one-shot generation.

### 4. Plain-English Result Summaries
Every run ends with a human-readable summary — files changed, tests passed/failed, what was fixed — so results are legible to someone who doesn't want to read a raw diff.

---

## 🧱 What This Version Removes

Earlier iterations of this repo explored a sandboxed manual coding environment (in-browser editor + arbitrary code execution). This has been **fully removed** from scope:
- Out of scope for the problem this project demonstrates (agent orchestration, not IDE infrastructure)
- Introduces security/cost exposure (arbitrary code execution from public users) disproportionate to the value it adds
- All related code, dependencies, and UI elements should be deleted, not just hidden

If sandboxed execution is ever revisited, it should be scoped as its own project.

---

## 🧠 System Architecture

```
graph TD
    User([User]) -->|1. Ask question / submit issue| Router{Query type}

    Router -->|Q&A| RAG[(RAG Index<br>code + issues + PRs)]
    RAG -->|Answer| User

    Router -->|Fix request| Planner[Planner Agent]
    Planner -->|Query context| RAG
    Planner -->|Execution plan| Executor[Executor Agent]
    Executor -->|Reads/writes code| Repo[(Local Git Clone)]
    Executor -->|Diff| Verifier[Verifier Agent]
    Verifier -->|Runs tests/lint| Repo
    Verifier -->|Fails: feedback| Executor
    Verifier -->|Passes| PR[Opens GitHub PR]
    PR --> User

    User -->|Refinement feedback| Executor
```

---

## 📂 Project Structure

```
├── agent/
│   ├── planner.py           # Issue/feature analysis and plan generation
│   ├── executor.py          # Applies code edits, incorporates refinement feedback
│   └── verifier.py          # Runs tests/lint + reviews diff against requirements
├── api/
│   └── server.py            # FastAPI application and endpoints
├── ingestion/
│   ├── github_indexer.py    # Fetches metadata, issues and PRs from the GitHub API
│   ├── sqlite_indexer.py    # SQLite FTS5 index + safe query builder for issues/PRs
│   ├── code_indexer.py      # SQLite FTS5 index of repository source files
│   ├── docs_collector.py    # Doc collection + budgeted prompt injection
│   └── workspace.py         # Downloads the repo snapshot for read-only code access
├── llm/
│   └── client.py            # Provider-agnostic LLM client factory
├── github/
│   └── pr_client.py         # Opens/updates pull requests via GitHub API
├── scripts/
│   └── benchmark_retrieval.py  # Index stats, search latency, hit-rate
├── ui/
│   ├── index.html           # Dashboard: Q&A, issue submission, live pipeline logs
│   └── styles.css
├── data/                    # Local storage for repo snapshots and SQLite DB
├── tests/
├── config.py
├── requirements.txt
└── README.md
```

---

## 🛠️ Essential Features To Build

Tracking what's already built vs. what's needed to reach the v1 scope above.

| Feature | Status |
|---|---|
| Planner → Executor → Verifier pipeline | ✅ Built |
| SQLite RAG indexing of source code + docs | ✅ Built |
| Minimal web dashboard | ✅ Built |
| GitHub Issues/PRs ingestion into RAG index | ⬜ To build |
| Repo-aware Q&A endpoint (chat interface, no Executor) | ⬜ To build |
| Verifier runs actual test suite / linter (not just LLM judgment) | ⬜ To build |
| Opens real GitHub PRs via API (not just local diff) | ⬜ To build |
| Conversational patch refinement loop | ⬜ To build |
| Plain-English run summaries | ⬜ To build |
| Free-form feature request input (no issue link required) | ⬜ To build |
| Repo size limits / per-run timeout & cost caps | ⬜ To build |
| Hosted deployment (GCP) | ⬜ To build |
| Removal of all sandbox-environment code/UI/deps | ⬜ To build |

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10 or higher
- An API key for any OpenAI-compatible LLM provider (OpenAI, Nebius, DeepSeek, or a local Ollama instance)
- A GitHub personal access token (for issue/PR ingestion and opening PRs)

### Installation

```bash
git clone https://github.com/nik-shar/taskchain-orchestrator.git
cd taskchain-orchestrator
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

TaskChain is **provider-agnostic**: it talks to any OpenAI-compatible endpoint. Create
a `.env` file in the project root and pick a provider preset, or point straight at a
custom endpoint:

```
# Preset: openai | nebius | deepseek | ollama
LLM_PROVIDER=openai
LLM_API_KEY=sk-your_api_key_here

# Optional overrides (these win over the preset)
# LLM_MODEL=gpt-4o-mini
# LLM_BASE_URL=https://api.openai.com/v1

GITHUB_TOKEN=ghp-your_github_token_here
DATABASE_URL=sqlite:///data/rag_index.sqlite
ENABLE_RERANKER=True
```

Examples for other providers:

| Provider | Configuration |
|---|---|
| OpenAI | `LLM_PROVIDER=openai` + `LLM_API_KEY=sk-...` |
| Nebius | `LLM_PROVIDER=nebius` + `LLM_API_KEY=<nebius key>` |
| DeepSeek | `LLM_PROVIDER=deepseek` + `LLM_API_KEY=<deepseek key>` |
| Ollama (local) | `LLM_PROVIDER=ollama` (no key required) |
| Anything else | `LLM_BASE_URL=<endpoint>` + `LLM_MODEL=<model>` + `LLM_API_KEY=<key>` |

`OPENAI_API_KEY` is still accepted as an alias for `LLM_API_KEY`.

### Running

```bash
python -m uvicorn api.server:app --reload
```

Open `http://localhost:8000` to use the dashboard.

### Testing

```bash
PYTHONPATH=. venv/bin/pytest -v
```

### Retrieval benchmark

`make bench` reports what is actually in the index plus how fast search returns:

```bash
# Ingest a repo, then measure
make bench ARGS="--repo-url https://github.com/tiangolo/fastapi"

# Or reuse an existing index
make bench ARGS="--repo-id tiangolo/fastapi --skip-ingest"

# Add labelled HitRate@k / MRR@k from a JSONL of {"query", "expected_path"}
make bench ARGS="--repo-id tiangolo/fastapi --skip-ingest --eval-file data/retrieval_eval.jsonl --out docs/retrieval_report.md"
```

Measured on this repository (`nik-shar/taskchain-orchestrator`, 37 indexed files, 5 queries):

| Source | Count |
| --- | ---: |
| Repository files indexed (FTS5 `files_fts`) | 37 |
| Files in read-only workspace | 37 |
| Documentation files injected | 2 |
| Issues / PRs indexed | 0 (ingestion requires `GITHUB_TOKEN`) |

| Retriever | P50 (ms) | P95 (ms) | Hits |
| --- | ---: | ---: | ---: |
| Code (FTS5 `files_fts`) | 0.72 | 1.04 | 16 |
| History (FTS5 `issues_fts`) | 0.17 | 0.21 | 0 |

> Ingesting a repository requires `GITHUB_TOKEN`. Without it the unauthenticated
> hourly quota (60 requests) trips `check_rate_limit`, which fails fast rather than
> stalling the pipeline for an hour.

---

## 🗺️ Roadmap

Stretch goals beyond v1 — not required for launch, useful for later iterations:

- Auto-generated documentation / README for arbitrary repos
- Missing-test generation for uncovered functions
- Issue triage: rank open issues by how tractable they look for the agent
- PR review assistant: review a human-authored PR against repo conventions

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome — check the issues page.

## 📝 License

MIT License.
