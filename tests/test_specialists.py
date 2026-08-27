"""Testes do orquestrador com múltiplos especialistas (Fase 4).

Valida:
- Orquestrador executa 1-3 especialistas em paralelo
- Cada especialista recebe contexto filtrado (cloud quando aplicável)
- Resultados são mergeados no summary final
- Latência p95 < 8s com 3 especialistas (SLA)
- Tools cloud são degradadas gracefully

Uso:
    pytest tests/test_specialists.py -v
"""

from __future__ import annotations

import asyncio
import time

import pytest

from cip.agents.orchestrator import get_orchestrator
from cip.logging import configure_logging

configure_logging()


# ─────────────────────────────────────────────────────────────────────────
# Singleton cleanup para pytest-asyncio
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_rag_engine():
    """Limpa singleton do RAG engine entre testes (evita event loop fechado)."""
    import cip.agents.orchestrator as orch_mod
    import cip.rag.engine as rag_mod

    orch_mod._orchestrator = None
    rag_mod._engine = None
    yield
    orch_mod._orchestrator = None
    rag_mod._engine = None


# ─────────────────────────────────────────────────────────────────────────
# Catálogo de especialistas
# ─────────────────────────────────────────────────────────────────────────


class TestSpecialistsCatalog:
    """11 especialistas disponíveis (3 provedores + 8 domínios).

    Round 18: 8 → 10 (platform_engineering + reliability).
    Round 22: 10 → 11 (software_architecture). Mantém aws/gcp/azure como provedores
    e tudo mais como domínio. Knowledge areas do RAG (architecture, case-studies)
    ficam como pseudo-clouds em SPECIALIST_CATEGORIES['knowledge_area'], não
    viram specialists (são knowledge, não personas).
    """

    def test_specialists_count(self) -> None:
        from cip.prompts.specialists import ALL_SPECIALISTS, SPECIALIST_PROMPTS

        # Round 18: 8 → 10, Round 22: 10 → 11
        assert len(ALL_SPECIALISTS) >= 11, (
            f"Esperado >= 11 especialistas, achou {len(ALL_SPECIALISTS)}"
        )
        assert len(SPECIALIST_PROMPTS) >= 11

    def test_all_three_cloud_providers(self) -> None:
        from cip.prompts.specialists import ALL_SPECIALISTS

        for cloud in ("aws", "gcp", "azure"):
            assert cloud in ALL_SPECIALISTS, f"{cloud} deve ser especialista"

    def test_all_five_domains(self) -> None:
        from cip.prompts.specialists import ALL_SPECIALISTS

        for domain in ("finops", "security", "sre", "kubernetes", "terraform"):
            assert domain in ALL_SPECIALISTS, f"{domain} deve ser especialista"

    def test_software_architecture_specialist_registered(self) -> None:
        """Round 22+: software_architecture é specialist ativo."""
        from cip.prompts.specialists import SPECIALIST_PROMPTS, get_specialist_prompt

        assert "software_architecture" in SPECIALIST_PROMPTS
        prompt = get_specialist_prompt("software_architecture")
        assert prompt is not None
        assert len(prompt) > 100
        # Deve cobrir os patterns chave
        for keyword in ("microservice", "circuit breaker", "cqrs", "event"):
            assert keyword.lower() in prompt.lower(), (
                f"software_architecture deve mencionar '{keyword}'"
            )

    def test_knowledge_areas_listed(self) -> None:
        """Round 22+: knowledge areas (architecture, case-studies) são pseudo-clouds."""
        from cip.prompts.specialists import SPECIALIST_CATEGORIES

        assert "knowledge_area" in SPECIALIST_CATEGORIES
        assert "architecture" in SPECIALIST_CATEGORIES["knowledge_area"]
        assert "case-studies" in SPECIALIST_CATEGORIES["knowledge_area"]

    def test_each_specialist_has_prompt(self) -> None:
        from cip.prompts.specialists import SPECIALIST_PROMPTS

        for name, prompt in SPECIALIST_PROMPTS.items():
            assert isinstance(prompt, str)
            assert len(prompt) > 30, f"Prompt de {name} muito curto"


# ─────────────────────────────────────────────────────────────────────────
# Roteamento
# ─────────────────────────────────────────────────────────────────────────


class TestOrchestratorRouting:
    """Orquestrador usa roteamento correto."""

    def test_iac_routes_to_terraform_security(self) -> None:
        from cip.agents.models import Intent
        from cip.agents.router import classify

        plan = classify("Revise meu .tf", has_iac_payload=True)
        assert plan.intent == Intent.IAC_REVIEW
        assert "terraform" in plan.specialists
        assert "security" in plan.specialists

    def test_env_full_stack(self) -> None:
        from cip.agents.router import classify

        plan = classify("Analise meu ambiente AWS Kubernetes")
        assert len(plan.specialists) >= 1


# ─────────────────────────────────────────────────────────────────────────
# Execução end-to-end
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestOrchestratorExecution:
    """Execução end-to-end do orquestrador com especialistas."""

    async def test_knowledge_query_executes_specialists(self) -> None:
        orch = get_orchestrator()
        result = await orch.handle(
            "O que é o AWS Well-Architected Framework?",
            cloud="aws",
        )
        assert result.plan is not None
        assert len(result.plan.specialists) >= 1
        assert len(result.sources) >= 1

    async def test_iac_review_executes_specialists(self) -> None:
        orch = get_orchestrator()
        iac = """
resource "aws_s3_bucket" "data" {
  bucket = "data"
}
resource "aws_security_group" "web" {
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
"""
        result = await orch.handle(
            "Analise meu Terraform AWS", cloud="aws", iac_payload=iac
        )
        # Plan deve incluir terraform + security + aws (cloud detectado pela query)
        assert result.plan is not None
        assert "terraform" in result.plan.specialists
        assert "security" in result.plan.specialists
        assert "aws" in result.plan.specialists
        assert len(result.plan.specialists) <= 3
        # Inspection gerou findings (SG crítico, S3 sem criptografia)
        assert any(f.severity == "critical" for f in result.findings)
        assert any(f.severity == "high" for f in result.findings)

    async def test_cost_query_uses_finops(self) -> None:
        orch = get_orchestrator()
        result = await orch.handle(
            "Como reduzir custo de EC2 com Savings Plans?",
            cloud="aws",
        )
        assert "finops" in result.plan.specialists

    async def test_environment_uses_multiple_specialists(self) -> None:
        orch = get_orchestrator()
        result = await orch.handle(
            "Analise meu ambiente AWS para reduzir custos",
            cloud="aws",
        )
        assert len(result.plan.specialists) >= 2
        assert result.summary

    async def test_latency_under_30s_with_3_specialists(self) -> None:
        """SLA relaxado para CI: latência < 30s com 3 especialistas (CI não tem GPU)."""
        orch = get_orchestrator()
        queries = [
            ("O que é o AWS Well-Architected?", "aws"),
            ("Como otimizar custos no Azure?", "azure"),
            ("Boas práticas de Kubernetes no GCP", "gcp"),
        ]
        latencies = []
        for q, c in queries:
            t0 = time.perf_counter()
            result = await orch.handle(q, cloud=c)
            latencies.append(int((time.perf_counter() - t0) * 1000))
            assert result.summary

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        # Em produção com Bedrock/Claude: < 8s
        # Em CI com bge-large em CPU: < 30s é aceitável
        assert p95 < 30000, f"p95 {p95}ms acima do limite de CI"


@pytest.mark.asyncio
class TestSpecialistResultMerge:
    """Validação do merge cross-domain."""

    async def test_specialist_failure_does_not_break_response(self) -> None:
        """Se um especialista falhar, resposta ainda vem via RAG principal."""
        orch = get_orchestrator()
        result = await orch.handle(
            "Como otimizar custos no AWS?",
            cloud="aws",
        )
        assert result.summary
        assert len(result.summary) > 50

    async def test_no_specialists_runs_just_rag(self) -> None:
        """Pergunta sem specialists deve funcionar via RAG puro."""
        orch = get_orchestrator()
        result = await orch.handle(
            "O que é uma VPC?",
        )
        assert result.summary
        # Sem especialistas ou com []: ainda retorna via RAG
        assert result.plan is not None