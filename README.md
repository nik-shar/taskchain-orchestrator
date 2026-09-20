# TaskChain — Repository Intelligence & Sandboxed Execution

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/interface-MCP-blueviolet.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**TaskChain** understands a GitHub repository end-to-end — its code, docs, issues and pull
requests — and gives an *external* agent the two things it needs to work on that repository:
**grounded context** and a **safe place to run things**.

It deliberately does **not** generate or apply code edits. Deciding what to change belongs
to your agent; TaskChain owns retrieval and isolation.

Paste a public repo. Ask it anything. Then point your own MCP-capable agent at it.

---

## 🎯 Core Use Cases

### 1. Repo-Aware Q&A
Ask natural-language questions about the codebase, its issues, or its pull requests:
- *"What does this repo do?"*
- *"Where is authentication handled?"*
- *"What's issue #42 about, and has anyone attempted a fix?"*

Answers are streamed over SSE with live pipeline stages, grounded in a four-tier context:
repository summary, budgeted documentation, indexed source files, and indexed issue/PR text.
Ingestion is a background step and requires a `GITHUB_TOKEN`.

### 2. Grounded Context for Any Agent (MCP)
TaskChain runs as an **MCP server**, so any MCP-capable agent can call it for:
- `search_code` / `search_issues` / `repository_docs` / `repo_summary` — retrieval
- `list_files` / `read_file` — bounded, path-checked reads
- `suggest_plan` — an advisory approach for an issue (a plan, never an edit)

### 3. A Safe Place to Work (MCP)
The same server exposes an execution substrate the agent can work in:
- `create_worktree` — an isolated, git-initialised copy of the repository
- `write_file` / `delete_file` / `apply_patch` — raw primitives, path-checked
- `sandbox_run` — hardened Docker execution: **no network**, non-root, memory/CPU/PID caps
  and a wall-clock timeout, **failing closed** when Docker is unavailable
- `diff` — a real unified diff of what the agent changed
- `discard_worktree` — throw it all away

The indexed workspace is never written to. Per-run worktrees live under `data/worktrees/`.

### 4. Open a Pull Request
Once the agent is happy with its diff, `open_pull_request` creates the PR through the
GitHub API — so the agent does not need its own GitHub write path.

---

## 🧱 What This Project Deliberately Excludes

**Code editing.** TaskChain does not plan-and-apply patches. An earlier iteration of this
repo implemented a full **Planner → Executor → Verifier** agent that generated patches,
gated them on the repository's test suite, and refined them from feedback. It was removed on
purpose: it made this another coding agent rather than the context-and-execution layer it is
meant to be. That implementation is preserved at the git tag `archive/editing-agent`.

Also removed in earlier iterations: the in-browser coding workspace with an editor and
arbitrary public code execution — out of scope, and disproportionate security/cost exposure.

---

## 🧠 System Architecture

```
graph TD
    Agent([Your MCP agent]) -->|1. context queries| MCP[MCP Server]
    User([User]) -->|ask| API[FastAPI<br>Q&A + SSE]

    MCP --> Search[(SQLite FTS5 index<br>source files + issues + PRs)]
    API --> Search
    Search --> MCP
    Search --> API

    MCP -->|2. create_worktree| WT[(Isolated worktree<br>data/worktrees/)]
    MCP -->|3. write_file / apply_patch| WT
    MCP -->|4. sandbox_run| Sandbox[Docker sandbox<br>no network · caps · timeout]
    Sandbox --> WT
    MCP -->|5. diff| Agent
    MCP -->|6. open_pull_request| GH[GitHub API]
```

The division of responsibility is the point: TaskChain answers *"what is in this repository
and how do I run it safely?"*, and the agent answers *"what should change?"*.

---

## 📂 Project Structure

├── mcp_server/
│   └── server.py            # MCP integration surface: context tools + execution substrate
├── agent/
│   ├── planner.py           # Advisory plan for an issue (exposed as suggest_plan)
│   ├── worktree.py          # Isolated per-run git worktree + raw patch primitives
│   └── code_tools.py        # Read-only list/read over the workspace
├── api/
│   └── server.py            # FastAPI endpoints (ingest/status/ask/ask-stream)
├── utils/
│   ├── sandbox.py           # Hardened Docker execution for agent-authored commands
│   ├── db.py                # SQLAlchemy models and session factory
│   └── logging_config.py    # JSON structured logging
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
│   ├── index.html           # Dashboard: ingestion + live Q&A pipeline
│   └── styles.css
├── data/                    # Local storage: snapshots, worktrees, SQLite DB
├── tests/
├── config.py
├── requirements.txt
└── README.md
```

---

## 🛠️ Project Status

| Capability | Status |
|---|---|
| MCP server exposing context + execution tools | ✅ Built |
| Isolated per-run git worktrees (workspace never written to) | ✅ Built |
| Hardened Docker sandbox (`--network none`, caps, timeout, fail-closed) | ✅ Built |
| SQLite FTS5 indexing of source files + issues/PRs | ✅ Built |
| GitHub ingestion: metadata, docs, file tree, issues, PRs | ✅ Built (needs `GITHUB_TOKEN`) |
| Repo-aware Q&A with streamed pipeline stages | ✅ Built |
| Provider-agnostic LLM configuration | ✅ Built |
| Retrieval benchmark (index size, P50/P95, HitRate@k) | ✅ Built |
| Minimal web dashboard | ✅ Built |
| Semantic (vector) retrieval alongside keyword search | ⬜ Not built — see [Roadmap](#roadmap) |
| Per-run cost caps | ⬜ Partial — time/resource caps only |
| Hosted deployment | ⬜ Out of scope for this repo |

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11 or higher** (`datetime.UTC` and the `X | None` syntax are required)
- An API key for an OpenAI-compatible LLM provider — OpenAI, Nebius, DeepSeek, or a local
  Ollama instance
- A GitHub personal access token — required for ingestion and for `open_pull_request`
- **Docker** — required by `sandbox_run`; the sandbox fails closed without a daemon

### Installation

```bash
git clone https://github.com/nik-shar/taskchain-orchestrator.git
cd taskchain-orchestrator
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

TaskChain is **provider-agnostic**: it talks to any OpenAI-compatible endpoint. Create a
`.env` file in the project root (see `.env.example`) and pick a preset, or point straight at
a custom endpoint:

```dotenv
# Preset: openai | nebius | deepseek | ollama
LLM_PROVIDER=openai
LLM_API_KEY=sk-your_api_key_here

# Optional overrides — these win over the preset
# LLM_MODEL=gpt-4o-mini
# LLM_BASE_URL=https://api.openai.com/v1

GITHUB_TOKEN=ghp-your_github_token_here
DATABASE_URL=sqlite:///data/rag_index.sqlite
```

| Provider | Configuration |
|---|---|
| OpenAI | `LLM_PROVIDER=openai` + `LLM_API_KEY=sk-...` |
| Nebius | `LLM_PROVIDER=nebius` + `LLM_API_KEY=<nebius key>` |
| DeepSeek | `LLM_PROVIDER=deepseek` + `LLM_API_KEY=<deepseek key>` |
| Ollama (local) | `LLM_PROVIDER=ollama` — no key required |
| Anything else | `LLM_BASE_URL=<endpoint>` + `LLM_MODEL=<model>` + `LLM_API_KEY=<key>` |

`OPENAI_API_KEY` is accepted as an alias for `LLM_API_KEY`.

`DATABASE_URL` must stay SQLite: the keyword index uses FTS5, which Postgres does not
provide. See [docs/decisions.md](docs/decisions.md#7-fts5-requires-sqlite-which-constrains-deployment).

### Running the Q&A dashboard

```bash
make api          # uvicorn api.server:app
```

Open `http://localhost:8000` to ingest a repository and ask questions.

### Running the MCP server

```bash
make mcp                       # stdio, for desktop/CLI agents
make mcp ARGS="--http"         # streamable HTTP on 127.0.0.1:8080
```

Point an MCP client at it. For example, a Claude Desktop / Cline-style config:

```json
{
  "mcpServers": {
    "taskchain": {
      "command": "/absolute/path/to/taskchain-orchestrator/venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/taskchain-orchestrator",
        "DATABASE_URL": "sqlite:///data/rag_index.sqlite",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```

A typical agent session:

```
index_repository   { repo_url: "https://github.com/owner/repo" }
search_code        { repo_id: "owner/repo", query: "where is auth handled?" }
read_file          { repo_id: "owner/repo", path: "src/auth.py" }
create_worktree    { repo_id: "owner/repo" }              -> worktree_id
write_file         { worktree_id, path: "src/auth.py", content: "..." }
sandbox_run        { worktree_id, command: "python -m pytest -q" }
diff               { worktree_id }                        -> unified diff
open_pull_request  { owner, repo, title, body, head_branch }
discard_worktree   { worktree_id }
```

**Security model.** Tools never accept a host filesystem path — they accept the
`worktree_id` returned by `create_worktree`, which is validated to live under
`config.WORKTREES_DIR`. `sandbox_run` executes with `--network none`, a non-root user,
memory/CPU/PID caps and a timeout, and refuses to run at all when Docker is unavailable
(`SANDBOX_ALLOW_HOST_FALLBACK=1` opts into host execution for local development only).

### Testing

```bash
make check                                  # compile everything + run the suite
PYTHONPATH=. venv/bin/pytest -q tests       # tests only
PYTHONPATH=. venv/bin/pytest -q -m docker   # only the tests needing a Docker daemon
```

The suite is hermetic by default: no network calls, a temporary SQLite database, and a
stubbed LLM. Tests marked `docker` exercise the real sandbox and are skipped automatically
when no daemon is available.

### Retrieval benchmark

`make bench` reports what is actually in the index plus how fast retrieval returns, so
performance claims can be reproduced rather than taken on trust:

```bash
# Ingest a repository first, then measure
make bench ARGS="--repo-url https://github.com/tiangolo/fastapi"

# Or reuse an existing index
make bench ARGS="--repo-id tiangolo/fastapi --skip-ingest"

# Add labelled HitRate@k / MRR@k from a JSONL of {"query", "expected_path"}
make bench ARGS="--repo-id tiangolo/fastapi --skip-ingest \
  --eval-file data/retrieval_eval.jsonl --out docs/retrieval_report.md"
```

**Reference run.** Measured on this repository at commit `de9894d`
(`nik-shar/taskchain-orchestrator`, 37 indexed files, 5 queries, local SQLite):

| Source | Count |
| --- | ---: |
| Repository files indexed (FTS5 `files_fts`) | 37 |
| Files in the read-only workspace | 37 |
| Documentation files injected | 2 |
| Issues / PRs indexed | 0 — ingestion needed a `GITHUB_TOKEN` |

| Retriever | P50 (ms) | P95 (ms) | Hits |
| --- | ---: | ---: | ---: |
| Code (FTS5 `files_fts`) | 0.72 | 1.04 | 16 |
| History (FTS5 `issues_fts`) | 0.17 | 0.21 | 0 |

These numbers are a sample, not a benchmark suite: they come from a single small
repository and 5 queries. The point is that `make bench` regenerates them on demand.

> **Ingestion needs `GITHUB_TOKEN`.** Without it the unauthenticated hourly quota
> (60 requests) trips `check_rate_limit`, which fails fast with an actionable error
> instead of stalling the pipeline for an hour.

---

## ⚠️ Limitations

Stated plainly, because they shape how the project should be used:

- **Keyword retrieval only.** FTS5 matches tokens, so a question phrased with different
  vocabulary than the code will miss. Semantic retrieval is the first roadmap item.
- **Ingestion is synchronous and in-process.** A large repository blocks the worker
  running it; there is no queue, retry, or resumable ingestion.
- **The sandbox cannot install dependencies.** `run_sandbox_command` executes with
  `--network none`, so a repository whose dependencies are not in the image cannot run its
  own tests. `utils/sandbox.build_repo_image()` is the intended workaround: bake a
  per-repository image at build time, where network is available.
- **Index size is capped** at 500 listed files, 2,000 indexed files, 100 KB per file and
  20,000 characters per indexed file. Very large repositories are partially covered.
- **State is local and single-instance.** The SQLite index and `data/worktrees/` live on
  one filesystem; nothing is shared between processes.
- **GitHub only.** Ingestion is written against the GitHub REST API.

---

## 📚 Documentation

| Document | Contents |
|---|---|
| [README](README.md) | Overview, quickstart, configuration, benchmark, limitations |
| [docs/mcp-tools.md](docs/mcp-tools.md) | Reference for all 18 MCP tools |
| [docs/decisions.md](docs/decisions.md) | Why the project is shaped this way, including the decision to exclude code editing |

---

<a id="roadmap"></a>

## 🗺️ Roadmap

Stretch goals — not required, useful later:

- Semantic (vector) retrieval fused with keyword search via RRF, restoring a ChromaDB
  collection alongside the FTS5 index (the config knobs `SEMANTIC_TOP_K` and `FINAL_TOP_K`
  are still present, and `scripts/benchmark_retrieval.py` already measures hit-rate)
- Persistent worktree sessions so an MCP client can resume across server restarts
- Streamable-HTTP MCP transport on Cloud Run (verified locally; deployment is next)
- Issue triage: rank open issues by how tractable they look
- Per-run cost caps in addition to the sandbox's time and resource caps

---

## 🤝 Contributing

Contributions, issues and feature requests are welcome — please open an issue first for
anything larger than a bug fix.

```bash
make install     # dependencies into ./venv
make check       # compile + lint + test
make test        # tests only
```

The test suite is hermetic: no network calls, a temporary SQLite database, and a stubbed
LLM. Keep it that way — `tests/conftest.py` forces a dummy `OPENAI_API_KEY` for exactly
that reason. Tests that need a real Docker daemon are marked `docker` and deselected in CI.

## 📝 License

MIT — see [LICENSE](LICENSE).
