# Mock Systems (FastAPI)

This folder contains deterministic mock systems for Jira, metrics, and logs.

## Services

- Jira mock: `company_sim.mock_systems.jira_api:app`
- Metrics mock: `company_sim.mock_systems.metrics_api:app`
- Logs mock: `company_sim.mock_systems.logs_api:app`

## Seed Data

All endpoints read deterministic seed data from `company_sim/mock_systems/data/`.

## Run with Docker Compose

From repository root:

```bash
docker compose -f company_sim/mock_systems/docker-compose.yml up --build
```

Ports:

- Jira mock: `http://localhost:8001`
- Metrics mock: `http://localhost:8002`
- Logs mock: `http://localhost:8003`

OpenAPI docs:

- Jira: `http://localhost:8001/openapi.json`
- Metrics: `http://localhost:8002/openapi.json`
- Logs: `http://localhost:8003/openapi.json`

## Run Tests

```bash
make test
```
