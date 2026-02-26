#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
ARTIFACT_REPO="${ARTIFACT_REPO:-taskchain}"
MOCK_IMAGE_NAME="${MOCK_IMAGE_NAME:-company-mocks}"
IMAGE_TAG="${IMAGE_TAG:-}"
JIRA_SERVICE_NAME="${JIRA_SERVICE_NAME:-jira-mock}"
METRICS_SERVICE_NAME="${METRICS_SERVICE_NAME:-metrics-mock}"
LOGS_SERVICE_NAME="${LOGS_SERVICE_NAME:-logs-mock}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID is required." >&2
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI is required." >&2
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
  artifactregistry.googleapis.com

if ! gcloud artifacts repositories describe "${ARTIFACT_REPO}" \
  --location "${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${ARTIFACT_REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Taskchain images"
fi

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${MOCK_IMAGE_NAME}:${IMAGE_TAG}"
echo "Building image: ${IMAGE_URI}"
gcloud builds submit "${REPO_ROOT}/company_details" \
  --file company_sim/mock_systems/Dockerfile \
  --tag "${IMAGE_URI}"

deploy_mock() {
  local service_name="$1"
  local app_module="$2"
  echo "Deploying ${service_name} (${app_module})"
  gcloud run deploy "${service_name}" \
    --image "${IMAGE_URI}" \
    --region "${REGION}" \
    --platform managed \
    --allow-unauthenticated \
    --set-env-vars "APP_MODULE=${app_module}"
}

deploy_mock "${JIRA_SERVICE_NAME}" "company_sim.mock_systems.jira_api:app"
deploy_mock "${METRICS_SERVICE_NAME}" "company_sim.mock_systems.metrics_api:app"
deploy_mock "${LOGS_SERVICE_NAME}" "company_sim.mock_systems.logs_api:app"

JIRA_URL="$(gcloud run services describe "${JIRA_SERVICE_NAME}" --region "${REGION}" --format='value(status.url)')"
METRICS_URL="$(gcloud run services describe "${METRICS_SERVICE_NAME}" --region "${REGION}" --format='value(status.url)')"
LOGS_URL="$(gcloud run services describe "${LOGS_SERVICE_NAME}" --region "${REGION}" --format='value(status.url)')"

cat <<EOF

Mock services deployed.
Use these values when deploying orchestrator:
  COMPANY_JIRA_BASE_URL=${JIRA_URL}
  COMPANY_METRICS_BASE_URL=${METRICS_URL}
  COMPANY_LOGS_BASE_URL=${LOGS_URL}
EOF
