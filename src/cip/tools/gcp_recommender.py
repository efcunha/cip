"""Tools read-only GCP: Recommender (custo/idle) + Asset Inventory.

Em dev/CI, se `CIP_USE_MOCK_CLOUDS=true`, usa o mock server local
(ver scripts/mock_cloud_server.py) em vez do google-cloud SDK.

Todas as chamadas têm cache TTL (default 1h).
"""

from __future__ import annotations

from typing import Any

from cip.config import get_settings
from cip.logging import get_logger
from cip.tools.base import assert_readonly
from cip.tools.cache import cached
from cip.tools.mock_client import is_mock_enabled

log = get_logger(__name__)


class GCPRecommenderTools:
    def __init__(self) -> None:
        self._mock_mode = is_mock_enabled()
        if not self._mock_mode:
            from google.cloud import recommender_v1
            self._project = get_settings().gcp_project_id
            self.client = recommender_v1.RecommenderClient()

    def _list(self, recommender_id: str) -> list[Any]:
        if self._mock_mode:
            from cip.tools.mock_client import gcp_recommendations
            return gcp_recommendations(recommender_id)
        parent = (
            f"projects/{self._project}/locations/global/recommenders/{recommender_id}"
        )
        return list(self.client.list_recommendations(parent=parent))

    @staticmethod
    def _normalize_cost(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Converte formato do mock para formato CIP."""
        out = []
        for r in recs:
            impact = None
            if "primaryImpact" in r:
                cost_proj = r["primaryImpact"].get("costProjection", {})
                if "cost" in cost_proj:
                    impact = cost_proj["cost"].get("units")
            out.append({
                "name": r.get("name"),
                "description": r.get("description"),
                "impact_units": impact,
            })
        return out

    @cached(ttl=3600)
    def get_cost_recommendations(self) -> list[dict[str, Any]]:
        """Recomendações de rightsizing para Compute Engine."""
        assert_readonly("list_recommendations")
        recs = self._list("google.cloud.compute.instance.MachineTypeRecommender")
        if self._mock_mode:
            return self._normalize_cost(recs)
        out = []
        for r in recs:
            impact = None
            if r.primary_impact and r.primary_impact.cost_projection:
                impact = r.primary_impact.cost_projection.cost.units
            out.append({"name": r.name, "description": r.description, "impact_units": impact})
        return out

    @cached(ttl=3600)
    def count_idle_resources(self) -> int:
        """Conta recursos ociosos (idle VMs, disks, IPs)."""
        assert_readonly("list_recommendations")
        try:
            return len(self._list("google.cloud.compute.IdleResourceRecommender"))
        except Exception:
            return 0

    @cached(ttl=3600)
    def get_iam_recommendations(self) -> list[dict[str, Any]]:
        """Recomendações IAM (least privilege)."""
        assert_readonly("list_recommendations")
        try:
            recs = self._list("iam.policy.Recommender")
            return [{"name": r.get("name"), "description": r.get("description")} for r in recs]
        except Exception:
            return []

    def summarize(self) -> str:
        try:
            recs = self.get_cost_recommendations()
            idle = self.count_idle_resources()
            iam = self.get_iam_recommendations()
            source = "[MOCK]" if self._mock_mode else "[GCP]"
            return (
                f"GCP {source} — Recommender: {len(recs)} recomendações de custo; "
                f"{idle} recursos ociosos detectados; "
                f"{len(iam)} recomendações IAM."
            )
        except Exception as exc:
            log.warning("gcp_summary_failed", error=str(exc))
            return "GCP — não foi possível coletar dados ao vivo (verifique a Service Account read-only)."
