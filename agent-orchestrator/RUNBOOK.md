# Agent-Orchestrator Runbook

This runbook is for the `agent-orchestrator` service only.
It covers local operation, Cloud Run deployment, smoke tests, rollback, and common failures.

## 1) Scope and endpoints

Service endpoints:

- `GET /health`
- `GET /tools`
- `POST /tasks`
- `POST /tasks/{task_id}/run`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/runs/latest`

Request contract for task creation:

- field name is `prompt` (not `task`)
- optional `context` keys used by runtime: `service`, `priority`, `severity`, `status`

## 2) Prerequisites

- Python 3.11+ (3.13 used in this repo)
- Docker (for local PostgreSQL)
- `gcloud` CLI authenticated to your GCP project (for cloud deploy)
- Existing files in repo root:
  - `company_details/company_sim/`
  - `data/rag_index.sqlite` (recommended for incident retrieval)

## 3) Local run (deterministic baseline)

Start PostgreSQL:

```bash
docker run --name agent-orchestrator-postgres \
  -e POSTGRES_USER=orchestrator \
  -e POSTGRES_PASSWORD=orchestrator \
  -e POSTGRES_DB=orchestrator_db \
  -p 5432:5432 \
  -d postgres:16
```

Install and run app:

```bash
cd agent-orchestrator
python -m venv .agent
source .agent/bin/activate
python -m pip install -e ".[dev]"

export AGENT_ORCHESTRATOR_DATABASE_URL='postgresql://orchestrator:orchestrator@127.0.0.1:5432/orchestrator_db'
make run
```

App URL: `http://127.0.0.1:8010`

## 4) Local smoke test

Run in another terminal:

```bash
BASE_URL='http://127.0.0.1:8010'

curl -sS "${BASE_URL}/health"
curl -sS "${BASE_URL}/tools"

TASK_ID="$(curl -sS -X POST "${BASE_URL}/tasks" \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt":"P1 incident in checkout: elevated latency and 5xx errors. Build an incident brief with evidence.",
    "context":{"service":"checkout","severity":"P1","priority":"P1","status":"Investigating"}
  }' | python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')"

curl -sS -X POST "${BASE_URL}/tasks/${TASK_ID}/run"
curl -sS "${BASE_URL}/tasks/${TASK_ID}"
curl -sS "${BASE_URL}/tasks/${TASK_ID}/runs/latest"
```

Expected:

- `/health` returns `{"status":"ok",...}`
- task status becomes `completed`
- `runs/latest` includes `plan_json`, `tool_results_json`, `verification_json`

## 5) Cloud Run deployment (agent-orchestrator)

Important:

- deploy script default `SERVICE_NAME` is `taskchain-orchestrator`
- if you keep that default, this replaces traffic for the previous app on that service

Set project and region:

```bash
export PROJECT_ID='<your-project-id>'
export REGION='us-central1'
gcloud config set project "${PROJECT_ID}"
```

Create Cloud SQL PostgreSQL:

```bash
export SQL_INSTANCE='taskchain-pg'
export DB_NAME='orchestrator_db'
export DB_USER='orchestrator'
export DB_PASS='<strong-password>'

gcloud sql instances create "${SQL_INSTANCE}" \
  --database-version=POSTGRES_16 \
  --tier=db-perf-optimized-N-2 \
  --region="${REGION}"

gcloud sql databases create "${DB_NAME}" --instance="${SQL_INSTANCE}"
gcloud sql users create "${DB_USER}" --instance="${SQL_INSTANCE}" --password="${DB_PASS}"
```

Create Secret Manager secret for DB URL:

```bash
export INSTANCE_CONNECTION_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"
export DB_URL="postgresql://${DB_USER}:${DB_PASS}@/${DB_NAME}?host=/cloudsql/${INSTANCE_CONNECTION_NAME}"

printf '%s' "${DB_URL}" | gcloud secrets create orchestrator-database-url --data-file=-
```

Deploy deterministic mode:

```bash
PROJECT_ID="${PROJECT_ID}" \
REGION="${REGION}" \
SERVICE_NAME="taskchain-orchestrator" \
CLOUD_SQL_INSTANCE="${INSTANCE_CONNECTION_NAME}" \
DATABASE_URL_SECRET="orchestrator-database-url" \
bash scripts/gcp/deploy_agent_orchestrator_cloud_run.sh
```

Optional LLM mode:

```bash
printf '%s' '<openai-api-key>' | gcloud secrets create openai-api-key --data-file=-

PROJECT_ID="${PROJECT_ID}" \
REGION="${REGION}" \
SERVICE_NAME="taskchain-orchestrator" \
CLOUD_SQL_INSTANCE="${INSTANCE_CONNECTION_NAME}" \
DATABASE_URL_SECRET="orchestrator-database-url" \
OPENAI_API_KEY_SECRET="openai-api-key" \
AGENT_ORCHESTRATOR_PLANNER_MODE="llm" \
AGENT_ORCHESTRATOR_EXECUTOR_MODE="llm" \
bash scripts/gcp/deploy_agent_orchestrator_cloud_run.sh
```

## 6) Cloud smoke test

```bash
SERVICE_URL="$(gcloud run services describe taskchain-orchestrator \
  --region "${REGION}" --format='value(status.url)')"

curl -sS "${SERVICE_URL}/health"
curl -sS "${SERVICE_URL}/tools"

TASK_ID="$(curl -sS -X POST "${SERVICE_URL}/tasks" \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt":"Summarize P1 escalation obligations and provide incident evidence references.",
    "context":{"service":"saas-api","severity":"P1","priority":"P1"}
  }' | python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')"

curl -sS -X POST "${SERVICE_URL}/tasks/${TASK_ID}/run"
curl -sS "${SERVICE_URL}/tasks/${TASK_ID}"
curl -sS "${SERVICE_URL}/tasks/${TASK_ID}/runs/latest"
```

## 7) Operations

View Cloud Run logs:

```bash
gcloud run services logs read taskchain-orchestrator --region "${REGION}" --limit 200
```

List revisions:

```bash
gcloud run revisions list --service taskchain-orchestrator --region "${REGION}"
```

Rollback traffic to a previous revision:

```bash
gcloud run services update-traffic taskchain-orchestrator \
  --region "${REGION}" \
  --to-revisions <REVISION_NAME>=100
```

## 8) Troubleshooting

`500 Task run failed`:

- inspect Cloud Run logs
- inspect `GET /tasks/{task_id}/runs/latest` for `state_json.error` and `verification_json`

`AGENT_ORCHESTRATOR_DATABASE_URL is required`:

- local: export `AGENT_ORCHESTRATOR_DATABASE_URL`
- cloud: verify `DATABASE_URL_SECRET` exists and is bound during deploy

Incident retrieval empty:

- verify `data/rag_index.sqlite` exists in repo root before deploy/build
- if needed, rebuild index:

```bash
python scripts/build_rag_index.py \
  --corpus data/rag_corpus_subset_v1.jsonl \
  --index data/rag_index.sqlite
```

LLM mode appears deterministic:

- inspect `verification.runtime.planner` and `verification.runtime.executor`
- `fallback_used: true` indicates deterministic fallback with reason
