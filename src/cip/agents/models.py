"""Modelos de domínio compartilhados (findings, plano de análise, resultado)."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]
Effort = Literal["low", "medium", "high"]
Domain = Literal["finops", "security", "reliability", "performance", "operations"]


class Intent(str, Enum):
    KNOWLEDGE = "knowledge"          # pergunta conceitual → só RAG
    ENVIRONMENT = "environment"      # analisar ambiente real → tools + RAG
    COST = "cost"                    # foco custo → tools de custo + FinOps
    IAC_REVIEW = "iac_review"        # revisar Terraform/K8s → Inspection Engine
    COMPARE = "compare"              # comparar clouds → RAG multi-cloud


class Finding(BaseModel):
    title: str
    severity: Severity
    domain: Domain
    description: str
    recommendation: str
    financial_impact_usd: float | None = None
    effort: Effort | None = None
    references: list[str] = Field(default_factory=list)

    @property
    def roi_score(self) -> float:
        """Prioridade simples: impacto / esforço (maior = mais prioritário)."""
        weight = {"low": 1.0, "medium": 2.0, "high": 3.0}
        impact = self.financial_impact_usd or 0.0
        return impact / weight.get(self.effort or "medium", 2.0)


class AnalysisPlan(BaseModel):
    intent: Intent
    clouds: list[str] = Field(default_factory=list)
    specialists: list[str] = Field(default_factory=list)
    use_tools: bool = False
    use_inspection: bool = False


class AnalysisResult(BaseModel):
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    plan: AnalysisPlan | None = None
    fallback: str | None = None  # motivo do fallback extrativo (LLM local)

    def prioritized_findings(self) -> list[Finding]:
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(
            self.findings,
            key=lambda f: (order[f.severity], -f.roi_score),
        )
