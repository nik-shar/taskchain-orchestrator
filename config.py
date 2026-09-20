import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# Primary store for the RAG index and application metadata.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DATA_DIR / 'rag_index.sqlite'}",
)

# API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Optional retrieval tuning
ENABLE_RERANKER = os.getenv("ENABLE_RERANKER", "True").lower() in ("true", "1", "yes")
SEMANTIC_TOP_K = int(os.getenv("SEMANTIC_TOP_K", "5"))
KEYWORD_TOP_K = int(os.getenv("KEYWORD_TOP_K", "5"))
FINAL_TOP_K = int(os.getenv("FINAL_TOP_K", "5"))

# Models
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# LLM provider configuration.
# TaskChain targets any OpenAI-compatible endpoint: select a preset with
# LLM_PROVIDER, or point straight at a custom endpoint with LLM_BASE_URL /
# LLM_MODEL. Explicit overrides always win over the preset's values.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or None
LLM_MODEL = os.getenv("LLM_MODEL") or None
FALLBACK_LLM_MODEL = "gpt-4o-mini"

# Preset endpoints/models per provider. `api_key` is only used when a provider
# needs a placeholder (Ollama ignores it, but the OpenAI SDK requires a value).
LLM_PROVIDER_PRESETS: dict[str, dict[str, str | None]] = {
    "openai": {"base_url": None, "model": "gpt-4o-mini", "api_key": None},
    "nebius": {
        "base_url": "https://api.tokenfactory.nebius.com/v1/",
        "model": "PrimeIntellect/INTELLECT-3",
        "api_key": None,
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": None,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1",
        "api_key": "ollama",
    },
}

# Three-tier context strategy budgets
# Tier 1: docs injected directly into the prompt
DOCS_CONTEXT_CHARS = int(os.getenv("DOCS_CONTEXT_CHARS", "12000"))
# Tier 2: code read via tools (bounded, read-only)
MAX_SELECTED_FILES = int(os.getenv("MAX_SELECTED_FILES", "5"))
CODE_FILE_MAX_CHARS = int(os.getenv("CODE_FILE_MAX_CHARS", "8000"))
CODE_CONTEXT_CHARS = int(os.getenv("CODE_CONTEXT_CHARS", "30000"))

# Docs ingestion limits
DOC_FILE_MAX_CHARS = int(os.getenv("DOC_FILE_MAX_CHARS", "20000"))
MAX_DOCS_STORED = int(os.getenv("MAX_DOCS_STORED", "50"))

# Source-file search index limits (SQLite FTS5 `files_fts`)
CODE_INDEX_FILE_MAX_CHARS = int(os.getenv("CODE_INDEX_FILE_MAX_CHARS", "20000"))
MAX_INDEXED_FILES = int(os.getenv("MAX_INDEXED_FILES", "2000"))

# Ingestion cache TTL in days
INGESTION_REFRESH_DAYS = int(os.getenv("INGESTION_REFRESH_DAYS", "7"))

# Sandboxed execution. Agent-authored commands (test runners, linters) must never
# execute on the host, so they run in a throwaway container with no network, a
# non-root user, resource caps and a wall-clock timeout.
DOCKER_SANDBOX_IMAGE = os.getenv("DOCKER_SANDBOX_IMAGE", "python:3.11-slim")
SANDBOX_TIMEOUT_S = int(os.getenv("SANDBOX_TIMEOUT_S", "300"))
SANDBOX_MEMORY = os.getenv("SANDBOX_MEMORY", "1g")
SANDBOX_CPUS = os.getenv("SANDBOX_CPUS", "2")
SANDBOX_PIDS_LIMIT = int(os.getenv("SANDBOX_PIDS_LIMIT", "256"))
# Run as the invoking host user so files written into the mounted worktree keep sane
# ownership, while still avoiding container root.
SANDBOX_USER = os.getenv("SANDBOX_USER") or (
    f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "65534:65534"
)
# Dependency installation needs network; test execution should not. Build a per-repo
# image with `build_repo_image()` rather than enabling this for the test run.
SANDBOX_ALLOW_NETWORK = os.getenv("SANDBOX_ALLOW_NETWORK", "False").lower() in (
    "true",
    "1",
    "yes",
)
# Fail closed by default: refusing to run is better than running untrusted commands
# on the host. This escape hatch exists for local development only.
SANDBOX_ALLOW_HOST_FALLBACK = os.getenv("SANDBOX_ALLOW_HOST_FALLBACK", "False").lower() in (
    "true",
    "1",
    "yes",
)
# Explicit test/lint command for the verifier. When unset, detect_test_command()
# infers one from the repo's manifests.
SANDBOX_TEST_COMMAND = os.getenv("SANDBOX_TEST_COMMAND", "").strip() or None
# Where patch edits are applied, per run. Kept separate from the read-only workspace
# so the "the LLM never writes to the workspace" invariant still holds.
WORKTREES_DIR = DATA_DIR / "worktrees"
