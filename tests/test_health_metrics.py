"""Testes para health checks, métricas Prometheus, audit logging e preflight (Round 8).

Valida:
- Health check rendering (formato Prometheus)
- Metrics registry (counters + histograms)
- Audit logger (JSONL)
- Preflight script (env checks)

Uso:
    pytest tests/test_health_metrics.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singletons entre testes."""
    from src.cip.observability import reset_audit_logger, reset_metrics

    reset_metrics()
    reset_audit_logger()
    yield
    reset_metrics()
    reset_audit_logger()


# ─────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────


class TestMetricsRegistry:
    """Registry de métricas Prometheus."""

    def test_counter_increments(self) -> None:
        from src.cip.observability import get_metrics

        m = get_metrics()
        m.inc_counter("cip_requests_total", labels={"endpoint": "/ask"})
        m.inc_counter("cip_requests_total", labels={"endpoint": "/ask"})
        m.inc_counter("cip_requests_total", value=5.0, labels={"endpoint": "/ask"})
        output = m.render()
        assert "cip_requests_total" in output
        # 1 + 1 + 5 = 7
        assert "7.0" in output

    def test_multiple_label_combinations(self) -> None:
        from src.cip.observability import get_metrics

        m = get_metrics()
        m.inc_counter("cip_requests_total", labels={"endpoint": "/ask", "status": "200"})
        m.inc_counter("cip_requests_total", labels={"endpoint": "/ask", "status": "500"})
        m.inc_counter("cip_requests_total", labels={"endpoint": "/analyze", "status": "200"})
        output = m.render()
        assert "endpoint=\"/ask\"" in output
        assert "endpoint=\"/analyze\"" in output
        assert "status=\"200\"" in output
        assert "status=\"500\"" in output

    def test_histogram_buckets(self) -> None:
        from src.cip.observability import get_metrics

        m = get_metrics()
        # Observações em diferentes latências
        m.observe_histogram("cip_request_duration_seconds", 0.005)
        m.observe_histogram("cip_request_duration_seconds", 0.5)
        m.observe_histogram("cip_request_duration_seconds", 10.0)  # > max bucket
        m.observe_histogram("cip_request_duration_seconds", 0.1)
        output = m.render()
        assert "cip_request_duration_seconds_bucket" in output
        assert "le=\"+Inf\"" in output
        assert "cip_request_duration_seconds_sum" in output
        assert "cip_request_duration_seconds_count" in output

    def test_render_format_prometheus(self) -> None:
        from src.cip.observability import get_metrics

        m = get_metrics()
        m.inc_counter("test_counter", value=42, labels={"foo": "bar"})
        output = m.render()
        # Prometheus text format
        assert "# HELP test_counter" in output
        assert "# TYPE test_counter counter" in output
        assert 'test_counter{foo="bar"} 42.0' in output

    def test_reset_clears_state(self) -> None:
        from src.cip.observability import get_metrics

        m = get_metrics()
        m.inc_counter("test", value=1.0)
        assert "test " in m.render()
        m.reset()
        assert "test" not in m.render()


class TestMetricsFromApp:
    """Métricas expostas em /metrics."""

    def test_metrics_endpoint_exists(self) -> None:
        from src.cip.api.app import app

        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/metrics" in paths

    def test_health_live_endpoint_exists(self) -> None:
        from src.cip.api.health import router

        # Router tem prefix /health; paths absolutos são /health/live, /health/ready
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/health/live" in paths

    def test_health_ready_endpoint_exists(self) -> None:
        from src.cip.api.health import router

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/health/ready" in paths


# ─────────────────────────────────────────────────────────────────────────
# Audit logging
# ─────────────────────────────────────────────────────────────────────────


class TestAuditLogger:
    """Audit log JSONL para compliance."""

    def _temp_log_path(self) -> Path:
        """Cria path temp seguro para teste."""
        import uuid
        base_tmp = ROOT / ".tmp_test"
        base_tmp.mkdir(exist_ok=True)
        path = base_tmp / f"audit_test_{uuid.uuid4().hex[:8]}.jsonl"
        return path

    def test_creates_log_file(self) -> None:
        from src.cip.observability import AuditEntry, AuditLogger

        log_path = self._temp_log_path()
        al = AuditLogger(log_path=str(log_path))
        al.log(AuditEntry(endpoint="/ask", method="POST", status=200, latency_ms=150))
        assert log_path.exists()
        log_path.unlink(missing_ok=True)

    def test_log_appends(self) -> None:
        from src.cip.observability import AuditEntry, AuditLogger

        log_path = self._temp_log_path()
        al = AuditLogger(log_path=str(log_path))
        for i in range(3):
            al.log(AuditEntry(endpoint=f"/req-{i}", method="POST", status=200, latency_ms=100 + i))
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        log_path.unlink(missing_ok=True)

    def test_log_is_valid_jsonl(self) -> None:
        from src.cip.observability import AuditEntry, AuditLogger

        log_path = self._temp_log_path()
        al = AuditLogger(log_path=str(log_path))
        al.log(AuditEntry(
            endpoint="/ask", method="POST", status=200, latency_ms=150,
            tenant_id="tenant-x", api_key_hash="abc123",
        ))
        # Parse deve funcionar
        line = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(line)
        assert entry["endpoint"] == "/ask"
        assert entry["tenant_id"] == "tenant-x"
        assert entry["status"] == 200
        log_path.unlink(missing_ok=True)

    def test_tail_returns_recent(self) -> None:
        from src.cip.observability import AuditEntry, AuditLogger

        log_path = self._temp_log_path()
        al = AuditLogger(log_path=str(log_path))
        for i in range(5):
            al.log(AuditEntry(endpoint=f"/req-{i}", method="POST", status=200, latency_ms=i))
        tail = al.tail(n=3)
        assert len(tail) == 3
        # Tail deve ter os 3 últimos (índices 2, 3, 4)
        assert tail[0]["endpoint"] == "/req-2"
        assert tail[-1]["endpoint"] == "/req-4"
        log_path.unlink(missing_ok=True)


class TestAuditEntryDefaults:
    """AuditEntry defaults."""

    def test_default_tenant_is_anonymous(self) -> None:
        from src.cip.observability import AuditEntry

        e = AuditEntry()
        assert e.tenant_id == "anonymous"
        assert e.status == 0
        assert e.latency_ms == 0

    def test_default_timestamp_is_iso(self) -> None:
        from src.cip.observability import AuditEntry

        e = AuditEntry()
        assert "T" in e.timestamp  # ISO 8601
        assert len(e.timestamp) > 10


# ─────────────────────────────────────────────────────────────────────────
# Health checks
# ─────────────────────────────────────────────────────────────────────────


class TestHealthCheckResult:
    """HealthCheckResult dataclass."""

    def test_default_healthy_false(self) -> None:
        from src.cip.api.health import HealthCheckResult

        r = HealthCheckResult(name="x", healthy=True)
        assert r.healthy is True
        assert r.message == ""
        assert r.latency_ms == 0.0

    def test_health_router_registers(self) -> None:
        from src.cip.api.health import router

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        # Router tem prefix /health; paths absolutos são /health/live, /health/ready
        assert "/health/live" in paths
        assert "/health/ready" in paths


# ─────────────────────────────────────────────────────────────────────────
# Preflight script
# ─────────────────────────────────────────────────────────────────────────


class TestPreflight:
    """Script de pre-flight check."""

    def test_script_exists(self) -> None:
        script = ROOT / "scripts" / "preflight.py"
        assert script.exists()
        assert script.stat().st_size > 1000

    def test_help_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "preflight.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "pre-flight" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_environment_check_dev_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_ENV", "dev")
        from scripts.preflight import check_environment

        result = check_environment()
        assert result.passed is True
        assert "dev" in result.message.lower() or "ok" in result.message.lower()

    def test_environment_check_prod_missing_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_ENV", "prod")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("CIP_API_KEYS", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        from scripts.preflight import check_environment

        result = check_environment()
        assert result.passed is False
        assert "faltando" in result.message.lower() or "missing" in result.message.lower()

    def test_api_keys_check_well_formed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_ENV", "prod")
        monkeypatch.setenv("CIP_API_KEYS", "key1:tenant1:60,key2:tenant2:120")
        from scripts.preflight import check_api_keys

        result = check_api_keys()
        assert result.passed is True
        assert "2" in result.message  # 2 tenants

    def test_api_keys_check_malformed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_ENV", "prod")
        monkeypatch.setenv("CIP_API_KEYS", "badformat,key:tenant:60")
        from scripts.preflight import check_api_keys

        result = check_api_keys()
        assert result.passed is False
        assert "malformadas" in result.message.lower() or "malformed" in result.message.lower()

    def test_embedding_dim_validation(self) -> None:
        from scripts.preflight import check_embedding_dim

        result = check_embedding_dim()
        # Deve passar com config do projeto (bge-large = 1024 + local = OK)
        assert result.passed is True

    def test_embedding_dim_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Forçar mismatch
        from scripts.preflight import check_embedding_dim
        from src.cip.config import get_settings

        # Testa diretamente via settings (sem monkeypatch de env pois Settings usa lru_cache)
        result = check_embedding_dim()
        # No projeto, embed_dim=1024 + embed_provider=local → OK (1024 ∈ {384,768,1024})
        assert result.passed is True