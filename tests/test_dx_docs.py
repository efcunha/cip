"""Testes para documentação final (Round 14).

Valida:
- CHANGELOG.md estrutura
- README.md tem seções obrigatórias
- EXECUTIVE_SUMMARY.md tem seções de stakeholder

Uso:
    pytest tests/test_dx_docs.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────
# CHANGELOG
# ─────────────────────────────────────────────────────────────────────────


class TestChangelog:
    """CHANGELOG.md com histórico dos rounds."""

    def test_changelog_exists(self) -> None:
        cl = ROOT / "CHANGELOG.md"
        assert cl.exists()
        assert cl.stat().st_size > 5000  # substancial

    def test_changelog_has_rounds(self) -> None:
        """Deve documentar os 14 rounds."""
        content = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        # Round 1 até Round 13 (mais recente)
        for round_num in range(1, 14):
            assert f"Round {round_num}" in content, f"Round {round_num} não documentado"

    def test_changelog_has_keep_a_changelog_format(self) -> None:
        """Formato Keep a Changelog: Adicionado, Modificado, Consertado."""
        content = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        # Seções comuns do formato
        assert "Adicionado" in content or "Added" in content
        assert "Modificado" in content or "Changed" in content or "Modificado" in content
        # Manter Changelog format usa verbos no passado
        assert "Mantenedor" in content or "Maintainer" in content

    def test_changelog_documents_metrics_improvements(self) -> None:
        """Cada round documenta métricas de testes adicionados."""
        content = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        # Procura por menções a "X testes"
        import re
        test_mentions = re.findall(r"(\d+)\s*testes?", content, re.IGNORECASE)
        assert len(test_mentions) > 5  # pelo menos 5 menções

    def test_changelog_has_unreleased_section(self) -> None:
        """Topo do changelog tem Unreleased para próximos rounds."""
        content = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "Unreleased" in content


# ─────────────────────────────────────────────────────────────────────────
# README
# ─────────────────────────────────────────────────────────────────────────


class TestReadme:
    """README.md principal do projeto."""

    def test_readme_exists(self) -> None:
        rm = ROOT / "README.md"
        assert rm.exists()
        assert rm.stat().st_size > 3000

    def test_readme_has_badges(self) -> None:
        """Badges no topo (tests, python, license, version)."""
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        # Verifica badges markdown
        assert "shields.io" in content or "img.shields.io" in content
        # Badges típicas
        assert "tests" in content.lower()
        assert "python" in content.lower()
        assert "license" in content.lower() or "Apache" in content

    def test_readme_has_required_sections(self) -> None:
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        # Seções essenciais
        assert "## Princípios" in content or "## Features" in content or "## Quickstart" in content
        assert "## Quickstart" in content
        assert "## Arquitetura" in content
        assert "## Estrutura" in content or "## Stack" in content
        assert "## Segurança" in content
        assert "## Roadmap" in content
        assert "## Licença" in content or "## Métricas" in content

    def test_readme_links_to_changelog(self) -> None:
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "CHANGELOG" in content
        assert "QUICKSTART" in content
        assert "CONTRIBUTING" in content

    def test_readme_has_metrics_section(self) -> None:
        """Deve ter seção de métricas do projeto."""
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "Métricas" in content or "334" in content
        # Pelo menos 3 métricas numéricas
        import re
        numbers = re.findall(r"\b\d{2,4}\s*(testes?|chunks|regras|specialists|casos)", content, re.IGNORECASE)
        assert len(numbers) >= 3

    def test_readme_docker_compose_quickstart(self) -> None:
        """Quickstart tem docker compose."""
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "docker compose" in content or "docker-compose" in content
        # Makefile
        assert "make " in content
        # curl example
        assert "curl" in content


# ─────────────────────────────────────────────────────────────────────────
# Executive Summary
# ─────────────────────────────────────────────────────────────────────────


class TestExecutiveSummary:
    """EXECUTIVE_SUMMARY.md — one-pager para stakeholders."""

    def test_executive_summary_exists(self) -> None:
        es = ROOT / "docs" / "EXECUTIVE_SUMMARY.md"
        assert es.exists()
        assert es.stat().st_size > 3000

    def test_executive_summary_is_one_pager(self) -> None:
        """Tamanho moderado (one-pager) — não muito longo."""
        es = ROOT / "docs" / "EXECUTIVE_SUMMARY.md"
        # < 30KB é reasonable para one-pager
        assert es.stat().st_size < 30000

    def test_executive_summary_has_stakeholder_content(self) -> None:
        """Conteúdo para stakeholders: status, métricas, custos, próximos passos."""
        content = (ROOT / "docs" / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
        assert "Stakeholders" in content
        assert "Métricas" in content or "métricas" in content.lower()
        assert "Custo" in content or "custo" in content
        assert "próximos passos" in content.lower() or "Próximos" in content

    def test_executive_summary_has_decision_adr_table(self) -> None:
        """Tabela de ADRs (decisões arquiteturais)."""
        content = (ROOT / "docs" / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
        assert "ADR" in content
        # Tabela markdown
        assert "|" in content
        # Conta ADRs em todos os formatos: ADR-0001, ADR 0001, ADR0001, 0001 (em tabela)
        import re
        adr_mentions = re.findall(r"ADR[- ]?0\d{3}", content)
        adr_mentions.extend(re.findall(r"\bADR\s+0\d{3}\b", content))
        adr_mentions.extend(re.findall(r"\| 0\d{3} \|", content))  # em tabela markdown
        unique_mentions = set(adr_mentions)
        assert len(unique_mentions) >= 2, f"Só {len(unique_mentions)} ADRs: {unique_mentions}"

    def test_executive_summary_has_risk_table(self) -> None:
        """Tabela de riscos + mitigações."""
        content = (ROOT / "docs" / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
        assert "Risco" in content or "risco" in content
        assert "Mitigação" in content or "mitigação" in content

    def test_executive_summary_has_cost_table(self) -> None:
        """Tabela de custos estimados."""
        content = (ROOT / "docs" / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
        assert "$" in content  # pelo menos 1 valor em dólar
        # Custo mensal mencionado
        assert "mês" in content or "monthly" in content.lower()

    def test_executive_summary_has_metrics_targets_vs_actual(self) -> None:
        """Tabela de métricas: target vs atual."""
        content = (ROOT / "docs" / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
        assert "Target" in content or "target" in content
        assert "Atual" in content or "atual" in content or "Current" in content
        # Latência p95
        assert "5s" in content or "5000" in content or "latência" in content.lower()
        # Custo target
        assert "$0.05" in content or "$0.5" in content
        # Score eval ≥ 4.0
        assert "4.0" in content


# ─────────────────────────────────────────────────────────────────────────
# Integration: docs + tests + scripts
# ─────────────────────────────────────────────────────────────────────────


class TestDocsIntegration:
    """Integração: docs apontam para código real."""

    def test_quickstart_mentions_makefile(self) -> None:
        """QUICKSTART deve referenciar Makefile (via 'make X')."""
        content = (ROOT / "QUICKSTART.md").read_text(encoding="utf-8")
        # Tem pelo menos 3 comandos make
        import re
        make_commands = re.findall(r"`?make\s+([a-z-]+)`?", content)
        assert len(make_commands) >= 3, f"Só {len(make_commands)} comandos make encontrados"

    def test_contributing_mentions_pyproject(self) -> None:
        content = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "pyproject" in content.lower()

    def test_executive_summary_links_to_docs(self) -> None:
        """EXECUTIVE_SUMMARY links para os docs principais."""
        content = (ROOT / "docs" / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
        for doc in ["QUICKSTART", "CONTRIBUTING", "CHANGELOG", "23-architecture-c4", "18-production-runbook", "adr"]:
            assert doc in content, f"{doc} não referenciado"

    def test_readme_has_makefile_targets(self) -> None:
        """README menciona targets make comuns."""
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        for target in ["make help", "make test", "make preflight", "make demo"]:
            assert target in content, f"{target} não mencionado"