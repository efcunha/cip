"""Tests do endpoint POST /consult (Round 22+ Phase 3).

Endpoint consumido por outros chats (cloudpilot) via HTTP.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestConsultEndpointStructure:
    """Estrutura do módulo consult.py (não precisa de infra)."""

    def test_consult_module_exists(self) -> None:
        f = ROOT / "src" / "cip" / "api" / "consult.py"
        assert f.exists()
        assert f.stat().st_size > 3000

    def test_consult_module_is_valid_python(self) -> None:
        f = ROOT / "src" / "cip" / "api" / "consult.py"
        code = f.read_text(encoding="utf-8")
        ast.parse(code)

    def test_consult_registers_router_in_app(self) -> None:
        app_py = ROOT / "src" / "cip" / "api" / "app.py"
        code = app_py.read_text(encoding="utf-8")
        assert "from cip.api.consult import router" in code
        assert "app.include_router(consult_router)" in code

    def test_consult_endpoint_path(self) -> None:
        f = ROOT / "src" / "cip" / "api" / "consult.py"
        code = f.read_text(encoding="utf-8")
        assert '"/consult"' in code
        assert "@router.post" in code

    def test_consult_returns_cipragresult_shape(self) -> None:
        """Output deve casar com CipRagResult do cloudpilot."""
        f = ROOT / "src" / "cip" / "api" / "consult.py"
        code = f.read_text(encoding="utf-8")
        # Schema fields
        for field in ("answer", "sources", "has_grounding", "refusal_reason", "run_id", "latency_ms"):
            assert field in code, f"Campo {field} faltando no ConsultOut"

    def test_consult_source_has_provenance(self) -> None:
        """Cada source tem provenance (doc_id, version, content_preview, etc.)."""
        f = ROOT / "src" / "cip" / "api" / "consult.py"
        code = f.read_text(encoding="utf-8")
        for field in (
            "doc_id", "source_version", "timestamp", "content_preview",
            "workspace_id", "is_global", "source", "canonical_url",
            "quarantined", "marked",
        ):
            assert field in code, f"Campo de provenance {field} faltando"

    def test_consult_supports_filters(self) -> None:
        """Suporta filtros cloud, service, category, run_id (audit)."""
        f = ROOT / "src" / "cip" / "api" / "consult.py"
        code = f.read_text(encoding="utf-8")
        for param in ("cloud", "service", "category", "run_id", "prompt_hash"):
            assert param in code, f"Filtro {param} faltando em ConsultReq"

    def test_consult_emits_metrics_and_log(self) -> None:
        f = ROOT / "src" / "cip" / "api" / "consult.py"
        code = f.read_text(encoding="utf-8")
        assert "observe_chat_latency" in code
        assert "log.info" in code
        assert "consult_completed" in code

    def test_source_dataclass_has_provenance_fields(self) -> None:
        """O Source dataclass (rag/engine.py) foi estendido com provenance."""
        f = ROOT / "src" / "cip" / "rag" / "engine.py"
        code = f.read_text(encoding="utf-8")
        for field in (
            "doc_id", "source_version", "timestamp", "content_preview",
            "workspace_id", "is_global", "canonical_url", "quarantined", "marked",
        ):
            assert field in code, f"Source.{field} faltando em rag/engine.py"


class TestConsultEndpointContract:
    """Contrato HTTP — só valida schema, sem subir servidor."""

    def test_consult_request_schema_fields(self) -> None:
        """ConsultReq tem todos os campos do cloudpilot + extras."""
        f = ROOT / "src" / "cip" / "api" / "consult.py"
        code = f.read_text(encoding="utf-8")
        for field in (
            "question", "cloud", "service", "category",
            "top_k", "min_score", "run_id", "prompt_hash", "include_global",
        ):
            assert field in code, f"ConsultReq.{field} faltando"

    def test_consult_response_status_codes(self) -> None:
        """Doc do endpoint explica 200 OK + 500 engine_error."""
        f = ROOT / "src" / "cip" / "api" / "consult.py"
        code = f.read_text(encoding="utf-8")
        assert "response_model=ConsultOut" in code or "ConsultOut" in code
        # HTTPException usado para erros
        assert "HTTPException" in code


class TestCloudPilotHttpClient:
    """Estrutura do CipHttpClient (D:\\cloudpilot-deploy)."""

    def test_file_exists(self) -> None:
        f = Path(r"D:\cloudpilot-deploy\backend\app\services\ai\cip_http_client.py")
        if not f.exists():
            pytest.skip("CipHttpClient não existe em D:\\cloudpilot-deploy — rode fora do sandbox")
        assert f.stat().st_size > 3000

    def test_module_is_valid_python(self) -> None:
        f = Path(r"D:\cloudpilot-deploy\backend\app\services\ai\cip_http_client.py")
        if not f.exists():
            pytest.skip("CipHttpClient não existe em D:\\cloudpilot-deploy")
        ast.parse(f.read_text(encoding="utf-8"))

    def test_client_has_is_http_mode_enabled(self) -> None:
        f = Path(r"D:\cloudpilot-deploy\backend\app\services\ai\cip_http_client.py")
        if not f.exists():
            pytest.skip("CipHttpClient não existe em D:\\cloudpilot-deploy")
        code = f.read_text(encoding="utf-8")
        assert "is_http_mode_enabled" in code
        assert "CIP_API_URL" in code
        assert "CIP_API_TOKEN" in code

    def test_client_returns_cipragresult(self) -> None:
        f = Path(r"D:\cloudpilot-deploy\backend\app\services\ai\cip_http_client.py")
        if not f.exists():
            pytest.skip("CipHttpClient não existe em D:\\cloudpilot-deploy")
        code = f.read_text(encoding="utf-8")
        assert "class CipRagResult" in code
        assert "answer" in code
        assert "sources" in code
        assert "has_grounding" in code
        assert "refusal_reason" in code

    def test_client_uses_drop_in_pattern(self) -> None:
        """consult_official_cloud_knowledge decide HTTP vs in-process automaticamente."""
        f = Path(r"D:\cloudpilot-deploy\backend\app\services\ai\cip_http_client.py")
        if not f.exists():
            pytest.skip("CipHttpClient não existe em D:\\cloudpilot-deploy")
        code = f.read_text(encoding="utf-8")
        assert "consult_official_cloud_knowledge" in code
        # Fallback para cip_client (in-process)
        assert "cip_client" in code

    def test_cloudpilot_settings_have_cip_api_fields(self) -> None:
        """backend/app/config.py tem CIP_API_URL e CIP_API_TOKEN."""
        f = Path(r"D:\cloudpilot-deploy\backend\app\config.py")
        if not f.exists():
            pytest.skip("config.py não existe em D:\\cloudpilot-deploy")
        code = f.read_text(encoding="utf-8")
        assert "CIP_API_URL" in code
        assert "CIP_API_TOKEN" in code
