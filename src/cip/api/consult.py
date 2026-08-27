"""Endpoint ``POST /consult`` — interface HTTP para cloudpilot (e outros).

Round 22+ Phase 3: CIP exposto como backend consumido por outros chats.

O cloudpilot (em D:\\cloudpilot-deploy) tem um chat que faz RAG consultando
a tabela local ``cip_cloud_docs`` (in-process). Esta rota oferece a MESMA
interface mas consultando o CIP canônico rodando em outro host/container.

Por que isto é útil:
  - Multi-tenant: cada org pode ter seu próprio CIP com corpus privado
  - Single source of truth: correções no RAG/KB propagam para todos
    os clients sem precisar de re-deploy
  - Multi-cloud: cloudpilot foca em FinOps de runtime; CIP foca em
    Well-Architected. Este endpoint junta os dois universos.

Contrato (round-trip com cloudpilot.cip_client.CipRagResult):

  Request:
    POST /consult
    Headers: Authorization: Bearer <jwt>
              X-Tenant-Id: <tenant_id>
              Content-Type: application/json
    Body:
      {
        "question": "string",               # required
        "cloud": "aws|gcp|azure",            # optional
        "service": "ec2|s3|...",             # optional
        "category": "compute|...",           # optional
        "top_k": 8,                           # optional, default 8
        "min_score": 0.80,                    # optional
        "run_id": "uuid",                     # optional, for audit correlation
        "prompt_hash": "hex16",               # optional, for audit
        "include_global": true                # optional, default true
      }

  Response (200):
      {
        "answer": "string",
        "sources": [
          {
            "cloud": "aws",
            "service": "ec2",
            "title": "...",
            "url": "https://docs.aws.amazon.com/...",
            "score": 0.85,
            "doc_id": 123,
            "source_version": "v1.0",
            "timestamp": "2024-01-15T...",
            "content_preview": "...",
            "workspace_id": null,            # null = CIP global (sem tenant)
            "is_global": true,
            "source": "aws-docs",
            "canonical_url": "https://...",
            "quarantined": false,
            "marked": false
          }
        ],
        "has_grounding": true,
        "refusal_reason": null
      }

  Response (200, sem grounding):
      {
        "answer": "",
        "sources": [],
        "has_grounding": false,
        "refusal_reason": "no_grounding_above_min_score"
      }
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cip.api._shared import get_tenant
from cip.api.auth import TenantContext
from cip.logging import get_logger
from cip.observability import observe_chat_latency

log = get_logger(__name__)

router = APIRouter(tags=["cip-consult"])


# ─────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────


class ConsultReq(BaseModel):
    """Body do endpoint /consult."""

    question: str = Field(..., min_length=1, max_length=4000, description="Pergunta ao CIP")
    cloud: str | None = Field(default=None, description="aws|gcp|azure")
    service: str | None = Field(default=None, description="ec2, s3, lambda, etc.")
    category: str | None = Field(default=None, description="compute, storage, etc.")
    top_k: int = Field(default=8, ge=1, le=20)
    min_score: float = Field(default=0.80, ge=0.0, le=1.0)
    run_id: str | None = Field(default=None, description="UUID para auditoria")
    prompt_hash: str | None = Field(default=None, description="SHA-256 hex (16 chars)")
    include_global: bool = Field(default=True, description="Se true, busca também no corpus global")


class ConsultSource(BaseModel):
    """Shape de source retornado por /consult (espelha CipRagResult do cloudpilot)."""

    cloud: str | None = None
    service: str | None = None
    title: str | None = None
    url: str | None = None
    score: float | None = None
    doc_id: int | None = None
    source_version: str | None = None
    timestamp: str | None = None
    content_preview: str | None = None
    workspace_id: str | None = None
    is_global: bool = True
    source: str | None = None
    canonical_url: str | None = None
    quarantined: bool = False
    marked: bool = False


class ConsultOut(BaseModel):
    """Resposta do /consult (idêntica ao CipRagResult do cloudpilot)."""

    answer: str = ""
    sources: list[ConsultSource] = []
    has_grounding: bool = False
    refusal_reason: str | None = None
    run_id: str | None = None
    latency_ms: int = 0


# ─────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────


@router.post(
    "/consult",
    response_model=ConsultOut,
    summary="Consulta RAG no CIP canônico (HTTP — substitui in-process)",
)
async def consult(
    req: ConsultReq,
    ctx: TenantContext = Depends(get_tenant),
) -> ConsultOut:
    """Consulta RAG no CIP, retornando shape idêntico ao CipRagResult.

    Usado pelo cloudpilot e por outros clientes HTTP que querem consumir
    o CIP sem acoplamento in-process.
    """
    from cip.rag.engine import get_engine

    t0 = time.perf_counter()
    try:
        engine = get_engine()
        result = await engine.query(
            req.question,
            cloud=req.cloud,
            service=req.service,
            category=req.category,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("consult_engine_error", question=req.question[:80])
        raise HTTPException(status_code=500, detail=f"consult failed: {exc}")

    latency_ms = int((time.perf_counter() - t0) * 1000)
    observe_chat_latency("consult", ctx.tenant_id, latency_ms / 1000.0)

    # Converte Source → ConsultSource
    sources = [
        ConsultSource(
            cloud=s.cloud,
            service=s.service,
            title=s.title,
            url=s.url,
            score=float(s.score) if s.score is not None else None,
            doc_id=s.doc_id,
            source_version=s.source_version,
            timestamp=s.timestamp,
            content_preview=s.content_preview,
            workspace_id=s.workspace_id,
            is_global=s.is_global,
            source=s.source,
            canonical_url=s.canonical_url,
            quarantined=s.quarantined,
            marked=s.marked,
        )
        for s in (result.sources or [])
    ]

    log.info(
        "consult_completed",
        tenant_id=ctx.tenant_id,
        question_len=len(req.question),
        n_sources=len(sources),
        has_grounding=result.has_grounding,
        latency_ms=latency_ms,
        run_id=req.run_id,
    )

    return ConsultOut(
        answer=result.answer or "",
        sources=sources,
        has_grounding=result.has_grounding,
        refusal_reason=getattr(result, "refusal_reason", None),
        run_id=req.run_id or str(uuid.uuid4()),
        latency_ms=latency_ms,
    )
