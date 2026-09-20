"""Tests for the provider-agnostic LLM client factory."""
import config
from llm.client import build_llm_client, resolve_llm_settings

PROVIDERS = ("openai", "nebius", "deepseek", "ollama")


def _configure(monkeypatch, provider, model=None, base_url=None, api_key=None):
    monkeypatch.setattr(config, "LLM_PROVIDER", provider)
    monkeypatch.setattr(config, "LLM_MODEL", model)
    monkeypatch.setattr(config, "LLM_BASE_URL", base_url)
    monkeypatch.setattr(config, "LLM_API_KEY", api_key)


def test_openai_uses_sdk_default_endpoint(monkeypatch):
    _configure(monkeypatch, "openai", api_key="sk-test")
    settings = resolve_llm_settings()
    assert settings.provider == "openai"
    assert settings.model == "gpt-4o-mini"
    # No base_url means "let the SDK pick api.openai.com".
    assert settings.base_url is None
    assert settings.api_key == "sk-test"


def test_preset_supplies_endpoint_model_and_key(monkeypatch):
    _configure(monkeypatch, "ollama")
    settings = resolve_llm_settings()
    assert settings.provider == "ollama"
    assert settings.base_url == "http://localhost:11434/v1"
    assert settings.model == "llama3.1"
    # Ollama ignores the key, but the SDK refuses to build without one.
    assert settings.api_key == "ollama"


def test_explicit_overrides_beat_preset(monkeypatch):
    _configure(
        monkeypatch,
        "deepseek",
        model="my-finetune",
        base_url="https://llm.internal.test/v1",
        api_key="secret",
    )
    settings = resolve_llm_settings()
    assert settings.model == "my-finetune"
    assert settings.base_url == "https://llm.internal.test/v1"
    assert settings.api_key == "secret"


def test_unknown_provider_falls_back_to_openai(monkeypatch):
    _configure(monkeypatch, "definitely-not-a-provider")
    settings = resolve_llm_settings()
    assert settings.provider == "openai"
    assert settings.model == config.FALLBACK_LLM_MODEL
    assert settings.base_url is None


def test_every_documented_provider_resolves(monkeypatch):
    """Backs the 'provider-agnostic' claim: each advertised provider resolves to a
    usable endpoint + model without any code change."""
    assert set(PROVIDERS) <= set(config.LLM_PROVIDER_PRESETS)
    for provider in PROVIDERS:
        _configure(monkeypatch, provider, api_key="key")
        settings = resolve_llm_settings()
        assert settings.provider == provider
        assert settings.model
        assert settings.api_key


def test_build_llm_client_uses_resolved_base_url(monkeypatch):
    _configure(monkeypatch, "ollama")
    client = build_llm_client()
    assert "11434" in str(client.base_url)
    assert client.api_key == "ollama"


def test_build_llm_client_accepts_explicit_settings(monkeypatch):
    _configure(monkeypatch, "openai", api_key="sk-test")
    explicit = resolve_llm_settings()
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    # A caller passing settings must not be re-resolved from config.
    client = build_llm_client(explicit)
    assert "11434" not in str(client.base_url)
