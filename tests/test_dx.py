"""Testes para Developer Experience (Round 13).

Valida:
- Makefile tem targets essenciais
- QUICKSTART.md existe e tem seções obrigatórias
- CONTRIBUTING.md tem convenções
- Dev container config válido
- GitHub templates existem

Uso:
    pytest tests/test_dx.py -v
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
# Makefile
# ─────────────────────────────────────────────────────────────────────────


class TestMakefile:
    """Makefile com targets comuns."""

    def test_makefile_exists(self) -> None:
        makefile = ROOT / "Makefile"
        assert makefile.exists()
        assert makefile.stat().st_size > 1000

    def test_makefile_has_help_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "help:" in makefile
        assert "## " in makefile  # help comments

    def test_makefile_has_install_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "install:" in makefile
        assert "pip install" in makefile

    def test_makefile_has_test_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "test:" in makefile
        assert "test-fast:" in makefile

    def test_makefile_has_lint_and_format(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "lint:" in makefile
        assert "format:" in makefile
        assert "ruff" in makefile

    def test_makefile_has_demo_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "demo:" in makefile
        assert "demo-mock:" in makefile
        assert "demo-react:" in makefile

    def test_makefile_has_preflight_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "preflight:" in makefile
        assert "preflight-fast:" in makefile

    def test_makefile_has_docs_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "docs:" in makefile
        assert "openapi" in makefile.lower()

    def test_makefile_has_clean_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "clean:" in makefile

    def test_makefile_has_ci_helpers(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        assert "ci-test:" in makefile
        assert "ci-preflight:" in makefile
        assert "ci-eval:" in makefile

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="make não está instalado por padrão no Windows",
    )
    def test_makefile_help_command_works(self) -> None:
        """Roda `make help` e valida output (skip em Windows)."""
        result = subprocess.run(
            ["make", "help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        # make help não tem dependência, sempre retorna 0
        assert result.returncode == 0
        assert "Targets" in result.stdout or "targets" in result.stdout.lower()

    def test_makefile_phony_targets(self) -> None:
        """Todos os targets comuns estão em .PHONY (suporta múltiplas linhas)."""
        makefile = (ROOT / "Makefile").read_text()
        # Extrai bloco .PHONY (pode estar em múltiplas linhas com \)
        phony_match = re.search(
            r"^\.PHONY:\s*([\s\S]+?)(?=^\.[A-Z]+|\Z)",
            makefile,
            re.MULTILINE,
        )
        assert phony_match is not None
        # Normaliza: remove quebras de linha + continuação backslash
        phony_text = phony_match.group(1)
        phony_text = phony_text.replace("\\\n", " ").replace("\n", " ")
        phony_targets = phony_text.split()
        # Targets essenciais devem estar no .PHONY
        for target in ["install", "test", "lint", "demo", "preflight", "up", "down"]:
            assert target in phony_targets, f"{target} not in .PHONY (have: {phony_targets})"


# ─────────────────────────────────────────────────────────────────────────
# QUICKSTART
# ─────────────────────────────────────────────────────────────────────────


class TestQuickstart:
    """QUICKSTART.md — guia de 5min."""

    def test_quickstart_exists(self) -> None:
        qs = ROOT / "QUICKSTART.md"
        assert qs.exists()
        assert qs.stat().st_size > 2000

    def test_quickstart_has_required_sections(self) -> None:
        content = (ROOT / "QUICKSTART.md").read_text(encoding="utf-8")
        # Required sections
        assert "## 1. Pré-requisitos" in content
        assert "## 2. Setup rápido" in content
        assert "## 3. Rodar" in content
        assert "## 4. Demo completa" in content
        assert "## 5. Rodar testes" in content
        assert "## 6. Próximos passos" in content
        assert "Troubleshooting" in content

    def test_quickstart_has_docker_option(self) -> None:
        content = (ROOT / "QUICKSTART.md").read_text(encoding="utf-8")
        assert "docker compose" in content
        assert "Opção A" in content
        assert "Opção B" in content

    def test_quickstart_has_role_based_next_steps(self) -> None:
        """Deve ter próximos passos por papel."""
        content = (ROOT / "QUICKSTART.md").read_text(encoding="utf-8")
        assert "Engenheiro de plataforma" in content
        assert "Engenheiro de ML" in content or "Engenheiro de ML/AI" in content
        assert "SRE" in content
        assert "Arquiteto" in content


# ─────────────────────────────────────────────────────────────────────────
# CONTRIBUTING
# ─────────────────────────────────────────────────────────────────────────


class TestContributing:
    """CONTRIBUTING.md — guia para contribuidores."""

    def test_contributing_exists(self) -> None:
        contrib = ROOT / "CONTRIBUTING.md"
        assert contrib.exists()
        assert contrib.stat().st_size > 2000

    def test_contributing_has_workflow(self) -> None:
        content = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "Workflow" in content
        assert "fork" in content.lower() or "clone" in content.lower()

    def test_contributing_has_conventions(self) -> None:
        """Deve documentar convenções de commit (Conventional Commits)."""
        content = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "Conventional Commits" in content
        assert "feat" in content
        assert "fix" in content
        # Branch convention
        assert "feature/" in content or "main" in content

    def test_contributing_has_project_structure(self) -> None:
        content = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "src/cip/" in content
        assert "tests/" in content
        assert "scripts/" in content

    def test_contributing_has_testing_guide(self) -> None:
        content = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "pytest" in content
        assert "fixture" in content.lower() or "Fixture" in content

    def test_contributing_has_code_of_conduct_section(self) -> None:
        content = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "Conduta" in content or "Conduct" in content
        assert "respeitoso" in content.lower() or "respeito" in content.lower()


# ─────────────────────────────────────────────────────────────────────────
# Dev container
# ─────────────────────────────────────────────────────────────────────────


class TestDevContainer:
    """VS Code dev container config."""

    def test_devcontainer_dir_exists(self) -> None:
        dev_dir = ROOT / ".devcontainer"
        assert dev_dir.exists()
        assert dev_dir.is_dir()

    def test_devcontainer_json_exists(self) -> None:
        config = ROOT / ".devcontainer" / "devcontainer.json"
        assert config.exists()
        assert config.stat().st_size > 100

    def test_devcontainer_json_valid(self) -> None:
        """JSON válido com name + image + customizations."""
        import json as json_mod

        config = json_mod.loads(
            (ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")
        )
        assert "name" in config
        assert "image" in config
        assert "customizations" in config
        assert "vscode" in config["customizations"]
        # Extensions devem incluir Python + Ruff
        exts = config["customizations"]["vscode"].get("extensions", [])
        exts_str = " ".join(exts)
        assert "python" in exts_str.lower()
        assert "ruff" in exts_str.lower()

    def test_devcontainer_forwards_api_port(self) -> None:
        config = (ROOT / ".devcontainer" / "devcontainer.json").read_text()
        # API port 8000 deve ser forwarded
        assert "8000" in config


# ─────────────────────────────────────────────────────────────────────────
# GitHub templates
# ─────────────────────────────────────────────────────────────────────────


class TestGitHubTemplates:
    """GitHub Issue e PR templates."""

    def test_issue_template_dir_exists(self) -> None:
        tpl_dir = ROOT / ".github" / "ISSUE_TEMPLATE"
        assert tpl_dir.exists()
        assert tpl_dir.is_dir()

    def test_bug_report_template_exists(self) -> None:
        template = ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.md"
        assert template.exists()

    def test_bug_report_template_has_required_sections(self) -> None:
        content = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.md").read_text(encoding="utf-8")
        assert "Descrição" in content
        assert "Passos para reproduzir" in content
        assert "Comportamento esperado" in content
        assert "Comportamento atual" in content
        assert "Ambiente" in content
        assert "Logs" in content

    def test_feature_request_template_exists(self) -> None:
        template = ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.md"
        assert template.exists()

    def test_feature_request_has_alternatives(self) -> None:
        content = (ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.md").read_text(encoding="utf-8")
        assert "Problema" in content
        assert "Solução proposta" in content
        assert "Alternativas" in content

    def test_pr_template_exists(self) -> None:
        template = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
        assert template.exists()

    def test_pr_template_has_checklist(self) -> None:
        content = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
        assert "Checklist" in content
        assert "ruff" in content.lower()
        assert "preflight" in content.lower()
        assert "test" in content.lower()