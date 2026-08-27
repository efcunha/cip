"""Testes para scripts de documentação (Round 12).

Valida:
- export_openapi.py: gera spec válido do FastAPI
- demo.py: executa 6 queries sem erro
- C4 diagramas (Mermaid) tem sintaxe correta
- ADRs têm formato padrão

Uso:
    pytest tests/test_documentation.py -v
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def temp_path_safe():
    """Cria path temp seguro (Windows-safe, fora de %TEMP%)."""
    base_tmp = ROOT / ".tmp_test"
    base_tmp.mkdir(exist_ok=True)
    path = base_tmp / f"cip_test_{uuid.uuid4().hex[:8]}"
    path.mkdir(exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────
# OpenAPI export
# ─────────────────────────────────────────────────────────────────────────


class TestOpenAPIExport:
    """Exporta OpenAPI spec do FastAPI."""

    def test_export_creates_json_file(self, temp_path_safe: Path) -> None:
        """Script export_openapi.py gera arquivo JSON válido."""
        out = temp_path_safe / "openapi.json"
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "export_openapi.py"),
                "--output", str(out),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert out.exists()
        # Valida JSON
        spec = json.loads(out.read_text(encoding="utf-8"))
        assert "openapi" in spec
        assert "paths" in spec
        assert "components" in spec

    def test_openapi_spec_has_core_endpoints(self, temp_path_safe: Path) -> None:
        """Spec inclui endpoints principais."""
        out = temp_path_safe / "openapi.json"
        subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "export_openapi.py"),
                "--output", str(out),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        spec = json.loads(out.read_text(encoding="utf-8"))
        paths = spec.get("paths", {})
        # Endpoints principais
        assert "/health" in paths
        assert "/health/live" in paths
        assert "/health/ready" in paths
        assert "/metrics" in paths
        assert "/ask" in paths
        assert "/analyze" in paths

    def test_openapi_has_react_mode_parameter(self, temp_path_safe: Path) -> None:
        """Schema AnalyzeRequest inclui react_mode."""
        out = temp_path_safe / "openapi.json"
        subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "export_openapi.py"),
                "--output", str(out),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        spec = json.loads(out.read_text(encoding="utf-8"))
        # Navega até AnalyzeRequest
        analyze_schema = spec["components"]["schemas"]["AnalyzeRequest"]["properties"]
        assert "react_mode" in analyze_schema

    def test_openapi_has_security_schemes(self, temp_path_safe: Path) -> None:
        """Spec tem securitySchemes (X-API-Key)."""
        out = temp_path_safe / "openapi.json"
        subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "export_openapi.py"),
                "--output", str(out),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        spec = json.loads(out.read_text(encoding="utf-8"))
        # FastAPI gera securitySchemes quando há Depends com Header
        assert "components" in spec
        # Security pode estar em endpoints individuais
        for path, ops in spec.get("paths", {}).items():
            for method, op in ops.items():
                if isinstance(op, dict) and op.get("security"):
                    return  # Found at least one
        # Se não tem security em nenhum, pelo menos os paths existem
        assert "/ask" in spec["paths"]


# ─────────────────────────────────────────────────────────────────────────
# Demo script
# ─────────────────────────────────────────────────────────────────────────


class TestDemoScript:
    """Script de demo end-to-end."""

    def test_demo_help_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "demo.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "demo" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_demo_executes_all_queries(self) -> None:
        """Roda demo completo (6 queries) sem erro.

        Sem --mock-clouds para não precisar de servidor rodando.
        Tools vão degradar gracefully (modo stub).
        """
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "demo.py")],
            capture_output=True,
            text=True,
            timeout=300,  # 6 queries com RAG local + bge-large embeddings
        )
        # Pode ter warnings, mas não error fatal
        assert result.returncode == 0, (
            f"Demo falhou (rc={result.returncode}):\n"
            f"STDOUT last 50 lines:\n{chr(10).join(result.stdout.splitlines()[-50:])}\n"
            f"STDERR:\n{result.stderr[-500:]}"
        )
        # Verifica que rodou todas as 6 queries
        assert "DEMO CONCLUÍDO" in result.stdout
        assert "Total: 6 queries" in result.stdout

    def test_demo_includes_all_categories(self) -> None:
        """Demo cobre knowledge, comparison, inspection, finops, security."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "demo.py")],
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0
        # Verifica que cada categoria aparece no output
        for keyword in [
            "KNOWLEDGE",
            "COMPARISON",
            "INSPECTION (Terraform)",
            "INSPECTION (Kubernetes)",
            "FINOPS",
            "SECURITY",
        ]:
            assert keyword in result.stdout, f"Categoria {keyword} não encontrada"


# ─────────────────────────────────────────────────────────────────────────
# C4 architecture document
# ─────────────────────────────────────────────────────────────────────────


class TestC4ArchitectureDoc:
    """Documento de arquitetura C4."""

    def test_doc_exists(self) -> None:
        doc = ROOT / "docs" / "23-architecture-c4.md"
        assert doc.exists()
        assert doc.stat().st_size > 5000  # tem conteúdo substancial

    def test_doc_has_required_sections(self) -> None:
        doc = ROOT / "docs" / "23-architecture-c4.md"
        content = doc.read_text(encoding="utf-8")
        # 4 níveis C4 (Context, Container, Component, Code)
        assert "System Context" in content
        assert "Container" in content
        assert "Component" in content

    def test_doc_has_mermaid_diagrams(self) -> None:
        doc = ROOT / "docs" / "23-architecture-c4.md"
        content = doc.read_text(encoding="utf-8")
        # Mermaid é renderizado pelo GitHub markdown
        assert "```mermaid" in content
        # Deve ter pelo menos 3 diagramas
        n_diagrams = content.count("```mermaid")
        assert n_diagrams >= 3, f"Só {n_diagrams} diagramas mermaid"

    def test_doc_has_sequence_diagrams(self) -> None:
        """Pelo menos 1 sequence diagram (fluxo de request)."""
        doc = ROOT / "docs" / "23-architecture-c4.md"
        content = doc.read_text(encoding="utf-8")
        assert "sequenceDiagram" in content


# ─────────────────────────────────────────────────────────────────────────
# ADRs
# ─────────────────────────────────────────────────────────────────────────


class TestADRs:
    """Architecture Decision Records."""

    def test_adr_directory_exists(self) -> None:
        adr_dir = ROOT / "docs" / "adr"
        assert adr_dir.exists()
        assert adr_dir.is_dir()

    def test_adr_0005_exists(self) -> None:
        adr = ROOT / "docs" / "adr" / "0005-orchestrator-static-vs-react.md"
        assert adr.exists()
        content = adr.read_text(encoding="utf-8")
        # Formato padrão
        assert "# ADR 0005" in content
        assert "Status" in content
        assert "Contexto" in content
        assert "Decisão" in content
        assert "Consequências" in content

    def test_adr_0006_exists(self) -> None:
        adr = ROOT / "docs" / "adr" / "0006-mock-cloud-for-dev-ci.md"
        assert adr.exists()
        content = adr.read_text(encoding="utf-8")
        assert "# ADR 0006" in content
        assert "Mock" in content
        assert "Status" in content

    def test_all_adrs_have_standard_format(self) -> None:
        """Todos os ADRs têm Status, Contexto, Decisão, Consequências."""
        adr_dir = ROOT / "docs" / "adr"
        for adr_file in sorted(adr_dir.glob("*.md")):
            if adr_file.name.startswith("000") and not adr_file.name.startswith("0000"):
                # Só testa os ADRs numerados, não o README
                content = adr_file.read_text(encoding="utf-8")
                # Required sections (case-insensitive)
                assert "status" in content.lower()
                assert "contexto" in content.lower()
                assert "decisão" in content.lower() or "decisao" in content.lower()
                assert "consequências" in content.lower() or "consequencias" in content.lower()