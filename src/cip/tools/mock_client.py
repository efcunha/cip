"""Mock Cloud HTTP client — permite tools chamarem mock server em dev/CI.

Quando `CIP_USE_MOCK_CLOUDS=true`, os tools AWS/Azure/GCP fazem chamadas HTTP
para o mock server (default: http://127.0.0.1:8888) em vez de boto3/azure-sdk/google-cloud.

Benefícios:
- CI/CD pode testar tools sem credenciais reais
- Devs podem trabalhar offline
- Testes reproduzíveis (mock é determinístico)
- Custo zero

Variáveis de ambiente:
- CIP_USE_MOCK_CLOUDS=true|false (default: false)
- CIP_MOCK_CLOUD_URL=http://127.0.0.1:8888 (default)

Uso:
    # Em dev (com mock server rodando)
    CIP_USE_MOCK_CLOUDS=true python -m cip.api.app

    # Em prod (com credenciais reais)
    unset CIP_USE_MOCK_CLOUDS  # ou =false
    python -m cip.api.app
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from cip.logging import get_logger

log = get_logger(__name__)

DEFAULT_MOCK_URL = "http://127.0.0.1:8888"


def is_mock_enabled() -> bool:
    """Retorna True se mock está habilitado via env var."""
    return os.getenv("CIP_USE_MOCK_CLOUDS", "false").lower() in ("true", "1", "yes")


def get_mock_base_url() -> str:
    """Retorna URL base do mock server."""
    return os.getenv("CIP_MOCK_CLOUD_URL", DEFAULT_MOCK_URL)


def _post(path: str, body: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    """Faz POST para o mock server."""
    url = f"{get_mock_base_url()}{path}"
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        log.warning("mock_call_failed", url=url, error=str(exc))
        raise


# ─────────────────────────────────────────────────────────────────────────
# AWS Cost Explorer mock endpoints
# ─────────────────────────────────────────────────────────────────────────


def aws_cost_and_usage(time_period: dict[str, str]) -> dict[str, Any]:
    """Mock GetCostAndUsage."""
    return _post("/aws/ce/cost-and-usage", {"TimePeriod": time_period})


def aws_rightsizing() -> dict[str, Any]:
    """Mock GetRightsizingRecommendation."""
    return _post("/aws/ce/rightsizing", {})


def aws_savings_plans() -> dict[str, Any]:
    """Mock GetSavingsPlansPurchaseRecommendation."""
    return _post("/aws/ce/savings-plans", {})


def aws_unattached_volumes() -> dict[str, Any]:
    """Mock DescribeVolumes (state=available = unattached)."""
    return _post("/aws/ec2/volumes", {})


def aws_unassociated_elastic_ips() -> dict[str, Any]:
    """Mock DescribeAddresses (AssociationId=null = unassociated)."""
    return _post("/aws/ec2/elastic-ips", {})


# ─────────────────────────────────────────────────────────────────────────
# Azure Advisor mock
# ─────────────────────────────────────────────────────────────────────────


def azure_advisor_recommendations() -> dict[str, Any]:
    """Mock Advisor recommendations.list()."""
    return _post("/azure/advisor/recommendations", {})


# ─────────────────────────────────────────────────────────────────────────
# GCP Recommender mock
# ─────────────────────────────────────────────────────────────────────────


def gcp_recommendations(recommender_id: str) -> list[dict[str, Any]]:
    """Mock listRecommendations para um recommender específico."""
    parent = f"projects/mock/locations/global/recommenders/{recommender_id}"
    return _post(f"/gcp/recommender/{recommender_id}", {"parent": parent})


def gcp_idle_resources() -> list[dict[str, Any]]:
    """Mock para IdleResourceRecommender."""
    return gcp_recommendations("google.cloud.compute.IdleResourceRecommender")


def gcp_machine_type() -> list[dict[str, Any]]:
    """Mock para MachineTypeRecommender (right-sizing)."""
    return gcp_recommendations("google.cloud.compute.instance.MachineTypeRecommender")


def gcp_iam_recommendations() -> list[dict[str, Any]]:
    """Mock para IAM recommender."""
    return gcp_recommendations("iam.policy.Recommender")


# ─────────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────────


def check_mock_available() -> bool:
    """Verifica se mock server está disponível."""
    try:
        url = f"{get_mock_base_url()}/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False