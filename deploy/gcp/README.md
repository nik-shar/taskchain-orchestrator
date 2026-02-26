# GCP Deployment (Minimal-Change Path)

This guide deploys the existing stack to GCP with minimal code changes:

- `taskchain-orchestrator` on Cloud Run
- PostgreSQL on Cloud SQL
- Secret Manager for runtime secrets
- Optional Jira/Metrics/Logs mock APIs on Cloud Run

## 1) Prerequisites

- `gcloud` CLI installed and authenticated.
- Billing-enabled GCP project.
- APIs enabled (scripts do this automatically):
  - `run.googleapis.com`
  - `cloudbuild.googleapis.com`
  - `artifactregistry.googleapis.com`
  - `secretmanager.googleapis.com`
  - `sqladmin.googleapis.com`

## 2) Create Cloud SQL (PostgreSQL)

Set project/region first:

```bash
export PROJECT_ID="<your-project-id>"
export REGION="us-central1"
gcloud config set project "${PROJECT_ID}"
```

Create instance + DB + app user:

```bash
export SQL_INSTANCE="taskchain-pg"
export DB_NAME="orchestrator_db"
export DB_USER="orchestrator"
export DB_PASS="<strong-password>"

gcloud sql instances create "${SQL_INSTANCE}" \
  --database-version=POSTGRES_16 \
  --tier=db-perf-optimized-N-2 \
  --region="${REGION}"

gcloud sql databases create "${DB_NAME}" --instance="${SQL_INSTANCE}"
gcloud sql users create "${DB_USER}" --instance="${SQL_INSTANCE}" --password="${DB_PASS}"
```

Build the Cloud SQL socket DSN and store it in Secret Manager:

```bash
export INSTANCE_CONNECTION_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"
export DB_URL="postgresql://${DB_USER}:${DB_PASS}@/${DB_NAME}?host=/cloudsql/${INSTANCE_CONNECTION_NAME}"

# Create the secret once:
printf '%s' "${DB_URL}" | gcloud secrets create orchestrator-database-url --data-file=-

# On later rotations, add a new version:
# printf '%s' "${DB_URL}" | gcloud secrets versions add orchestrator-database-url --data-file=-
```

## 3) (Optional) Deploy Mock Jira/Metrics/Logs Services

If you want `jira_search_tickets`, `metrics_query`, and `logs_search` working in cloud demos, deploy mocks:

```bash
PROJECT_ID="${PROJECT_ID}" REGION="${REGION}" \
bash scripts/gcp/deploy_mock_services_cloud_run.sh
```

The script prints:

- `COMPANY_JIRA_BASE_URL`
- `COMPANY_METRICS_BASE_URL`
- `COMPANY_LOGS_BASE_URL`

Use those values in step 4.

## 4) Deploy Orchestrator to Cloud Run

Deterministic-only deploy:

```bash
PROJECT_ID="${PROJECT_ID}" \
REGION="${REGION}" \
CLOUD_SQL_INSTANCE="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}" \
DATABASE_URL_SECRET="orchestrator-database-url" \
COMPANY_JIRA_BASE_URL="<optional-jira-url>" \
COMPANY_METRICS_BASE_URL="<optional-metrics-url>" \
COMPANY_LOGS_BASE_URL="<optional-logs-url>" \
bash scripts/gcp/deploy_orchestrator_cloud_run.sh
```

Notes:
- Step 3 is optional. If you skip mocks, leave `COMPANY_*_BASE_URL` unset (or remove those lines).
- The deploy script now creates `data/rag_index.sqlite` placeholder automatically if missing, so build does not fail.

LLM-enabled deploy (optional):

```bash
printf '%s' '<openai-api-key>' | gcloud secrets create openai-api-key --data-file=-

PROJECT_ID="${PROJECT_ID}" \
REGION="${REGION}" \
CLOUD_SQL_INSTANCE="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}" \
DATABASE_URL_SECRET="orchestrator-database-url" \
OPENAI_API_KEY_SECRET="openai-api-key" \
ORCHESTRATOR_PLANNER_MODE="llm" \
ORCHESTRATOR_EXECUTOR_MODE="llm" \
bash scripts/gcp/deploy_orchestrator_cloud_run.sh
```

## 5) Smoke Test

After deployment, get URL:

```bash
gcloud run services describe taskchain-orchestrator \
  --region "${REGION}" \
  --format='value(status.url)'
```

Use that URL:

```bash
export SERVICE_URL="<cloud-run-url>"
curl -sS "${SERVICE_URL}/health"
curl -sS "${SERVICE_URL}/tools"
```

Create and run one task:

```bash
TASK_ID="$(curl -sS -X POST "${SERVICE_URL}/tasks" \
  -H "Content-Type: application/json" \
  -d '{"task":"Summarize incident policy escalation for P1 alerts.","context":{"service":"saas-api","severity":"P1"}}' \
  | python -c 'import json,sys;print(json.load(sys.stdin)["task_id"])')"

curl -sS -X POST "${SERVICE_URL}/tasks/${TASK_ID}/run" -H "Content-Type: application/json" -d '{}'
curl -sS "${SERVICE_URL}/tasks/${TASK_ID}"
```

## Notes

- Container images now include `company_details/company_sim` and `data/rag_index.sqlite`, so local retrieval/reference tools work in Cloud Run.
- Runtime secrets are injected via Secret Manager (`--set-secrets`); no `.env` file is needed in cloud.
- You can redeploy safely by rerunning the scripts with a new image tag.

## Deploy `agent-orchestrator` (replace previous app in same service)

If you want Cloud Run to serve the `agent-orchestrator` UI/API instead of the older app, use:

```bash
PROJECT_ID="${PROJECT_ID}" \
REGION="${REGION}" \
SERVICE_NAME="taskchain-orchestrator" \
CLOUD_SQL_INSTANCE="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}" \
DATABASE_URL_SECRET="orchestrator-database-url" \
bash scripts/gcp/deploy_agent_orchestrator_cloud_run.sh
```

Optional LLM mode for `agent-orchestrator`:

```bash
PROJECT_ID="${PROJECT_ID}" \
REGION="${REGION}" \
SERVICE_NAME="taskchain-orchestrator" \
CLOUD_SQL_INSTANCE="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}" \
DATABASE_URL_SECRET="orchestrator-database-url" \
OPENAI_API_KEY_SECRET="openai-api-key" \
AGENT_ORCHESTRATOR_PLANNER_MODE="llm" \
AGENT_ORCHESTRATOR_EXECUTOR_MODE="llm" \
bash scripts/gcp/deploy_agent_orchestrator_cloud_run.sh
```
