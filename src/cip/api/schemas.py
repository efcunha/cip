"""Schemas de request/response da API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from cip.config import CloudName


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, examples=["Como reduzir custo de um bucket S3 com dados frios?"])
    cloud: CloudName | None = None
    service: str | None = None
    category: str | None = None


class SourceOut(BaseModel):
    cloud: str | None = None
    service: str | None = None
    title: str | None = None
    url: str | None = None
    score: float | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceOut] = Field(default_factory=list)
    has_grounding: bool = True


class AnalyzeRequest(BaseModel):
    question: str = Field(..., min_length=3)
    cloud: CloudName | None = None
    iac_payload: str | None = Field(
        default=None,
        description="Conteúdo de Terraform (.tf) ou manifesto Kubernetes (YAML) a inspecionar.",
    )
    react_mode: bool | None = Field(
        default=None,
        description="Forçar modo ReAct (LLM raciocina + chama tools). Default: usa env var CIP_REACT_MODE.",
    )


class FindingOut(BaseModel):
    title: str
    severity: str
    domain: str
    description: str
    recommendation: str
    financial_impact_usd: float | None = None
    effort: str | None = None
    references: list[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    summary: str
    intent: str | None = None
    clouds: list[str] = Field(default_factory=list)
    findings: list[FindingOut] = Field(default_factory=list)
    sources: list[SourceOut] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────
# Auth schemas (Fase 6 — Production Hardening)
# ─────────────────────────────────────────────────────────────────────────


class AuthInfo(BaseModel):
    """Metadata do tenant autenticado (retornado no header X-Tenant-Info)."""

    tenant_id: str
    rate_limit_rpm: int
    authenticated: bool


class HealthResponse(BaseModel):
    """Resposta do /health (público, sem auth)."""

    status: str
    version: str
    env: str
    readonly: bool