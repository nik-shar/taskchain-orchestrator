"""Application settings."""

from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "agent-orchestrator"
    app_env: str = "dev"
    app_debug: bool = False
    planner_mode: str = "deterministic"
    executor_mode: str = "deterministic"
    max_graph_loops: int = 2
    database_url: str = ""
    tool_timeout_s: float = Field(default=2.0, ge=0.01)
    tool_max_retries: int = Field(default=1, ge=0)
    tool_retry_backoff_s: float = Field(default=0.0, ge=0.0)
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_s: float = Field(default=8.0, ge=0.5)
    llm_max_retries: int = Field(default=1, ge=0)
    llm_backoff_s: float = Field(default=0.2, ge=0.0)
    openai_api_key: str = ""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_ORCHESTRATOR_",
        extra="ignore",
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local"),
        env_file_encoding="utf-8",
    )

    def resolved_database_url(self) -> str:
        return self.database_url or os.getenv("ORCHESTRATOR_DATABASE_URL", "")

    def resolved_openai_api_key(self) -> str:
        return self.openai_api_key or os.getenv("OPENAI_API_KEY", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
