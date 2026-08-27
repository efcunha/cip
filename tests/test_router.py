"""Testes do classificador de intenção (não requer LLM nem banco)."""

from cip.agents.models import Intent
from cip.agents.router import classify


def test_cost_environment_uses_tools():
    plan = classify("Analise meu ambiente AWS e diga onde economizar custos")
    assert plan.intent in {Intent.COST, Intent.ENVIRONMENT}
    assert "aws" in plan.clouds
    assert plan.use_tools is True


def test_iac_review_detected_by_payload():
    plan = classify("Revise isto", has_iac_payload=True)
    assert plan.intent == Intent.IAC_REVIEW
    assert plan.use_inspection is True


def test_compare_multiple_clouds():
    plan = classify("Compare GKE vs EKS vs AKS")
    assert plan.intent == Intent.COMPARE
    assert set(["aws", "gcp", "azure"]).issubset(set(plan.clouds)) or len(plan.clouds) >= 2


def test_pure_knowledge():
    plan = classify("O que é uma VPC?")
    assert plan.intent == Intent.KNOWLEDGE
    assert plan.use_tools is False
