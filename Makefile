# TaskChain — Autonomous Repository Agent
PYTHON := ./venv/bin/python
PIP := ./venv/bin/pip
PYTEST := ./venv/bin/pytest
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: help install api test check bench clean

ARGS ?=

help:
	@echo "Available targets:"
	@echo "  make install   Install Python dependencies into ./venv"
	@echo "  make api       Run the FastAPI server with uvicorn"
	@echo "  make test      Run the test suite"
	@echo "  make check     Compile modules and run tests"
	@echo "  make bench     Retrieval benchmark; pass ARGS=--repo-id owner/repo --skip-ingest"
	@echo "  make clean     Remove local Python cache artifacts"

install:
	$(PIP) install -r requirements.txt

api:
	PYTHONPATH=. $(PYTHON) -m uvicorn api.server:app --host $(HOST) --port $(PORT)

test:
	PYTHONPATH=. $(PYTEST) -q tests

check:
	PYTHONPATH=. $(PYTHON) -m py_compile config.py ingestion/*.py agent/*.py api/*.py github/*.py llm/*.py utils/*.py tests/*.py
	PYTHONPATH=. $(PYTEST) -q tests

bench:
	PYTHONPATH=. $(PYTHON) scripts/benchmark_retrieval.py $(ARGS)

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
