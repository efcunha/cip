"""Testes do router melhorado (Fase 4): roteamento para 1-3 especialistas,
combinação provedor + domínio, e merge cross-domain.

Uso:
    pytest tests/test_router_v2.py -v
"""

from __future__ import annotations

import pytest

from cip.agents.models import Intent
from cip.agents.router import classify, _detect_clouds, _detect_domains, _cap_specialists


# ─────────────────────────────────────────────────────────────────────────
# Cloud detection
# ─────────────────────────────────────────────────────────────────────────


class TestDetectClouds:
    """Detecção de provedores de cloud na pergunta."""

    def test_detects_aws_explicit(self) -> None:
        assert _detect_clouds("Como otimizar custos no AWS?") == ["aws"]

    def test_detects_aws_by_service(self) -> None:
        assert _detect_clouds("Meu EKS está caro, o que faço?") == ["aws"]

    def test_detects_azure_explicit(self) -> None:
        assert _detect_clouds("Como funciona o AKS?") == ["azure"]

    def test_detects_gcp_explicit(self) -> None:
        assert _detect_clouds("Tenho um cluster GKE, preciso de ajuda") == ["gcp"]

    def test_detects_multiple_clouds(self) -> None:
        clouds = _detect_clouds("Comparar AWS Lambda vs GCP Cloud Functions")
        assert "aws" in clouds
        assert "gcp" in clouds

    def test_returns_empty_when_no_cloud(self) -> None:
        assert _detect_clouds("O que é FinOps?") == []


# ─────────────────────────────────────────────────────────────────────────
# Domain detection
# ─────────────────────────────────────────────────────────────────────────


class TestDetectDomains:
    """Detecção de domínios (finops/security, sre, kubernetes, terraform)."""

    def test_detects_finops_keywords(self) -> None:
        domains = _detect_domains("Como reduzir custo de EC2 com Savings Plans?")
        assert "finops" in domains

    def test_detects_security_keywords(self) -> None:
        domains = _detect_domains("Política IAM permissiva no AWS")
        assert "security" in domains

    def test_detects_sre_keywords(self) -> None:
        domains = _detect_domains("Como definir SLOs para meu serviço?")
        # Round 18: 'slo' agora é detectado por 'reliability' (que também cobre SRE)
        assert "sre" in domains or "reliability" in domains

    def test_detects_kubernetes_keywords(self) -> None:
        domains = _detect_domains("Como configurar HPA no Kubernetes?")
        assert "kubernetes" in domains

    def test_detects_terraform_keywords(self) -> None:
        domains = _detect_domains("Meu arquivo .tf está com problemas")
        assert "terraform" in domains


# ─────────────────────────────────────────────────────────────────────────
# Specialist capping
# ─────────────────────────────────────────────────────────────────────────


class TestCapSpecialists:
    """Limite de 1-3 especialistas, com provedor-cloud priorizado."""

    def test_cap_3(self) -> None:
        result = _cap_specialists(["aws", "finops", "security", "sre", "terraform"], max_n=3)
        assert len(result) == 3
        # AWS (cloud_provider) deve estar primeiro
        assert result[0] == "aws"

    def test_no_cap_if_under_max(self) -> None:
        result = _cap_specialists(["aws", "finops"], max_n=3)
        assert len(result) == 2

    def test_dedup_preserving_order(self) -> None:
        result = _cap_specialists(["aws", "finops", "aws", "security"], max_n=3)
        assert len(result) == 3
        assert result.count("aws") == 1


# ─────────────────────────────────────────────────────────────────────────
# Intent classification
# ─────────────────────────────────────────────────────────────────────────


class TestClassifyIntent:
    """Classificação de intenção: KNOWLEDGE, ENVIRONMENT, COST, IAC_REVIEW, COMPARE."""

    def test_knowledge_intent(self) -> None:
        plan = classify("O que é o AWS Well-Architected Framework?")
        assert plan.intent == Intent.KNOWLEDGE
        assert "aws" in plan.clouds

    def test_knowledge_routes_to_cloud_specialist(self) -> None:
        plan = classify("Como funciona o GCP BigQuery?")
        assert "gcp" in plan.specialists

    def test_cost_intent_routes_to_finops(self) -> None:
        plan = classify("Como reduzir custo de EC2?")
        assert plan.intent == Intent.COST
        assert "finops" in plan.specialists

    def test_cost_intent_with_environment_uses_tools(self) -> None:
        plan = classify("Analise meu ambiente AWS para reduzir custos")
        assert plan.intent == Intent.COST
        assert plan.use_tools is True

    def test_iac_intent_with_payload(self) -> None:
        plan = classify("Revise essa config", has_iac_payload=True)
        assert plan.intent == Intent.IAC_REVIEW
        assert "terraform" in plan.specialists
        assert "security" in plan.specialists
        assert plan.use_inspection is True

    def test_iac_intent_with_terraform_keywords(self) -> None:
        plan = classify("Meu Terraform tem problemas de security")
        assert plan.intent == Intent.IAC_REVIEW
        assert "terraform" in plan.specialists

    def test_iac_intent_with_k8s_includes_kubernetes(self) -> None:
        plan = classify("Revise meu manifest Kubernetes")
        assert plan.intent == Intent.IAC_REVIEW
        assert "kubernetes" in plan.specialists
        assert "terraform" in plan.specialists  # também entra (cross-domain)

    def test_environment_intent_full_stack(self) -> None:
        plan = classify("Analise meu ambiente AWS")
        assert plan.intent == Intent.ENVIRONMENT
        # Cap=3: aws + finops + security (sre removido pelo cap)
        assert "aws" in plan.specialists
        assert "finops" in plan.specialists
        assert "security" in plan.specialists
        assert len(plan.specialists) == 3
        assert plan.use_tools is True

    def test_compare_intent_with_two_clouds(self) -> None:
        plan = classify("Comparar AWS Lambda vs Azure Functions")
        assert plan.intent == Intent.COMPARE
        assert "aws" in plan.clouds
        assert "azure" in plan.clouds

    def test_compare_intent_with_keyword(self) -> None:
        plan = classify("Qual a diferença entre S3 e Azure Blob?")
        assert plan.intent == Intent.COMPARE

    def test_max_3_specialists_per_query(self) -> None:
        """Garantia: nunca mais de 3 especialistas (mesmo em queries complexas)."""
        plan = classify("Analise meu ambiente AWS Kubernetes Terraform com security e SRE")
        assert len(plan.specialists) <= 3

    def test_kubernetes_query_routes_to_k8s_specialist(self) -> None:
        plan = classify("Como configurar HPA no EKS?")
        # Pode ter aws + kubernetes, mas capped em 3
        assert any(s in plan.specialists for s in ("aws", "kubernetes"))

    def test_security_query_routes_to_security_specialist(self) -> None:
        plan = classify("Como proteger meu bucket S3 com criptografia KMS?")
        assert "security" in plan.specialists

    def test_multi_domain_query(self) -> None:
        """Query com múltiplos domínios (custo + security) deve rotear para ambos."""
        plan = classify("Como economizar EC2 sem comprometer segurança?")
        # Deve pegar aws + finops + security (cap 3)
        assert "aws" in plan.specialists
        assert "finops" in plan.specialists
        assert "security" in plan.specialists
        assert len(plan.specialists) == 3

    def test_no_cloud_general_knowledge(self) -> None:
        """Pergunta genérica sem cloud não deve invocar provedor specialist."""
        plan = classify("O que é FinOps?")
        # "O que é X" é KNOWLEDGE; mas a query tem keyword "custo"? Não.
        # "FinOps" é detectado como finops domain
        assert not any(s in ("aws", "gcp", "azure") for s in plan.specialists)