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
│   ├── sqlite_indexer.py    # Indexes source code and markdown docs
│   └── github_indexer.py    # Indexes issues and PR metadata/discussion (NEW)
├── github/
│   └── pr_client.py         # Opens/updates pull requests via GitHub API (NEW)
├── ui/
│   ├── index.html           # Dashboard: Q&A, issue submission, live pipeline logs
│   └── styles.css
├── data/                    # Local storage for cloned repos and SQLite DB
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
- An OpenAI API key
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

Create a `.env` file in the project root:

```
OPENAI_API_KEY=sk-your_openai_api_key_here
GITHUB_TOKEN=ghp-your_github_token_here
DATABASE_URL=sqlite:///data/rag_index.sqlite
ENABLE_RERANKER=True
```

### Running

```bash
python -m uvicorn api.server:app --reload
```

Open `http://localhost:8000` to use the dashboard.

### Testing

```bash
PYTHONPATH=. venv/bin/pytest -v
```

---

## 🗺️ Roadmap

Stretch goals beyond v1 — not required for launch, useful for later iterations:

- Auto-generated documentation / README for arbitrary repos
- Missing-test generation for uncovered functions
- Issue triage: rank open issues by how tractable they look for the agent
- PR review assistant: review a human-authored PR against repo conventions
- Multi-provider LLM support (not just OpenAI)

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome — check the issues page.

## 📝 License

MIT License.
