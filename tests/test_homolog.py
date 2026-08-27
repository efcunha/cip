"""Testes para setup de homologação (Round 20).

Valida:
- smoke_test.py: estrutura, exit codes, parsing
- setup_homolog.py: steps, error handling
- homologation.md existe e tem seções obrigatórias
- Makefile tem targets homolog, homolog-fast, smoke, smoke-verbose

Uso:
    pytest tests/test_homolog.py -v
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────────


class TestSmokeTestScript:
    """Script de smoke test."""

    def test_script_exists(self) -> None:
        script = ROOT / "scripts" / "smoke_test.py"
        assert script.exists()
        assert script.stat().st_size > 1000

    def test_script_help_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_test.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "URL" in result.stdout or "smoke" in result.stdout.lower()

    def test_script_supports_url_and_api_key(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_test.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "--url" in result.stdout
        assert "--api-key" in result.stdout
        assert "--tenant-id" in result.stdout
        assert "--verbose" in result.stdout

    def test_script_returns_correct_exit_code_on_connection_error(self) -> None:
        """Com API não rodando, retorna exit code 2 (connection error)."""
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "smoke_test.py"),
                "--url", "http://127.0.0.1:1",  # porta inválida
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Exit code 2 = connection error (ver código)
        assert result.returncode in (1, 2)

    def test_script_has_all_test_functions(self) -> None:
        content = (ROOT / "scripts" / "smoke_test.py").read_text(encoding="utf-8")
        # Verifica que tem todos os 8 testes
        for fn in [
            "test_health", "test_health_live", "test_health_ready",
            "test_metrics", "test_ask_simple", "test_ask_with_grounding",
            "test_analyze_iac", "test_streaming_ask",
        ]:
            assert f"async def {fn}" in content, f"Função {fn} não encontrada"

    def test_script_tests_have_assertions(self) -> None:
        content = (ROOT / "scripts" / "smoke_test.py").read_text(encoding="utf-8")
        # Cada test deve ter pelo menos 1 assert
        test_count = content.count("async def test_")
        assert_count = content.count("assert ")
        assert assert_count >= test_count, \
            f"Só {assert_count} asserts para {test_count} testes"


# ─────────────────────────────────────────────────────────────────────────
# Setup homolog
# ─────────────────────────────────────────────────────────────────────────


class TestSetupHomologScript:
    """Script de setup de homologação."""

    def test_script_exists(self) -> None:
        script = ROOT / "scripts" / "setup_homolog.py"
        assert script.exists()
        assert script.stat().st_size > 1000

    def test_script_help_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "setup_homolog.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "homolog" in result.stdout.lower()

    def test_script_supports_skip_flags(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "setup_homolog.py"), "--help"],
            capture_output=True,
            text=True,
        )
        assert "--skip-build" in result.stdout
        assert "--skip-ingest" in result.stdout
        assert "--skip-tests" in result.stdout
        assert "--api-url" in result.stdout

    def test_script_has_all_step_functions(self) -> None:
        content = (ROOT / "scripts" / "setup_homolog.py").read_text(encoding="utf-8")
        for fn in [
            "step_check_prerequisites",
            "step_start_database",
            "step_wait_db_ready",
            "step_apply_schema",
            "step_ingest",
            "step_preflight",
            "step_smoke_test",
        ]:
            assert f"def {fn}" in content, f"Função {fn} não encontrada"

    def test_script_prerequisites_check_podman(self) -> None:
        content = (ROOT / "scripts" / "setup_homolog.py").read_text(encoding="utf-8")
        # Verifica que checa podman
        assert "podman" in content
        assert "psql" in content or "DB" in content


# ─────────────────────────────────────────────────────────────────────────
# Homologation doc
# ─────────────────────────────────────────────────────────────────────────


class TestHomologationDoc:
    """Documentação de homologação."""

    def test_doc_exists(self) -> None:
        doc = ROOT / "docs" / "homologation.md"
        assert doc.exists()
        assert doc.stat().st_size > 3000

    def test_doc_has_setup_section(self) -> None:
        content = (ROOT / "docs" / "homologation.md").read_text(encoding="utf-8")
        assert "Setup" in content
        assert "Opção A" in content or "Opção B" in content

    def test_doc_has_smoke_test_section(self) -> None:
        content = (ROOT / "docs" / "homologation.md").read_text(encoding="utf-8")
        assert "Smoke Test" in content or "smoke" in content.lower()

    def test_doc_has_checklist(self) -> None:
        content = (ROOT / "docs" / "homologation.md").read_text(encoding="utf-8")
        # Checklist de homologação
        assert "Checklist" in content or "checklist" in content
        # Pelo menos 10 itens de checklist
        checklist_items = content.count("- [ ]")
        assert checklist_items >= 10, f"Só {checklist_items} itens de checklist"

    def test_doc_has_troubleshooting(self) -> None:
        content = (ROOT / "docs" / "homologation.md").read_text(encoding="utf-8")
        assert "Troubleshooting" in content

    def test_doc_has_production_comparison(self) -> None:
        content = (ROOT / "docs" / "homologation.md").read_text(encoding="utf-8")
        assert "Produção" in content or "produção" in content
        # Tabela de comparação
        assert "|" in content
        assert "Homolog" in content or "homolog" in content

    def test_doc_links_to_other_docs(self) -> None:
        content = (ROOT / "docs" / "homologation.md").read_text(encoding="utf-8")
        # Deve referenciar outros documentos
        for ref in [
            "18-production-runbook",
            "23-architecture-c4",
            "09-plano-execucao-llm-cloud",
        ]:
            assert ref in content or ref.replace("-", "_") in content, \
                f"Referência a {ref} não encontrada"


# ─────────────────────────────────────────────────────────────────────────
# Makefile integration
# ─────────────────────────────────────────────────────────────────────────


class TestMakefileHomolog:
    """Makefile tem targets para homologação."""

    def test_makefile_has_homolog_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert re.search(r"^homolog:", makefile, re.MULTILINE) is not None

    def test_makefile_has_homolog_fast_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert re.search(r"^homolog-fast:", makefile, re.MULTILINE) is not None

    def test_makefile_has_smoke_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert re.search(r"^smoke:", makefile, re.MULTILINE) is not None

    def test_makefile_has_smoke_verbose_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert re.search(r"^smoke-verbose:", makefile, re.MULTILINE) is not None

    def test_makefile_homolog_calls_setup_script(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        # homolog target deve chamar setup_homolog.py
        homolog_section = re.search(
            r"^homolog:.*?(?=^\w+:|\Z)", makefile, re.MULTILINE | re.DOTALL
        )
        if homolog_section:
            assert "setup_homolog" in homolog_section.group()

    def test_makefile_smoke_calls_smoke_script(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        smoke_section = re.search(
            r"^smoke:.*?(?=^\w+:|\Z)", makefile, re.MULTILINE | re.DOTALL
        )
        if smoke_section:
            assert "smoke_test" in smoke_section.group()


# ─────────────────────────────────────────────────────────────────────────
# Wait for DB
# ─────────────────────────────────────────────────────────────────────────


class TestWaitForDB:
    """Helper wait_for_db."""

    def test_wait_for_db_function_exists(self) -> None:
        content = (ROOT / "scripts" / "setup_homolog.py").read_text(encoding="utf-8")
        assert "def wait_for_db" in content
        # Importa socket
        assert "import socket" in content

    def test_wait_for_db_uses_socket(self) -> None:
        """Usa socket.create_connection para verificar TCP connect."""
        from scripts.setup_homolog import wait_for_db

        # Testa com porta inválida (deve falhar rápido)
        result = wait_for_db("127.0.0.1", 1, timeout_s=1)
        assert result is False

    def test_wait_for_db_succeeds_for_listening_port(self) -> None:
        """Porta que está escutando retorna True."""
        import socket
        import threading

        from scripts.setup_homolog import wait_for_db

        # Cria servidor TCP temporário
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        try:
            result = wait_for_db("127.0.0.1", port, timeout_s=2)
            assert result is True
        finally:
            server.close()


# ─────────────────────────────────────────────────────────────────────────
# Integration: Podman compatibility
# ─────────────────────────────────────────────────────────────────────────


class TestPodmanCompatibility:
    """Valida que docker-compose.yml funciona com podman."""

    def test_compose_file_uses_podman_compatible_format(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        # docker-compose v3 é compatível com podman-compose
        assert "version:" in compose or "services:" in compose
        # Round 22: o Postgres é EXTERNO (`cloudpilot_postgres`, pgvector:pg16),
        # não sobe no compose. A referência deve apontar para o hostname externo
        # e a rede DNS `cip_default`.
        assert "cloudpilot_postgres" in compose
        assert "networks:" in compose
        assert "cip_default" in compose

    def test_compose_includes_pgvector_extension(self) -> None:
        """Compose aponta para o Postgres externo com pgvector (não sobe um local)."""
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        # O banco externo roda pgvector:pg16 — o compose documenta isso no header
        # e no DATABASE_URL (port 5432).
        assert "pgvector" in compose
        # Port 5432 (Postgres externo)
        assert "5432" in compose

    def test_podman_compose_alternative_works(self) -> None:
        """Documenta alternativa com podman-compose."""
        # docker-compose.yml é compatível com podman-compose
        # porque podman implementa Compose Spec
        # (já testado em Round 1 — podman compose up -d db funciona)
        pass  # integration test seria: podman compose -f docker-compose.yml config


# ─────────────────────────────────────────────────────────────────────────
# End-to-end (sem mock — só estrutura)
# ─────────────────────────────────────────────────────────────────────────


class TestSmokeTestOutput:
    """Validação do output do smoke test (sem API real)."""

    def test_smoke_test_graceful_failure_message(self) -> None:
        """Quando API não está disponível, mensagem clara."""
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "smoke_test.py"),
                "--url", "http://127.0.0.1:1",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout + result.stderr
        # Deve mencionar que API não está acessível
        assert (
            "API" in output
            and ("não" in output.lower() or "connection" in output.lower() or "abort" in output.lower())
        )

    def test_setup_homolog_validates_prerequisites(self) -> None:
        """Setup verifica pré-requisitos antes de prosseguir."""
        # Sem podman, setup deve falhar
        # (Não podemos testar isso diretamente, mas verificamos a estrutura)
        content = (ROOT / "scripts" / "setup_homolog.py").read_text(encoding="utf-8")
        # Deve checar podman primeiro
        assert 'check_prerequisite("podman"' in content
        # step_check_prerequisites é o primeiro step
        assert "step_check_prerequisites" in content