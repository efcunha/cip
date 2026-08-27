#!/usr/bin/env python3
"""Mock Cloud API server para testar tools sem credenciais reais.

Emula endpoints REST das 3 clouds com respostas realistas:
- AWS Cost Explorer (CostAndUsage, Rightsizing, Savings Plans)
- Azure Advisor (recommendations)
- GCP Recommender (recommendations, asset inventory)

Uso (desenvolvimento local):
    python scripts/mock_cloud_server.py --port 8888 &
    AWS_COST_ENDPOINT=http://localhost:8888/aws python -c "..."

Respostas são geradas com base nos parâmetros de request, simulando:
- Latência real (~200-800ms)
- Estrutura JSON fiel à API oficial
- Variação determinística (seed) para testes reproduzíveis

Vantagens:
- CI/CD pode testar tools sem AWS/Azure/GCP creds
- Devs podem trabalhar offline
- Testes reproduzíveis
- Custo zero
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# ─────────────────────────────────────────────────────────────────────────
# Deterministic RNG baseado em request
# ─────────────────────────────────────────────────────────────────────────


def _seed_for(request: dict[str, Any]) -> random.Random:
    """Gera RNG determinístico baseado no request (reprodutibilidade)."""
    payload = json.dumps(request, sort_keys=True, default=str)
    seed = int(hashlib.sha256(payload.encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def _simulate_latency(rng: random.Random, base_ms: int = 300, variance_ms: int = 200) -> None:
    """Simula latência de API real."""
    import time as _time

    delay = (base_ms + rng.randint(-variance_ms // 2, variance_ms // 2)) / 1000
    _time.sleep(max(0, delay))


# ─────────────────────────────────────────────────────────────────────────
# AWS Cost Explorer mocks
# ─────────────────────────────────────────────────────────────────────────


def _aws_cost_and_usage(request: dict[str, Any]) -> dict[str, Any]:
    """Emula AWS Cost Explorer GetCostAndUsage."""
    rng = _seed_for(request)
    _simulate_latency(rng, base_ms=500)

    time_period = request.get("TimePeriod", {})
    start = time_period.get("Start", "2026-08-01")
    end = time_period.get("End", "2026-08-31")

    # Calcula dias no período (inclusivo: 01 a 03 = 3 dias)
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    days = (end_dt - start_dt).days + 1
    if days < 1:
        days = 1  # fallback: mesmo dia = 1 dia

    # Top serviços AWS
    services = [
        "AmazonEC2", "AmazonS3", "AmazonRDS", "AWSLambda",
        "AmazonCloudFront", "AmazonEKS", "AmazonDynamoDB", "AmazonElastiCache",
    ]
    # Custos sintéticos (USD/dia) - sempre gera 8 services
    service_costs = {s: max(50, rng.uniform(50, 5000)) for s in services}

    results_by_time = []
    for day in range(days):
        date = (start_dt + timedelta(days=day)).strftime("%Y-%m-%d")
        groups = []
        for service, cost in service_costs.items():
            # Variação diária ±10%
            daily = cost * rng.uniform(0.9, 1.1)
            groups.append({
                "Keys": [service],
                "Metrics": {
                    "UnblendedCost": {"Amount": f"{daily:.2f}", "Unit": "USD"},
                    "UsageQuantity": {"Amount": f"{rng.uniform(100, 10000):.2f}", "Unit": "N/A"},
                },
            })
        results_by_time.append({
            "TimePeriod": {"Start": date, "End": date},
            "Groups": groups,
            "Estimated": False,
        })

    return {
        "ResultsByTime": results_by_time,
        "DimensionKeyAttributes": [],
        "ResponseMetadata": {"RequestId": "mock-" + hashlib.md5(start.encode()).hexdigest()[:16]},
    }


def _aws_rightsizing(request: dict[str, Any]) -> dict[str, Any]:
    """Emula AWS Cost Explorer GetRightsizingRecommendation."""
    rng = _seed_for(request)
    _simulate_latency(rng, base_ms=700)

    recommendations = []
    instance_families = ["m5", "c5", "r5"]
    for i in range(rng.randint(2, 8)):
        family = rng.choice(instance_families)
        size = rng.choice(["large", "xlarge", "2xlarge"])
        instance = f"{family}.{size}"
        current_cost = rng.uniform(50, 500)
        # Mapear família para nova geração
        new_family = {"m5": "m6i", "c5": "c6i", "r5": "r6i"}[family]
        target = f"{new_family}.{size}"
        recommendations.append({
            "AccountId": f"123456789{i:03d}",
            "CurrentInstance": {
                "InstanceId": f"i-mock{i:04d}",
                "InstanceType": instance,
                "MonthlyCost": f"{current_cost:.2f}",
            },
            "RightsizingType": "Modify",
            "ModifyRecommendation": {
                "TargetInstances": [{
                    "InstanceType": target,
                    "EstimatedMonthlyCost": f"{current_cost * 0.6:.2f}",
                    "EstimatedMonthlySavings": f"{current_cost * 0.4:.2f}",
                }],
                "TargetInstanceType": target,
            },
        })

    return {
        "RightsizingRecommendations": recommendations,
        "NextPageToken": None,
    }


def _aws_savings_plans(request: dict[str, Any]) -> dict[str, Any]:
    """Emula AWS Cost Explorer GetSavingsPlansPurchaseRecommendation."""
    rng = _seed_for(request)
    _simulate_latency(rng, base_ms=400)

    monthly_savings = rng.uniform(500, 5000)
    return {
        "SavingsPlansRecommendations": [{
            "AccountScope": "ACCOUNT",
            "SavingsPlansType": "COMPUTE_SP",
            "TermInYears": "ONE_YEAR",
            "PaymentOption": "NO_UPFRONT",
            "LookbackPeriodInDays": "THIRTY_DAYS",
            "SavingsPlansOptions": [{
                "EstimatedMonthlySavingsAmount": f"{monthly_savings:.2f}",
                "EstimatedSavingsPercentage": f"{rng.uniform(20, 35):.2f}",
                "HourlyCommitment": f"{rng.uniform(0.5, 10):.4f}",
                "UpfrontCost": "0.00",
                "EstimatedROI": f"{rng.uniform(2, 8):.2f}",
            }],
        }],
    }


def _aws_describe_volumes(request: dict[str, Any]) -> dict[str, Any]:
    """Emula EC2 DescribeVolumes para volumes não anexados."""
    rng = _seed_for(request)
    _simulate_latency(rng, base_ms=250)

    n_volumes = rng.randint(0, 5)
    volumes = []
    for i in range(n_volumes):
        volumes.append({
            "VolumeId": f"vol-mock{i:04d}{rng.randint(0, 9):08x}",
            "Size": rng.choice([20, 50, 100, 500, 1000]),
            "VolumeType": rng.choice(["gp2", "gp3", "io1", "st1"]),
            "State": "available",
            "CreateTime": datetime(2026, 1, rng.randint(1, 28), tzinfo=timezone.utc).isoformat(),
        })

    return {"Volumes": volumes}


def _aws_describe_addresses(request: dict[str, Any]) -> dict[str, Any]:
    """Emula EC2 DescribeAddresses para Elastic IPs não associados."""
    rng = _seed_for(request)
    _simulate_latency(rng, base_ms=200)

    n_eips = rng.randint(0, 3)
    addresses = []
    for i in range(n_eips):
        # EIP sem AssociationId = ocioso
        addresses.append({
            "PublicIp": f"54.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}",
            "AllocationId": f"eipalloc-mock{i:04d}{rng.randint(0, 9):08x}",
            "AssociationId": None,  # não associado = ocioso
        })

    return {"Addresses": addresses}


# ─────────────────────────────────────────────────────────────────────────
# Azure Advisor mocks
# ─────────────────────────────────────────────────────────────────────────


def _azure_advisor_recommendations(request: dict[str, Any]) -> dict[str, Any]:
    """Emula Azure Advisor recommendations.list()."""
    rng = _seed_for(request)
    _seed_for({"category": "cost"})  # só geramos cost recs
    _simulate_latency(rng, base_ms=450)

    n_recs = rng.randint(2, 7)
    recommendations = []
    for i in range(n_recs):
        impact = rng.choice(["High", "Medium", "Low"])
        category = "Cost"
        recs_pool = [
            ("Right-size underutilized VMs", "Resize or shut down underutilized virtual machines to save costs"),
            ("Delete unused public IPs", "Remove public IP addresses not associated with any resource"),
            ("Use Reserved Instances", "Save up to 72% with reserved instance commitments"),
            ("Optimize storage tier", "Move infrequently accessed blobs to cool/archive tier"),
            ("Right-size PostgreSQL DB", "Downsize DTU configuration based on actual usage"),
        ]
        problem, solution = rng.choice(recs_pool)
        rec_id = f"/subscriptions/mock/sub{i}/providers/Microsoft.Advisor/recommendations/mock-{i:04d}"
        recommendations.append({
            "id": rec_id,
            "name": f"recommendation-{i}",
            "type": "Microsoft.Advisor/recommendations",
            "category": category,
            "impact": impact,
            "impactedField": "Microsoft.Compute/virtualMachines",
            "impactedValue": f"/subscriptions/mock/resourceGroups/rg{i}/providers/Microsoft.Compute/virtualMachines/vm{i}",
            "shortDescription": {
                "problem": problem,
                "solution": solution,
            },
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "value": recommendations,
        "nextLink": None,
    }


# ─────────────────────────────────────────────────────────────────────────
# GCP Recommender mocks
# ─────────────────────────────────────────────────────────────────────────


def _gcp_recommendations(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Emula GCP Recommender API listRecommendations()."""
    rng = _seed_for(request)
    _simulate_latency(rng, base_ms=550)

    parent = request.get("parent", "")
    if "MachineTypeRecommender" in parent:
        n = rng.randint(1, 5)
        return [
            {
                "name": f"projects/mock/locations/global/recommenders/MachineTypeRecommender/recommendations/r{i}",
                "description": f"Right-size VM{i}: reduce from n1-standard-4 to e2-standard-2",
                "primaryImpact": {
                    "category": "COST",
                    "costProjection": {
                        "cost": {
                            "units": f"{rng.randint(50, 500)}",  # USD/mês
                            "currencyCode": "USD",
                        },
                        "duration": "P30D",
                    },
                },
                "stateInfo": {"state": "ACTIVE"},
            }
            for i in range(n)
        ]
    elif "IdleResourceRecommender" in parent:
        n = rng.randint(0, 4)
        return [
            {
                "name": f"projects/mock/locations/global/recommenders/IdleResourceRecommender/recommendations/i{i}",
                "description": f"Idle disk {i}: no recent I/O",
                "primaryImpact": {
                    "category": "COST",
                    "costProjection": {"cost": {"units": "10", "currencyCode": "USD"}, "duration": "P30D"},
                },
            }
            for i in range(n)
        ]
    elif "IAM" in parent:
        return [
            {
                "name": f"projects/mock/recommenders/iam.policy.Recommender/recommendations/iam{i}",
                "description": f"Service account {i} has excessive role",
                "primaryImpact": {"category": "SECURITY"},
            }
            for i in range(rng.randint(0, 3))
        ]
    return []


# ─────────────────────────────────────────────────────────────────────────
# HTTP handler
# ─────────────────────────────────────────────────────────────────────────


class MockCloudHandler(BaseHTTPRequestHandler):
    """HTTP handler que despacha para os mocks."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Silencia logs do BaseHTTPServer (mantém stdout limpo)
        pass

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body, default=str).encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        try:
            # Parse path
            path = self.path.split("?")[0]

            # Read body se houver
            content_length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            request_data: dict[str, Any] = json.loads(body.decode("utf-8") or "{}")

            # Dispatch por path
            if path == "/aws/ce/cost-and-usage":
                self._send_json(200, _aws_cost_and_usage(request_data))
            elif path == "/aws/ce/rightsizing":
                self._send_json(200, _aws_rightsizing(request_data))
            elif path == "/aws/ce/savings-plans":
                self._send_json(200, _aws_savings_plans(request_data))
            elif path == "/aws/ec2/volumes":
                self._send_json(200, _aws_describe_volumes(request_data))
            elif path == "/aws/ec2/elastic-ips":
                self._send_json(200, _aws_describe_addresses(request_data))
            elif path == "/azure/advisor/recommendations":
                self._send_json(200, _azure_advisor_recommendations(request_data))
            elif path.startswith("/gcp/recommender/"):
                self._send_json(200, _gcp_recommendations(request_data))
            elif path == "/health":
                self._send_json(200, {"status": "ok", "type": "mock_cloud_server"})
            else:
                self._send_json(404, {"error": "not_found", "path": path})

        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mock Cloud API server para testes locais (AWS/Azure/GCP)"
    )
    parser.add_argument(
        "--port", type=int, default=8888,
        help="Porta do servidor (default: 8888)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host para bind (default: 127.0.0.1 — só local)",
    )
    parser.add_argument(
        "--latency-ms", type=int, default=400,
        help="Latência base simulada em ms (default: 400)",
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockCloudHandler)
    print(f"[OK] Mock Cloud API server escutando em http://{args.host}:{args.port}")
    print(f"     Endpoints disponíveis:")
    print(f"       GET  /health")
    print(f"       POST /aws/ce/cost-and-usage")
    print(f"       POST /aws/ce/rightsizing")
    print(f"       POST /aws/ce/savings-plans")
    print(f"       POST /aws/ec2/volumes")
    print(f"       POST /aws/ec2/elastic-ips")
    print(f"       POST /azure/advisor/recommendations")
    print(f"       POST /gcp/recommender/<recommender_id>")
    print()
    print(f"     Configure o client: AWS_COST_ENDPOINT=http://localhost:{args.port}")
    print(f"     Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[OK] Server stopped.")
        server.shutdown()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())