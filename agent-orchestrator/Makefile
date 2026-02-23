.PHONY: setup run run-prod test test-unit test-integration fmt lint build-chroma-index eval-retrieval

PYTHON ?= .agent/bin/python
APP_MODULE := agent_orchestrator.api.main:app
HOST ?= 127.0.0.1
PORT ?= 8010
RETRIEVAL_MODE ?= all
EVAL_DATASET ?= ../data/retrieval_eval_queries.sample.jsonl

ifneq (,$(wildcard .env.example))
include .env.example
endif
ifneq (,$(wildcard .env))
include .env
endif
export

setup:
	$(PYTHON) -m pip install -e ".[dev]"
	@test -n "$$AGENT_ORCHESTRATOR_DATABASE_URL" || (echo "AGENT_ORCHESTRATOR_DATABASE_URL missing in .env/.env.example" && exit 1)
	@echo "Setup complete. Database URL loaded from env file."

run:
	PYTHONPATH=src $(PYTHON) -m uvicorn $(APP_MODULE) --reload --host $(HOST) --port $(PORT)

run-prod:
	PYTHONPATH=src $(PYTHON) -m uvicorn $(APP_MODULE) --host $(HOST) --port $(PORT)

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

test-unit:
	PYTHONPATH=src $(PYTHON) -m pytest -q tests/unit

test-integration:
	PYTHONPATH=src $(PYTHON) -m pytest -q tests/integration

fmt:
	PYTHONPATH=src $(PYTHON) -m black src tests

lint:
	PYTHONPATH=src $(PYTHON) -m ruff check src tests

build-chroma-index:
	PYTHONPATH=src $(PYTHON) scripts/build_chroma_index.py

eval-retrieval:
	PYTHONPATH=src $(PYTHON) scripts/ab_test_retrieval.py --mode $(RETRIEVAL_MODE) --dataset $(EVAL_DATASET)
