import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# Config parameters for GitHub Contributor Onboarding Agent
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5433/taskchain")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
CHROMA_PATH = os.getenv("CHROMA_PATH", str(DATA_DIR / "chroma_db"))
SQLITE_PATH = os.getenv("SQLITE_PATH", str(DATA_DIR / "fts.db"))
INGESTION_REFRESH_DAYS = int(os.getenv("INGESTION_REFRESH_DAYS", "7"))

# Embedding model config
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
EMBEDDING_DIM = 4096   # Qwen3-8B is 4096-dimensional
EMBEDDING_BASE_URL = os.getenv("NEBIUS_EMBEDDING_BASE_URL", "https://api.tokenfactory.uk-south1.nebius.com/v1/")
EMBEDDING_API_KEY = os.getenv("NEBIUS_EMBEDDING_API_KEY", os.getenv("NEBIUS_API_KEY"))

# LLM config
LLM_MODEL = os.getenv("LLM_MODEL", "PrimeIntellect/INTELLECT-3")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY")

# Retrieval settings
SEMANTIC_TOP_K = 5
KEYWORD_TOP_K = 5
FINAL_TOP_K = 5

# Local Git Clone and Sandbox configuration
REPOS_CLONE_DIR = DATA_DIR / "repos"
DOCKER_SANDBOX_IMAGE = os.getenv("DOCKER_SANDBOX_IMAGE", "python:3.11-slim")
