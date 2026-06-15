# TaskChain — GitHub Contributor Onboarding & Autonomous Coding Workspace

TaskChain is a developer agent system designed to automate public GitHub repository onboarding and issue resolution. Instead of just working alongside developers, TaskChain functions as an autonomous **Coding Agent** running within an isolated **Docker Sandbox**, coupled with an interactive **Monaco Editor Browser Workspace** and **Steerable LLM ReAct loop control**.

---

## Key Features

1. **Personalized Contributor Onboarding**
   - Paste any public GitHub repository URL and describe your developer background.
   - Generates a customized Contributor Guide, indexes technical DNA (README, tech stack, rules), and recommends matching open issues.

2. **Orchestrator & Handoff Router**
   - Coordinates conversations and automatically routes handoff requests. 
   - Detects explicit trigger commands (e.g., `/solve #42` or `let's work on issue 7`) to open the sandbox workspace and dispatch the agent.

3. **Steerable ReAct Coding Agent**
   - Powered by an LLM loop equipped with local tools (`list_directory`, `read_file`, `write_file`, `run_tests`).
   - Supports user-specified **Steering Instructions** injected into the system prompt to enforce rules or limit search scope.

4. **Docker Sandbox Execution Engine**
   - Mounts cloned repositories inside isolated container volumes to safely execute compiler, build, and test runner commands (e.g., `pytest`, `npm test`).
   - Gracefully falls back to local subprocess execution with warnings if Docker is offline.

5. **Split-Pane Developer Workspace UI**
   - **Left Pane**: Expandable folder and file tree highlighting files modified by the agent.
   - **Right Pane**: Monaco Code Editor (the exact editor inside VS Code) loaded dynamically via RequireJS, supporting save controls and `Ctrl+S` hotkeys.
   - **Bottom Console**: Dark terminal console streaming LLM thoughts, execution stages, and sandbox test logs in real-time.

---

## System Architecture

```mermaid
graph TD
    User[Developer UI] -->|Connect Repo & Profile| Ingestion[Ingestion Pipeline]
    Ingestion -->|1. Shallow Git Clone| Repo[(Local Repo Clone)]
    Ingestion -->|2. Tech Stack & DNA Summary| Postgres[(PostgreSQL)]
    Ingestion -->|3. Index Issues & docs| Vector[Chroma & SQLite FTS]
    
    User -->|Open Workspace / Solve| Orch[Orchestrator]
    Orch -->|Start Solve Task| Coding[ReAct Coding Agent]
    
    Coding -->|Read/Write Source Code| Repo
    Coding -->|Execute commands & tests| Docker[Docker Sandbox]
    Docker -->|Mounts Workspace| Repo
    
    Repo -->|git diff| User
    User -->|Manual Code Edits| Monaco[Monaco Editor]
    Monaco -->|Persistence API| Repo
```

---

## Project Structure

```
├── agent/
│   ├── onboarding_agent.py   # LLM onboarding guide and chat logic
│   ├── onboarding_workflow.py# LangGraph multi-step ingestion search workflow
│   ├── orchestrator.py        # Intercepts chat triggers and dispatches handoffs
│   └── coding_agent.py        # Steerable LLM ReAct loop solver with sandbox tools
├── api/
│   └── server.py              # FastAPI application, streaming SSE events and file APIs
├── ingestion/
│   ├── github_fetcher.py      # GitHub REST fetcher for files, issues, PRs
│   └── ingestion_pipeline.py  # DNA summarizer, vector database indexing, and local clone
├── ui/
│   ├── index.html             # Split-pane layout, Monaco config, and terminal components
│   ├── app.js                 # Monaco editor loads, tree scanner, console polling, and steer solvers
│   └── styles.css             # Harmonious HSL styling and responsive panels
├── utils/
│   ├── db.py                  # SQLAlchemy models (guides, handoffs, message history)
│   └── sandbox.py             # Docker CLI command execution wrapper and local subprocess fallback
├── tests/
│   ├── test_steerable_agent.py# Tests for steering API, DB logs, and prompt guidelines
│   ├── test_sandbox.py        # Sandbox timeout, mounting, and execution tests
│   └── test_file_apis.py      # File tree traversal guards and content endpoints
├── config.py                  # Global settings, model endpoints, and local clone paths
├── pyproject.toml             # Project dependency settings
├── requirements.txt           # Python library requirements list
└── Makefile                   # Quick-start build commands
```

---

## Getting Started

### Prerequisites
- Python 3.10+
- Docker (for sandbox container tests)
- PostgreSQL database

### 1. Installation
Clone the repository and set up a virtual environment:
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration
Create a `.env` file in the root directory. TaskChain is LLM provider-agnostic and works with any OpenAI-compatible API endpoint (e.g. OpenAI, Nebius, DeepSeek, or local Ollama instances).

Configure the environment variables in your `.env` file:
```env
# General LLM API Key (OpenAI, Nebius, DeepSeek, etc.)
NEBIUS_API_KEY=your_llm_api_key_here

# GitHub Access Token (for downloading repository code and issues)
GITHUB_TOKEN=your_github_personal_access_token_here

# Database URL Connection String
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/taskchain

# Optional Model/URL Overrides (e.g. to use OpenAI directly)
# LLM_BASE_URL=https://api.openai.com/v1/
# LLM_MODEL=gpt-4o
# NEBIUS_EMBEDDING_BASE_URL=https://api.openai.com/v1/
# EMBEDDING_MODEL=text-embedding-3-large
```

### 3. Running the Server
Start the FastAPI development server:
```bash
python -m uvicorn api.server:app --reload
```
Open your browser and navigate to `http://localhost:8000` to interact with TaskChain.

### 4. Running the Tests
To run all unit and integration test suites:
```bash
PYTHONPATH=. venv/bin/pytest -v
```
