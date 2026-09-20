"""Provider-agnostic LLM client factory."""
import logging
from dataclasses import dataclass

from openai import OpenAI

import config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMSettings:
    """A fully resolved endpoint configuration for one LLM provider."""

    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None


def resolve_llm_settings() -> LLMSettings:
    """Resolve provider, endpoint, key and model from configuration.

    Precedence: explicit ``LLM_BASE_URL`` / ``LLM_MODEL`` / ``LLM_API_KEY`` win,
    and the ``LLM_PROVIDER`` preset fills in whatever is left unset. An unknown
    provider logs a warning and falls back to the OpenAI preset instead of
    failing at request time.
    """
    requested = config.LLM_PROVIDER
    preset = config.LLM_PROVIDER_PRESETS.get(requested)
    provider = requested
    if preset is None:
        logger.warning(
            "Unknown LLM_PROVIDER %r; falling back to the openai preset. Known providers: %s",
            requested,
            ", ".join(sorted(config.LLM_PROVIDER_PRESETS)),
        )
        provider = "openai"
        preset = config.LLM_PROVIDER_PRESETS[provider]

    model = config.LLM_MODEL or preset.get("model") or config.FALLBACK_LLM_MODEL
    base_url = config.LLM_BASE_URL or preset.get("base_url")
    api_key = config.LLM_API_KEY or preset.get("api_key")

    return LLMSettings(provider=provider, model=model, base_url=base_url, api_key=api_key)


def build_llm_client(settings: LLMSettings | None = None) -> OpenAI:
    """Build an OpenAI-compatible client for the resolved provider."""
    resolved = settings or resolve_llm_settings()
    logger.debug(
        "LLM provider=%s model=%s base_url=%s",
        resolved.provider,
        resolved.model,
        resolved.base_url or "(provider default)",
    )
    if resolved.base_url:
        return OpenAI(api_key=resolved.api_key, base_url=resolved.base_url)
    return OpenAI(api_key=resolved.api_key)
