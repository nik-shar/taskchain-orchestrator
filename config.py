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
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

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

# Ingestion cache TTL in days
INGESTION_REFRESH_DAYS = int(os.getenv("INGESTION_REFRESH_DAYS", "7"))
