"""Provider-agnostic LLM access for every agent.

Agents never construct a client directly; they go through `build_llm_client`, so
switching providers is a configuration change rather than a code change. Any
OpenAI-compatible endpoint works: select an `LLM_PROVIDER` preset (openai,
nebius, deepseek, ollama) or override `LLM_BASE_URL` / `LLM_MODEL` directly.
"""
