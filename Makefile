# TaskChain — Contributor Onboarding Agent
PYTHON := ./venv/bin/python
PIP := ./venv/bin/pip
PYTEST := ./venv/bin/pytest
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: help install api test check clean postgres-start postgres-stop

help:
	@echo "Available targets:"
	@echo "  make install          Install Python dependencies into ./venv"
	@echo "  make postgres-start   Start PostgreSQL container in Docker on port 5433"
	@echo "  make postgres-stop    Stop PostgreSQL container in Docker"
	@echo "  make api              Run the FastAPI server with uvicorn"
	@echo "  make test             Run the onboarding test suite"
	@echo "  make check            Compile modules and run tests"
	@echo "  make clean            Remove local Python cache artifacts"

install:
	$(PIP) install -r requirements.txt

postgres-start:
	docker run -d --name pg_taskchain -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=taskchain -p 5433:5432 postgres:latest 2>/dev/null || docker start pg_taskchain

postgres-stop:
	docker stop pg_taskchain

api:
	PYTHONPATH=. $(PYTHON) -m uvicorn api.server:app --host $(HOST) --port $(PORT)

test:
	PYTHONPATH=. $(PYTEST) -q tests

check:
	PYTHONPATH=. $(PYTHON) -m py_compile config.py ingestion/*.py agent/*.py api/*.py utils/*.py tests/*.py
	PYTHONPATH=. $(PYTEST) -q tests

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
