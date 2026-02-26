#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-taskchain-orchestrator}"
ARTIFACT_REPO="${ARTIFACT_REPO:-taskchain}"
IMAGE_NAME="${IMAGE_NAME:-orchestrator-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
SERVICE_ACCOUNT_ID="${SERVICE_ACCOUNT_ID:-taskchain-orchestrator-sa}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-}"
CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-}"
DATABASE_URL_SECRET="${DATABASE_URL_SECRET:-}"
OPENAI_API_KEY_SECRET="${OPENAI_API_KEY_SECRET:-}"
ALLOW_UNAUTH="${ALLOW_UNAUTH:-1}"

ORCHESTRATOR_PLANNER_MODE="${ORCHESTRATOR_PLANNER_MODE:-deterministic}"
ORCHESTRATOR_EXECUTOR_MODE="${ORCHESTRATOR_EXECUTOR_MODE:-deterministic}"
ORCHESTRATOR_RAG_RERANK_MODE="${ORCHESTRATOR_RAG_RERANK_MODE:-auto}"
ORCHESTRATOR_TOOL_TIMEOUT_S="${ORCHESTRATOR_TOOL_TIMEOUT_S:-5.0}"
ORCHESTRATOR_TOOL_MAX_RETRIES="${ORCHESTRATOR_TOOL_MAX_RETRIES:-1}"
ORCHESTRATOR_TOOL_BACKOFF_S="${ORCHESTRATOR_TOOL_BACKOFF_S:-0.05}"
ORCHESTRATOR_COMPANY_TOOL_TIMEOUT_S="${ORCHESTRATOR_COMPANY_TOOL_TIMEOUT_S:-10.0}"
ORCHESTRATOR_LLM_MODEL="${ORCHESTRATOR_LLM_MODEL:-gpt-4o-mini}"

COMPANY_JIRA_BASE_URL="${COMPANY_JIRA_BASE_URL:-}"
COMPANY_METRICS_BASE_URL="${COMPANY_METRICS_BASE_URL:-}"
COMPANY_LOGS_BASE_URL="${COMPANY_LOGS_BASE_URL:-}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID is required." >&2
  exit 1
fi
if [[ -z "${CLOUD_SQL_INSTANCE}" ]]; then
  echo "CLOUD_SQL_INSTANCE is required (project:region:instance)." >&2
  exit 1
fi
if [[ -z "${DATABASE_URL_SECRET}" ]]; then
  echo "DATABASE_URL_SECRET is required." >&2
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI is required." >&2
  exit 1
fi

if [[ ! -f "data/rag_index.sqlite" ]]; then
  echo "WARNING: data/rag_index.sqlite not found."
  echo "Creating empty placeholder index so Docker build can proceed."
  mkdir -p data
  : > data/rag_index.sqlite
  echo "Tip: build a real index later with:"
  echo "  python scripts/build_rag_index.py --corpus data/rag_corpus_subset_v1.jsonl --index data/rag_index.sqlite"
fi

if ! gcloud meta list-files-for-upload 2>/dev/null | grep -Fxq "data/rag_index.sqlite"; then
  echo "ERROR: data/rag_index.sqlite is not in Cloud Build upload set." >&2
  echo "Check .gcloudignore/.gitignore rules before retrying." >&2
  exit 1
fi

if [[ -z "${IMAGE_TAG}" ]]; then
  if git rev-parse --short HEAD >/dev/null 2>&1; then
    IMAGE_TAG="$(git rev-parse --short HEAD)"
  else
    IMAGE_TAG="$(date +%Y%m%d%H%M%S)"
  fi
fi

echo "Using project: ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}" >/dev/null

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com

if ! gcloud artifacts repositories describe "${ARTIFACT_REPO}" \
  --location "${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${ARTIFACT_REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Taskchain images"
fi

if [[ -z "${SERVICE_ACCOUNT_EMAIL}" ]]; then
  SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${SERVICE_ACCOUNT_ID}" \
      --display-name="Taskchain Orchestrator Runtime"
  fi
fi

for role in roles/cloudsql.client roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="${role}" >/dev/null
done

if ! gcloud secrets describe "${DATABASE_URL_SECRET}" >/dev/null 2>&1; then
  echo "Secret ${DATABASE_URL_SECRET} does not exist." >&2
  exit 1
fi

if [[ -n "${OPENAI_API_KEY_SECRET}" ]]; then
  if ! gcloud secrets describe "${OPENAI_API_KEY_SECRET}" >/dev/null 2>&1; then
    echo "Secret ${OPENAI_API_KEY_SECRET} does not exist." >&2
    exit 1
  fi
fi

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${IMAGE_NAME}:${IMAGE_TAG}"
echo "Building image: ${IMAGE_URI}"
gcloud builds submit "${REPO_ROOT}" --tag "${IMAGE_URI}"

env_vars=(
  "ORCHESTRATOR_PLANNER_MODE=${ORCHESTRATOR_PLANNER_MODE}"
  "ORCHESTRATOR_EXECUTOR_MODE=${ORCHESTRATOR_EXECUTOR_MODE}"
  "ORCHESTRATOR_RAG_RERANK_MODE=${ORCHESTRATOR_RAG_RERANK_MODE}"
  "ORCHESTRATOR_TOOL_TIMEOUT_S=${ORCHESTRATOR_TOOL_TIMEOUT_S}"
  "ORCHESTRATOR_TOOL_MAX_RETRIES=${ORCHESTRATOR_TOOL_MAX_RETRIES}"
  "ORCHESTRATOR_TOOL_BACKOFF_S=${ORCHESTRATOR_TOOL_BACKOFF_S}"
  "ORCHESTRATOR_COMPANY_TOOL_TIMEOUT_S=${ORCHESTRATOR_COMPANY_TOOL_TIMEOUT_S}"
)
if [[ -n "${OPENAI_API_KEY_SECRET}" ]]; then
  env_vars+=("ORCHESTRATOR_LLM_PROVIDER=openai")
  env_vars+=("ORCHESTRATOR_LLM_MODEL=${ORCHESTRATOR_LLM_MODEL}")
fi
if [[ -n "${COMPANY_JIRA_BASE_URL}" ]]; then
  env_vars+=("COMPANY_JIRA_BASE_URL=${COMPANY_JIRA_BASE_URL}")
fi
if [[ -n "${COMPANY_METRICS_BASE_URL}" ]]; then
  env_vars+=("COMPANY_METRICS_BASE_URL=${COMPANY_METRICS_BASE_URL}")
fi
if [[ -n "${COMPANY_LOGS_BASE_URL}" ]]; then
  env_vars+=("COMPANY_LOGS_BASE_URL=${COMPANY_LOGS_BASE_URL}")
fi
env_csv="$(IFS=,; echo "${env_vars[*]}")"

secrets=("ORCHESTRATOR_DATABASE_URL=${DATABASE_URL_SECRET}:latest")
if [[ -n "${OPENAI_API_KEY_SECRET}" ]]; then
  secrets+=("OPENAI_API_KEY=${OPENAI_API_KEY_SECRET}:latest")
fi
secrets_csv="$(IFS=,; echo "${secrets[*]}")"

deploy_cmd=(
  gcloud run deploy "${SERVICE_NAME}"
  --image "${IMAGE_URI}"
  --region "${REGION}"
  --platform managed
  --service-account "${SERVICE_ACCOUNT_EMAIL}"
  --add-cloudsql-instances "${CLOUD_SQL_INSTANCE}"
  --set-env-vars "${env_csv}"
  --set-secrets "${secrets_csv}"
)
if [[ "${ALLOW_UNAUTH}" == "1" ]]; then
  deploy_cmd+=(--allow-unauthenticated)
else
  deploy_cmd+=(--no-allow-unauthenticated)
fi

echo "Deploying Cloud Run service: ${SERVICE_NAME}"
"${deploy_cmd[@]}"

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format='value(status.url)')"
cat <<EOF

Orchestrator deployed.
Service URL: ${SERVICE_URL}
EOF
