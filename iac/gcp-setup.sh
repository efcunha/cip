#!/usr/bin/env bash
# Cria uma Service Account read-only para a CIP no GCP.
# Requer gcloud autenticado com permissão para criar SAs e conceder roles.
set -euo pipefail

PROJECT_ID="${1:?Uso: gcp-setup.sh <project-id> [sa-name]}"
SA_NAME="${2:-cip-readonly-sa}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo ">> Criando Service Account '${SA_NAME}' em ${PROJECT_ID}"
gcloud iam service-accounts create "${SA_NAME}" \
  --project "${PROJECT_ID}" \
  --display-name "CIP read-only" || true

echo ">> Concedendo roles read-only"
for role in \
    roles/viewer \
    roles/recommender.viewer \
    roles/cloudasset.viewer \
    roles/billing.viewer \
    roles/monitoring.viewer; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${SA_EMAIL}" \
    --role "${role}" \
    --condition None >/dev/null
  echo "   + ${role}"
done

KEY_FILE="gcp-readonly-sa.json"
echo ">> Gerando chave em ${KEY_FILE} (mova para /secrets e aponte GOOGLE_APPLICATION_CREDENTIALS)"
gcloud iam service-accounts keys create "${KEY_FILE}" \
  --iam-account "${SA_EMAIL}"

echo ">> Configure no .env:"
echo "GCP_PROJECT_ID=${PROJECT_ID}"
echo "GOOGLE_APPLICATION_CREDENTIALS=/secrets/${KEY_FILE}"
echo ">> Prefira Workload Identity Federation em produção (evita chave estática)."
