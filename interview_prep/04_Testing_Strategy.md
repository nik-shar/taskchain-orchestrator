# Testing Strategy

tags: #testing #quality

## Test Layers
1. Unit tests for planner/executor/verifier/tool behavior.
2. API tests with in-memory storage double for fast lifecycle checks.
3. Integration tests with real Postgres and uvicorn process.
4. Optional live LLM integration tests (opt-in by env flags).

## Representative Coverage
- Planner behavior and normalization:
  - `tests/test_planner.py`
  - `tests/test_phase2_scaffold.py`
- Executor deterministic tools, metadata, retries/repair:
  - `tests/test_tools.py`
- Verification rules, especially incident evidence:
  - `tests/test_verifier.py`
- API lifecycle and status transitions:
  - `tests/test_tasks.py`
- Postgres wiring and config guards:
  - `tests/test_storage_backend.py`
- Real-world and incident integration flows:
  - `tests/integration/test_api_real_world_flow.py`
  - `tests/integration/test_incident_rag_flow.py`
- Live LLM smoke:
  - `tests/integration/test_live_llm_flow.py`

## Why This Is Interview-Strong
- Demonstrates layered confidence, not only unit tests.
- Covers happy-path and failure-path behavior.
- Explicitly validates reliability features (fallback, arg repair, verification gates).

## Commands to Remember
```bash
make test
python -m pytest tests/integration/test_api_real_world_flow.py
RUN_POSTGRES_INTEGRATION_TESTS=1 RUN_LIVE_LLM_TESTS=1 OPENAI_API_KEY=<key> \
python -m pytest tests/integration/test_live_llm_flow.py
```

## Good Interview Line
> [!tip]
> "I tested determinism, integration, and optional live-LLM paths separately so failures are diagnosable and we don't confuse infrastructure issues with orchestration logic."

See: [[02_Architecture_Deep_Dive]], [[05_LLM_Integration_Story]]

