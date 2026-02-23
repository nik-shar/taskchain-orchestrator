.PHONY: run run-manual-tool test fmt lint

run:
	uvicorn orchestrator_api.main:app --reload --host 127.0.0.1 --port 8000

run-manual-tool:
	uvicorn orchestrator_api.manual_tool:app --reload --host 127.0.0.1 --port 8010

test:
	python -m pytest tests

fmt:
	python -m black src tests

lint:
	python -m ruff check src tests
