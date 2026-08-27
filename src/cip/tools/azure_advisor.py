"""Tools read-only Azure: Advisor (recomendações) + Cost Management.

Em dev/CI, se `CIP_USE_MOCK_CLOUDS=true`, usa o mock server local
(ver scripts/mock_cloud_server.py) em vez do Azure SDK.

Todas as chamadas têm cache TTL (default 1h) — Advisor retorna os mesmos dados
dentro de uma janela curta (recomendações são atualizadas diariamente).
"""

from __future__ import annotations

from typing import Any

from cip.config import get_settings
from cip.logging import get_logger
from cip.tools.base import assert_readonly
from cip.tools.cache import cached
from cip.tools.mock_client import is_mock_enabled

log = get_logger(__name__)


class AzureAdvisorTools:
    def __init__(self) -> None:
        self._mock_mode = is_mock_enabled()
        self.advisor = None
        self._cred_error: str | None = None
        if not self._mock_mode:
            try:
                from azure.identity import ClientSecretCredential, DefaultAzureCredential
                from azure.mgmt.advisor import AdvisorManagementClient

                s = get_settings()
                if s.azure_client_id and s.azure_client_secret and s.azure_tenant_id:
                    cred = ClientSecretCredential(
                        tenant_id=s.azure_tenant_id,
                        client_id=s.azure_client_id,
                        client_secret=s.azure_client_secret,
                    )
                else:
                    cred = DefaultAzureCredential()
                self._sub = s.azure_subscription_id
                self.advisor = AdvisorManagementClient(cred, self._sub)
            except Exception as exc:  # noqa: BLE001
                # Sem credenciais (dev/CI, IS_TESTING) o DefaultAzureCredential
                # lança em __init__ — degrada graciosamente em vez de derrubar.
                self._cred_error = str(exc)
                log.warning("azure_cred_init_failed", error=str(exc))

    @cached(ttl=3600)
    def get_cost_recommendations(self) -> list[dict[str, Any]]:
        """Recomendações de custo do Azure Advisor."""
        assert_readonly("recommendations.list")
        if self._mock_mode:
            from cip.tools.mock_client import azure_advisor_recommendations

            resp = azure_advisor_recommendations()
            return self._filter_category(resp.get("value", []), "Cost")

        if self.advisor is None:  # sem credenciais — degradação graciosa
            return []
        recs = self.advisor.recommendations.list()
        out = []
        for r in recs:
            if getattr(r, "category", None) != "Cost":
                continue
            sd = getattr(r, "short_description", None)
            out.append(
                {
                    "id": r.id,
                    "impact": getattr(r, "impact", None),
                    "problem": getattr(sd, "problem", None),
                    "solution": getattr(sd, "solution", None),
                }
            )
        return out

    @staticmethod
    def _filter_category(recs: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
        """Filtra recs por categoria + normaliza para formato CIP."""
        out = []
        for r in recs:
            if r.get("category") != category:
                continue
            sd = r.get("shortDescription", {}) or {}
            out.append(
                {
                    "id": r.get("id"),
                    "impact": r.get("impact"),
                    "problem": sd.get("problem"),
                    "solution": sd.get("solution"),
                }
            )
        return out

    @cached(ttl=3600)
    def get_security_recommendations(self) -> list[dict[str, Any]]:
        """Recomendações de segurança do Azure Advisor (alta/medium/low)."""
        assert_readonly("recommendations.list")
        if self._mock_mode:
            from cip.tools.mock_client import azure_advisor_recommendations

            resp = azure_advisor_recommendations()
            return self._filter_category(resp.get("value", []), "Security")

        if self.advisor is None:  # sem credenciais — degradação graciosa
            return []
        recs = self.advisor.recommendations.list()
        out = []
        for r in recs:
            if getattr(r, "category", None) != "Security":
                continue
            sd = getattr(r, "short_description", None)
            out.append(
                {
                    "id": r.id,
                    "impact": getattr(r, "impact", None),
                    "problem": getattr(sd, "problem", None),
                }
            )
        return out

    @cached(ttl=3600)
    def get_high_availability_recommendations(self) -> list[dict[str, Any]]:
        """Recomendações de alta disponibilidade (HA) do Azure Advisor."""
        assert_readonly("recommendations.list")
        if self._mock_mode:
            from cip.tools.mock_client import azure_advisor_recommendations

            resp = azure_advisor_recommendations()
            return self._filter_category(resp.get("value", []), "HighAvailability")

        if self.advisor is None:  # sem credenciais — degradação graciosa
            return []
        recs = self.advisor.recommendations.list()
        out = []
        for r in recs:
            if getattr(r, "category", None) != "HighAvailability":
                continue
            sd = getattr(r, "short_description", None)
            out.append(
                {
                    "id": r.id,
                    "impact": getattr(r, "impact", None),
                    "problem": getattr(sd, "problem", None),
                }
            )
        return out

    def summarize(self) -> str:
        try:
            cost = self.get_cost_recommendations()
            sec = self.get_security_recommendations()
            ha = self.get_high_availability_recommendations()
            cost_high = sum(1 for r in cost if r.get("impact") == "High")
            sec_high = sum(1 for r in sec if r.get("impact") == "High")
            ha_high = sum(1 for r in ha if r.get("impact") == "High")
            source = "[MOCK]" if self._mock_mode else "[Azure]"
            return (
                f"Azure {source} — Advisor: {len(cost)} custo ({cost_high} alto), "
                f"{len(sec)} segurança ({sec_high} alto), "
                f"{len(ha)} HA ({ha_high} alto)."
            )
        except Exception as exc:
            log.warning("azure_summary_failed", error=str(exc))
            return "Azure — não foi possível coletar dados ao vivo (verifique o Service Principal read-only)."
