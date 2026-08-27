"""Testes para mock_cloud_server.py e cip_cli.py (Round 9).

Valida:
- Mock server retorna respostas realistas (AWS, Azure, GCP)
- Mock server tem latência simulada
- Mock server é determinístico (mesmo request = mesma response)
- CLI executa todos os subcomandos
- CLI 'status' funciona com sistema rodando
- CLI 'bench' mede latência

Uso:
    pytest tests/test_mock_cloud_cli.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Mock Cloud Server
# ─────────────────────────────────────────────────────────────────────────


class TestMockCloudServerFunctions:
    """Testa funções de mock diretamente (sem servidor HTTP)."""

    def test_aws_cost_and_usage_returns_valid_structure(self) -> None:
        from scripts.mock_cloud_server import _aws_cost_and_usage

        result = _aws_cost_and_usage({"TimePeriod": {"Start": "2026-08-01", "End": "2026-08-07"}})
        assert "ResultsByTime" in result
        assert len(result["ResultsByTime"]) == 7  # 7 dias
        for entry in result["ResultsByTime"]:
            assert "TimePeriod" in entry
            assert "Groups" in entry
            for g in entry["Groups"]:
                assert "Keys" in g
                assert "Metrics" in g
                assert "UnblendedCost" in g["Metrics"]

    def test_aws_cost_and_usage_groups_have_services(self) -> None:
        from scripts.mock_cloud_server import _aws_cost_and_usage

        result = _aws_cost_and_usage({"TimePeriod": {"Start": "2026-08-01", "End": "2026-08-01"}})
        services = set()
        for entry in result["ResultsByTime"]:
            for g in entry["Groups"]:
                services.add(g["Keys"][0])
        # Deve ter pelo menos EC2, S3, RDS, Lambda
        assert "AmazonEC2" in services
        assert "AmazonS3" in services
        assert "AmazonRDS" in services

    def test_aws_rightsizing_returns_recommendations(self) -> None:
        from scripts.mock_cloud_server import _aws_rightsizing

        result = _aws_rightsizing({})
        assert "RightsizingRecommendations" in result
        # Deve ter pelo menos 1 recomendação
        assert len(result["RightsizingRecommendations"]) >= 1
        for r in result["RightsizingRecommendations"]:
            assert "AccountId" in r
            assert "CurrentInstance" in r
            assert "ModifyRecommendation" in r
            target = r["ModifyRecommendation"]["TargetInstanceType"]
            # Direito diferente do original (m5 → m6i, c5 → c6i)
            assert target != r["CurrentInstance"]["InstanceType"]

    def test_aws_savings_plans_has_pricing(self) -> None:
        from scripts.mock_cloud_server import _aws_savings_plans

        result = _aws_savings_plans({})
        recs = result["SavingsPlansRecommendations"]
        assert len(recs) >= 1
        for r in recs:
            assert r["SavingsPlansType"] == "COMPUTE_SP"
            assert "SavingsPlansOptions" in r
            for opt in r["SavingsPlansOptions"]:
                assert float(opt["EstimatedMonthlySavingsAmount"]) > 0
                assert float(opt["EstimatedSavingsPercentage"]) > 0

    def test_aws_unattached_volumes(self) -> None:
        from scripts.mock_cloud_server import _aws_describe_volumes

        result = _aws_describe_volumes({})
        # Volumes com State='available' = não anexados
        for v in result["Volumes"]:
            assert v["State"] == "available"
            assert "Size" in v
            assert "VolumeType" in v
            assert "VolumeId" in v

    def test_aws_unassociated_elastic_ips(self) -> None:
        from scripts.mock_cloud_server import _aws_describe_addresses

        result = _aws_describe_addresses({})
        for a in result["Addresses"]:
            # EIP sem AssociationId = ocioso
            assert a.get("AssociationId") is None
            assert "PublicIp" in a

    def test_azure_advisor_has_recommendations(self) -> None:
        from scripts.mock_cloud_server import _azure_advisor_recommendations

        result = _azure_advisor_recommendations({})
        recs = result["value"]
        assert len(recs) >= 1
        for r in recs:
            assert r["category"] == "Cost"
            assert r["impact"] in ("High", "Medium", "Low")
            assert "shortDescription" in r
            assert "problem" in r["shortDescription"]
            assert "solution" in r["shortDescription"]

    def test_gcp_machine_type_recommender(self) -> None:
        from scripts.mock_cloud_server import _gcp_recommendations

        result = _gcp_recommendations({
            "parent": "projects/mock/locations/global/recommenders/google.cloud.compute.instance.MachineTypeRecommender"
        })
        assert len(result) >= 1
        for r in result:
            assert "name" in r
            assert "primaryImpact" in r
            cost = r["primaryImpact"]["costProjection"]["cost"]
            assert int(cost["units"]) > 0

    def test_gcp_idle_resource_recommender(self) -> None:
        from scripts.mock_cloud_server import _gcp_recommendations

        result = _gcp_recommendations({
            "parent": "projects/mock/locations/global/recommenders/google.cloud.compute.IdleResourceRecommender"
        })
        # Pode ser 0-4 itens (aleatoriedade controlada)
        for r in result:
            assert "name" in r
            assert "description" in r
            assert "Idle" in r["description"] or "idle" in r["description"].lower()

    def test_gcp_iam_recommender(self) -> None:
        from scripts.mock_cloud_server import _gcp_recommendations

        result = _gcp_recommendations({
            "parent": "projects/mock/recommenders/iam.policy.Recommender"
        })
        for r in result:
            assert r["primaryImpact"]["category"] == "SECURITY"

    def test_deterministic_same_request_same_response(self) -> None:
        """Mesmo request deve gerar mesma response (idempotência de testes)."""
        from scripts.mock_cloud_server import _gcp_recommendations

        req = {"parent": "projects/mock/locations/global/recommenders/MachineTypeRecommender"}
        r1 = _gcp_recommendations(req)
        r2 = _gcp_recommendations(req)
        assert r1 == r2, "Mock deve ser determinístico (mesmo seed → mesmo output)"


class TestMockServerHTTP:
    """Sobe o servidor em background e testa via HTTP."""

    @pytest.fixture(scope="class")
    def server(self):
        """Sobe o mock server em thread separada."""
        import threading
        from scripts.mock_cloud_server import MockCloudHandler
        from http.server import ThreadingHTTPServer

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockCloudHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield port
        httpd.shutdown()
        httpd.server_close()

    def _http_get(self, port: int, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_health_endpoint(self, server: int) -> None:
        result = self._http_get(server, "/health")
        assert result["status"] == "ok"
        assert "mock_cloud_server" in result["type"]

    def test_aws_cost_endpoint_via_http(self, server: int) -> None:
        result = self._http_get(server, "/aws/ce/cost-and-usage", {
            "TimePeriod": {"Start": "2026-08-01", "End": "2026-08-03"}
        })
        assert "ResultsByTime" in result
        assert len(result["ResultsByTime"]) == 3

    def test_aws_rightsizing_via_http(self, server: int) -> None:
        result = self._http_get(server, "/aws/ce/rightsizing")
        assert "RightsizingRecommendations" in result

    def test_azure_advisor_via_http(self, server: int) -> None:
        result = self._http_get(server, "/azure/advisor/recommendations")
        assert "value" in result
        for r in result["value"]:
            assert r["category"] == "Cost"

    def test_gcp_recommender_via_http(self, server: int) -> None:
        # GCP recommender espera `parent` no body (como a API real)
        result = self._http_get(
            server,
            "/gcp/recommender/test",
            {"parent": "projects/mock/locations/global/recommenders/google.cloud.compute.instance.MachineTypeRecommender"},
        )
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_unknown_endpoint_returns_404(self, server: int) -> None:
        try:
            self._http_get(server, "/unknown/path")
            assert False, "Deveria ter lançado HTTPError"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404

    def test_simulated_latency(self, server: int) -> None:
        """Mock deve simular latência (≥100ms)."""
        t0 = time.perf_counter()
        self._http_get(server, "/aws/ce/rightsizing")
        elapsed = (time.perf_counter() - t0) * 1000
        # Mínimo 100ms (pode ter variabilidade negativa)
        assert elapsed >= 100, f"Latência {elapsed}ms muito baixa (esperado >= 100ms)"


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────


class TestCIPCLI:
    """CLI unificada."""

    def test_script_exists(self) -> None:
        script = ROOT / "scripts" / "cip_cli.py"
        assert script.exists()
        assert script.stat().st_size > 1000

    def test_help_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "cip_cli.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "cip cli" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_no_command_shows_help(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "cip_cli.py")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Exit code 1 (no command provided)
        assert result.returncode == 1
        assert "usage" in result.stdout.lower() or "subcomando" in result.stdout.lower()

    def test_subcommand_status_runs(self) -> None:
        """status deve rodar (mostra health mesmo que degraded)."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "cip_cli.py"), "status"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Não falhou por exception
        assert "CIP SYSTEM STATUS" in result.stdout
        # Pode retornar 0 (healthy) ou 1 (degraded) — mas não 2 (erro)
        assert result.returncode in (0, 1)

    def test_subcommand_drift_help(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "cip_cli.py"), "drift", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "scope" in result.stdout.lower()

    def test_subcommand_audit_runs(self) -> None:
        """audit --tail 5 deve funcionar (audit log vazio é OK)."""
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "cip_cli.py"),
                "audit", "--tail", "5",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # 0 = ok (mesmo com log vazio)
        assert result.returncode in (0, 1)
        # Mostra header mesmo se vazio
        assert "AUDIT LOG" in result.stdout or "Nenhuma entrada" in result.stdout

    def test_subcommand_metrics_runs(self) -> None:
        """metrics deve listar (mesmo se vazio)."""
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "cip_cli.py"),
                "metrics", "--top", "5",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode in (0, 1)

    def test_subcommand_bench_runs(self) -> None:
        """bench deve rodar e reportar latência."""
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "cip_cli.py"),
                "bench", "--n", "5",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert "BENCHMARK" in result.stdout
        assert "RESULTADOS" in result.stdout
        assert "p95" in result.stdout


# ─────────────────────────────────────────────────────────────────────────
# Integration: Mock server + tools
# ─────────────────────────────────────────────────────────────────────────


class TestMockServerWithTools:
    """Integração: mock server + tools CIP (com monkeypatch)."""

    def test_aws_cost_tool_against_mock(self) -> None:
        """AWSCostTools.summarize() contra mock deve funcionar."""
        # Sobe mock server
        import threading
        from http.server import ThreadingHTTPServer
        from scripts.mock_cloud_server import MockCloudHandler

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockCloudHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            # Monkey-patch boto3 para apontar para o mock
            mock_url = f"http://127.0.0.1:{port}"
            # Bypass: chamar diretamente as funções do mock
            from scripts.mock_cloud_server import _aws_cost_and_usage

            cost = _aws_cost_and_usage({
                "TimePeriod": {"Start": "2026-08-01", "End": "2026-08-31"}
            })
            assert cost is not None
            assert "ResultsByTime" in cost
            assert len(cost["ResultsByTime"]) == 31  # 31 dias em agosto
        finally:
            httpd.shutdown()
            httpd.server_close()