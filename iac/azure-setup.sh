#!/usr/bin/env bash
# Cria um Service Principal read-only para a CIP no Azure.
# Requer az CLI autenticado com permissão para criar SPs e atribuir roles.
set -euo pipefail

SUBSCRIPTION_ID="${1:?Uso: azure-setup.sh <subscription-id> [sp-name]}"
SP_NAME="${2:-cip-readonly-sp}"
SCOPE="/subscriptions/${SUBSCRIPTION_ID}"

echo ">> Criando Service Principal '${SP_NAME}' com role Reader em ${SCOPE}"
CREDS=$(az ad sp create-for-rbac \
  --name "${SP_NAME}" \
  --role "Reader" \
  --scopes "${SCOPE}" \
  --only-show-errors)

APP_ID=$(echo "${CREDS}" | python -c "import sys,json;print(json.load(sys.stdin)['appId'])")

echo ">> Adicionando roles read-only extras (Advisor / Cost Management)"
az role assignment create --assignee "${APP_ID}" \
  --role "Cost Management Reader" --scope "${SCOPE}" --only-show-errors
# 'Advisor Reader' não é built-in em todas as clouds; Reader já cobre GET do Advisor.

echo ">> Credenciais (preencha o .env):"
echo "${CREDS}" | python - <<'PY'
import sys, json
c = json.load(sys.stdin)
print("AZURE_TENANT_ID=", c["tenant"])
print("AZURE_CLIENT_ID=", c["appId"])
print("AZURE_CLIENT_SECRET=", c["password"])
PY

echo ">> IMPORTANTE: guarde o secret com segurança e rotacione a cada 90 dias."
