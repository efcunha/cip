"""Tools read-only AWS: Cost Explorer, Rightsizing e recursos ociosos.

Requer política IAM read-only (ver iac/aws-readonly-policy.json) e, preferencialmente,
credenciais temporárias via STS.

Em dev/CI, se `CIP_USE_MOCK_CLOUDS=true`, usa o mock server local
(ver scripts/mock_cloud_server.py) em vez de boto3.

Todas as chamadas têm cache TTL (default 1h) — evita duplicação de chamadas Cost
Explorer dentro de uma janela curta (mesmo resultado = mesmo cache).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from cip.config import get_settings
from cip.logging import get_logger
from cip.tools.base import assert_readonly
from cip.tools.cache import cached
from cip.tools.mock_client import is_mock_enabled

log = get_logger(__name__)


class AWSCostTools:
    def __init__(self) -> None:
        self._mock_mode = is_mock_enabled()
        if not self._mock_mode:
            import boto3
            s = get_settings()
            session = boto3.Session(
                aws_access_key_id=s.aws_access_key_id,
                aws_secret_access_key=s.aws_secret_access_key,
                aws_session_token=s.aws_session_token,
                region_name=s.aws_region,
            )
            self.ce = session.client("ce")
            self.ec2 = session.client("ec2")
            self.rds = session.client("rds")

    @cached(ttl=3600)
    def get_monthly_cost_by_service(self, days: int = 30) -> dict[str, Any]:
        """Custo dos últimos N dias agrupado por serviço (Cost Explorer)."""
        assert_readonly("get_cost_and_usage")
        if self._mock_mode:
            from cip.tools.mock_client import aws_cost_and_usage

            end = datetime.now(timezone.utc).date()
            start = end - timedelta(days=days)
            return aws_cost_and_usage({"Start": str(start), "End": str(end)})
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days)
        return self.ce.get_cost_and_usage(
            TimePeriod={"Start": str(start), "End": str(end)},
            Granularity="DAILY",
            Metrics=["UnblendedCost", "UsageQuantity"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

    @cached(ttl=3600)
    def get_rightsizing(self) -> dict[str, Any]:
        """Recomendações de rightsizing EC2 (Cost Explorer)."""
        assert_readonly("get_rightsizing_recommendation")
        if self._mock_mode:
            from cip.tools.mock_client import aws_rightsizing

            return aws_rightsizing()
        return self.ce.get_rightsizing_recommendation(Service="AmazonEC2")

    @cached(ttl=3600)
    def get_savings_plans_recommendation(self) -> dict[str, Any]:
        """Recomendações de Savings Plans Compute (1 ano, sem upfront)."""
        assert_readonly("get_savings_plans_purchase_recommendation")
        if self._mock_mode:
            from cip.tools.mock_client import aws_savings_plans

            return aws_savings_plans()
        return self.ce.get_savings_plans_purchase_recommendation(
            SavingsPlansType="COMPUTE_SP",
            TermInYears="ONE_YEAR",
            PaymentOption="NO_UPFRONT",
            LookbackPeriodInDays="THIRTY_DAYS",
        )

    @cached(ttl=1800)
    def list_unattached_volumes(self) -> list[dict[str, Any]]:
        """Volumes EBS em estado 'available' (não anexados a nenhuma EC2)."""
        assert_readonly("describe_volumes")
        if self._mock_mode:
            from cip.tools.mock_client import aws_unattached_volumes

            resp = aws_unattached_volumes()
            return [
                {"id": v["VolumeId"], "size_gb": v["Size"], "type": v["VolumeType"]}
                for v in resp.get("Volumes", [])
            ]
        vols = self.ec2.describe_volumes(
            Filters=[{"Name": "status", "Values": ["available"]}]
        )
        return [
            {"id": v["VolumeId"], "size_gb": v["Size"], "type": v["VolumeType"]}
            for v in vols.get("Volumes", [])
        ]

    @cached(ttl=1800)
    def list_unused_elastic_ips(self) -> list[dict[str, Any]]:
        """Elastic IPs não associados (cobram ~$0.005/hora)."""
        assert_readonly("describe_addresses")
        if self._mock_mode:
            from cip.tools.mock_client import aws_unassociated_elastic_ips

            resp = aws_unassociated_elastic_ips()
            return [
                {"ip": a.get("PublicIp"), "allocation_id": a.get("AllocationId")}
                for a in resp.get("Addresses", [])
            ]
        addresses = self.ec2.describe_addresses()
        return [
            {"ip": a.get("PublicIp"), "allocation_id": a.get("AllocationId")}
            for a in addresses.get("Addresses", [])
            if not a.get("AssociationId")
        ]

    def summarize(self) -> str:
        """Resumo textual para injetar no contexto do LLM."""
        try:
            cost = self.get_monthly_cost_by_service()
            unattached = self.list_unattached_volumes()
            unused_eips = self.list_unused_elastic_ips()
            total = sum(
                float(g["Metrics"]["UnblendedCost"]["Amount"])
                for day in cost.get("ResultsByTime", [])
                for g in day.get("Groups", [])
            )
            # Top 3 serviços por custo
            by_service: dict[str, float] = {}
            for day in cost.get("ResultsByTime", []):
                for g in day.get("Groups", []):
                    svc = g["Keys"][0] if g.get("Keys") else "?"
                    amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
                    by_service[svc] = by_service.get(svc, 0) + amt
            top3 = sorted(by_service.items(), key=lambda x: -x[1])[:3]
            top3_str = ", ".join(f"{s}: ${v:,.0f}" for s, v in top3)
            source = "[MOCK]" if self._mock_mode else "[AWS]"
            return (
                f"AWS {source} — custo (30d): ${total:,.2f}. "
                f"Top 3 serviços: {top3_str}. "
                f"Volumes EBS não anexados (desperdício): {len(unattached)}. "
                f"Elastic IPs ociosos: {len(unused_eips)}."
            )
        except Exception as exc:
            log.warning("aws_summary_failed", error=str(exc))
            return "AWS — não foi possível coletar dados ao vivo (verifique credenciais read-only)."
