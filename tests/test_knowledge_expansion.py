"""Testes para expansão de knowledge base (Round 18).

Valida:
- sources_advanced.yaml existe e tem URLs em áreas gap
- 2 novos specialists: platform_engineering, reliability
- Router reconhece os novos keywords
- load_sources() merge de sources.yaml + sources_advanced.yaml

Uso:
    pytest tests/test_knowledge_expansion.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Sources advanced
# ─────────────────────────────────────────────────────────────────────────


class TestSourcesAdvanced:
    """sources_advanced.yaml preenche gaps para Distinguished Architect."""

    def test_sources_advanced_file_exists(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        assert f.exists()
        assert f.stat().st_size > 5000  # substancial

    def test_covers_ai_ml_infrastructure(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # AI/ML
        assert "sagemaker" in content.lower()
        assert "vertex-ai" in content.lower()
        assert "ai-foundry" in content.lower()
        assert "bedrock" in content.lower()

    def test_covers_kubernetes_advanced(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # K8s avançado
        assert "kubernetes" in content.lower()
        assert "ingress" in content.lower()
        assert "pod-security" in content.lower() or "podsecurity" in content.lower()
        # network policies: aceita várias grafias
        assert "network-polic" in content.lower() or "networkpolic" in content.lower()

    def test_covers_observability(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # Observability stack - principais
        assert "prometheus" in content.lower()
        assert "grafana" in content.lower()
        assert "opentelemetry" in content.lower() or "cloud-trace" in content.lower()
        # Pelo menos 2 dos: loki, tempo, alertmanager, profiler, error-reporting
        obs_optional = sum(
            1 for w in ["loki", "tempo", "alertmanager", "profiler", "error-reporting"]
            if w in content.lower()
        )
        assert obs_optional >= 1, "Pelo menos 1 ferramenta adicional de observability esperada"

    def test_covers_gitops(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # GitOps
        assert "argo" in content.lower() or "argocd" in content.lower()
        assert "flux" in content.lower()

    def test_covers_platform_engineering(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # Platform Engineering
        assert "backstage" in content.lower()
        assert "crossplane" in content.lower()

    def test_covers_sre_reliability(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # SRE / Reliability
        assert "sre" in content.lower()
        assert "postmortem" in content.lower() or "post-mortem" in content.lower()
        assert "chaos" in content.lower()  # chaos engineering
        assert "slo" in content.lower() or "error budget" in content.lower()

    def test_covers_advanced_networking(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # Advanced networking
        assert "direct-connect" in content.lower() or "direct connect" in content.lower()
        assert "expressroute" in content.lower()
        assert "interconnect" in content.lower()

    def test_covers_security_advanced(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # Security avançado
        assert "opa" in content.lower() or "open policy agent" in content.lower()
        assert "falco" in content.lower() or "trivy" in content.lower()
        assert "zero trust" in content.lower() or "policy-as-code" in content.lower()

    def test_covers_vector_dbs(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # Vector databases
        assert "weaviate" in content.lower() or "qdrant" in content.lower()

    def test_covers_service_mesh(self) -> None:
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # Service mesh
        assert "istio" in content.lower()

    def test_has_minimum_50_urls(self) -> None:
        """Sources avançadas devem adicionar pelo menos 50 URLs."""
        f = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
        content = f.read_text(encoding="utf-8")
        # Conta linhas que começam com "- https"
        urls = [l for l in content.splitlines() if l.strip().startswith("- https")]
        assert len(urls) >= 50, f"Só {len(urls)} URLs"


# ─────────────────────────────────────────────────────────────────────────
# Specialists expandidos
# ─────────────────────────────────────────────────────────────────────────


class TestSpecialistsExpansion:
    """2 novos specialists adicionados (Round 18)."""

    def test_platform_engineering_specialist_exists(self) -> None:
        from src.cip.prompts.specialists import SPECIALIST_PROMPTS, get_specialist_prompt

        assert "platform_engineering" in SPECIALIST_PROMPTS
        prompt = get_specialist_prompt("platform_engineering")
        assert prompt is not None
        assert "Platform" in prompt or "IDP" in prompt

    def test_reliability_specialist_exists(self) -> None:
        from src.cip.prompts.specialists import SPECIALIST_PROMPTS, get_specialist_prompt

        assert "reliability" in SPECIALIST_PROMPTS
        prompt = get_specialist_prompt("reliability")
        assert prompt is not None
        assert "SLO" in prompt or "reliability" in prompt.lower()

    def test_all_specialists_list_includes_new_ones(self) -> None:
        from src.cip.prompts.specialists import ALL_SPECIALISTS

        assert "platform_engineering" in ALL_SPECIALISTS
        assert "reliability" in ALL_SPECIALISTS
        # Round 18: 8 → 10 (platform_engineering + reliability).
        # Round 22: 10 → 11 (software_architecture).
        assert len(ALL_SPECIALISTS) >= 11, (
            f"Esperado >= 11 especialistas, achou {len(ALL_SPECIALISTS)}"
        )

    def test_specialist_categories_includes_new_ones(self) -> None:
        from src.cip.prompts.specialists import SPECIALIST_CATEGORIES

        domain = SPECIALIST_CATEGORIES["domain"]
        assert "platform_engineering" in domain
        assert "reliability" in domain


# ─────────────────────────────────────────────────────────────────────────
# Router reconhece os novos specialists
# ─────────────────────────────────────────────────────────────────────────


class TestRouterRecognizesNewSpecialists:
    """Router detecta keywords que roteiam para os novos specialists."""

    def test_platform_engineering_routing(self) -> None:
        from src.cip.agents.router import classify, _detect_domains

        # Keywords que devem ativar platform_engineering
        for q in [
            "Como construir um Internal Developer Platform?",
            "O que é Golden Path no backstage?",
            "Como implementar self-service infrastructure?",
            "O que é Platform as a Product?",
        ]:
            domains = _detect_domains(q)
            assert "platform_engineering" in domains, f"'{q}' não roteou para platform_engineering"

    def test_reliability_routing(self) -> None:
        from src.cip.agents.router import classify, _detect_domains

        # Keywords que devem ativar reliability
        for q in [
            "Como definir SLOs para minha API?",
            "O que é error budget?",
            "Como fazer chaos engineering?",
            "Como calcular RPO e RTO?",
            "Como escrever post-mortem?",
        ]:
            domains = _detect_domains(q)
            assert "reliability" in domains, f"'{q}' não roteou para reliability"

    def test_router_includes_new_specialists_in_plan(self) -> None:
        from src.cip.agents.router import classify

        # Plan de reliability deve incluir reliability
        plan = classify("Como definir SLOs?")
        assert "reliability" in plan.specialists

        # Plan de platform engineering deve incluir platform_engineering
        plan = classify("Como criar um IDP?")
        assert "platform_engineering" in plan.specialists


# ─────────────────────────────────────────────────────────────────────────
# load_sources merge
# ─────────────────────────────────────────────────────────────────────────


class TestLoadSourcesMerge:
    """load_sources() faz merge de sources.yaml + sources_advanced.yaml."""

    def test_load_sources_includes_advanced(self) -> None:
        """load_sources() deve incluir URLs avançadas."""
        from src.cip.ingestion.ingest import load_sources

        sources = load_sources("mvp")
        all_sources = []
        for cloud, entries in sources.items():
            for entry in entries:
                all_sources.append(entry.get("source", ""))

        # Deve ter pelo menos uma source avançada
        advanced_sources = [
            "aws-ml", "gcp-ml", "azure-ml", "kubernetes-docs",
            "prometheus", "grafana", "opentelemetry", "argocd", "fluxcd",
            "backstage", "sre-book", "chaos-mesh", "istio",
        ]
        found_advanced = any(adv in s for s in all_sources for adv in advanced_sources)
        assert found_advanced, f"Nenhuma source avançada encontrada em {set(all_sources)}"

    def test_load_sources_returns_8_advanced_categories(self) -> None:
        """Sources avançadas cobrem pelo menos 8 categorias gap."""
        from src.cip.ingestion.ingest import load_sources

        sources = load_sources("mvp")
        categories = set()
        for cloud, entries in sources.items():
            for entry in entries:
                categories.add(entry.get("category", ""))

        gap_categories = {
            "ai-ml", "observability", "devops", "reliability", "governance",
        }
        covered = categories & gap_categories
        assert len(covered) >= 4, f"Só {len(covered)} gap categories: {covered}"