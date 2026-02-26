#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-asia-south1}"
SERVICE_NAME="${SERVICE_NAME:-taskchain-orchestrator}"
ARTIFACT_REPO="${ARTIFACT_REPO:-taskchain}"
IMAGE_NAME="${IMAGE_NAME:-agent-orchestrator-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
SERVICE_ACCOUNT_ID="${SERVICE_ACCOUNT_ID:-taskchain-orchestrator-sa}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-}"
CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-}"
DATABASE_URL_SECRET="${DATABASE_URL_SECRET:-}"
OPENAI_API_KEY_SECRET="${OPENAI_API_KEY_SECRET:-}"
ALLOW_UNAUTH="${ALLOW_UNAUTH:-1}"

AGENT_ORCHESTRATOR_APP_ENV="${AGENT_ORCHESTRATOR_APP_ENV:-prod}"
AGENT_ORCHESTRATOR_APP_DEBUG="${AGENT_ORCHESTRATOR_APP_DEBUG:-false}"
AGENT_ORCHESTRATOR_PLANNER_MODE="${AGENT_ORCHESTRATOR_PLANNER_MODE:-deterministic}"
AGENT_ORCHESTRATOR_EXECUTOR_MODE="${AGENT_ORCHESTRATOR_EXECUTOR_MODE:-deterministic}"
AGENT_ORCHESTRATOR_MAX_GRAPH_LOOPS="${AGENT_ORCHESTRATOR_MAX_GRAPH_LOOPS:-2}"
AGENT_ORCHESTRATOR_TOOL_TIMEOUT_S="${AGENT_ORCHESTRATOR_TOOL_TIMEOUT_S:-5.0}"
AGENT_ORCHESTRATOR_TOOL_MAX_RETRIES="${AGENT_ORCHESTRATOR_TOOL_MAX_RETRIES:-1}"
AGENT_ORCHESTRATOR_TOOL_RETRY_BACKOFF_S="${AGENT_ORCHESTRATOR_TOOL_RETRY_BACKOFF_S:-0.05}"
AGENT_ORCHESTRATOR_LLM_PROVIDER="${AGENT_ORCHESTRATOR_LLM_PROVIDER:-openai}"
AGENT_ORCHESTRATOR_LLM_MODEL="${AGENT_ORCHESTRATOR_LLM_MODEL:-gpt-4o-mini}"
AGENT_ORCHESTRATOR_LLM_BASE_URL="${AGENT_ORCHESTRATOR_LLM_BASE_URL:-https://api.openai.com/v1}"
AGENT_ORCHESTRATOR_LLM_TIMEOUT_S="${AGENT_ORCHESTRATOR_LLM_TIMEOUT_S:-8.0}"
AGENT_ORCHESTRATOR_LLM_MAX_RETRIES="${AGENT_ORCHESTRATOR_LLM_MAX_RETRIES:-1}"
AGENT_ORCHESTRATOR_LLM_BACKOFF_S="${AGENT_ORCHESTRATOR_LLM_BACKOFF_S:-0.2}"
AGENT_ORCHESTRATOR_COMPANY_SIM_ROOT="${AGENT_ORCHESTRATOR_COMPANY_SIM_ROOT:-/app/company_details/company_sim}"
AGENT_ORCHESTRATOR_RAG_INDEX_PATH="${AGENT_ORCHESTRATOR_RAG_INDEX_PATH:-/app/data/rag_index.sqlite}"

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
gcloud builds submit "${REPO_ROOT}" \
  --ignore-file "${REPO_ROOT}/.gcloudignore.agent-orchestrator" \
  --config "${REPO_ROOT}/cloudbuild.agent-orchestrator.yaml" \
  --substitutions "_IMAGE_URI=${IMAGE_URI}"

env_vars=(
  "AGENT_ORCHESTRATOR_APP_ENV=${AGENT_ORCHESTRATOR_APP_ENV}"
  "AGENT_ORCHESTRATOR_APP_DEBUG=${AGENT_ORCHESTRATOR_APP_DEBUG}"
  "AGENT_ORCHESTRATOR_PLANNER_MODE=${AGENT_ORCHESTRATOR_PLANNER_MODE}"
  "AGENT_ORCHESTRATOR_EXECUTOR_MODE=${AGENT_ORCHESTRATOR_EXECUTOR_MODE}"
  "AGENT_ORCHESTRATOR_MAX_GRAPH_LOOPS=${AGENT_ORCHESTRATOR_MAX_GRAPH_LOOPS}"
  "AGENT_ORCHESTRATOR_TOOL_TIMEOUT_S=${AGENT_ORCHESTRATOR_TOOL_TIMEOUT_S}"
  "AGENT_ORCHESTRATOR_TOOL_MAX_RETRIES=${AGENT_ORCHESTRATOR_TOOL_MAX_RETRIES}"
  "AGENT_ORCHESTRATOR_TOOL_RETRY_BACKOFF_S=${AGENT_ORCHESTRATOR_TOOL_RETRY_BACKOFF_S}"
  "AGENT_ORCHESTRATOR_LLM_PROVIDER=${AGENT_ORCHESTRATOR_LLM_PROVIDER}"
  "AGENT_ORCHESTRATOR_LLM_MODEL=${AGENT_ORCHESTRATOR_LLM_MODEL}"
  "AGENT_ORCHESTRATOR_LLM_BASE_URL=${AGENT_ORCHESTRATOR_LLM_BASE_URL}"
  "AGENT_ORCHESTRATOR_LLM_TIMEOUT_S=${AGENT_ORCHESTRATOR_LLM_TIMEOUT_S}"
  "AGENT_ORCHESTRATOR_LLM_MAX_RETRIES=${AGENT_ORCHESTRATOR_LLM_MAX_RETRIES}"
  "AGENT_ORCHESTRATOR_LLM_BACKOFF_S=${AGENT_ORCHESTRATOR_LLM_BACKOFF_S}"
  "AGENT_ORCHESTRATOR_COMPANY_SIM_ROOT=${AGENT_ORCHESTRATOR_COMPANY_SIM_ROOT}"
  "AGENT_ORCHESTRATOR_RAG_INDEX_PATH=${AGENT_ORCHESTRATOR_RAG_INDEX_PATH}"
)
env_csv="$(IFS=,; echo "${env_vars[*]}")"

secrets=("AGENT_ORCHESTRATOR_DATABASE_URL=${DATABASE_URL_SECRET}:latest")
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

agent-orchestrator deployed.
Service URL: ${SERVICE_URL}
EOF
