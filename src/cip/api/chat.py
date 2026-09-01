"""Chat multi-turn + feedback loop — Round 22+.

Endpoints:
  POST   /chat/conversations            Criar nova conversa (título opcional)
  GET    /chat/conversations            Listar conversas do tenant
  GET    /chat/conversations/{id}       Detalhes + histórico
  DELETE /chat/conversations/{id}       Remove conversa + cascata messages
  POST   /chat/conversations/{id}/messages  Adicionar pergunta (executa /ask com histórico)
  POST   /chat/conversations/{id}/messages?stream=true  Stream SSE multi-turn
  GET    /chat/conversations/{id}/export  Exporta md ou json
  POST   /chat/conversations/{id}/share   Gera link público (read-only token)
  GET    /chat/share/{token}            Acessa conversa via share token
  POST   /chat/messages/{id}/feedback   Thumbs up/down em uma resposta
  WS     /ws/chat                       WebSocket para notificações (ver _ws.py)

Schema (db/migrations/003_conversations_and_feedback.sql):
  - conversations: id, tenant_id, user_id, title, created_at, updated_at, metadata
  - messages: id, conversation_id, role, content, sources, findings, plan,
              tools_used, latency_ms, model_name, cost_estimated_usd,
              feedback (up/down/null), feedback_note, feedback_at
  - share_tokens: token, conversation_id, created_at, expires_at (opcional)

Por que multi-turn:
  - UX: usuário refina a pergunta ("Como faço isso no Terraform?")
    sem repetir contexto. LLM recebe histórico como system message.
  - Auditoria: persistir conversas ajuda a debugar respostas ruins.
  - Feedback: correlacionar 👍/👎 com mensagens permite treinar/improve.

Isolamento:
  - tenant_id em TODA query (multi-tenant safe)
  - authorization: o caller deve conhecer conversation_id E tenant_id.
    Se tentar acessar conversa de outro tenant → 404 (não 403, evita leak).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cip.agents.models import AnalysisPlan
from cip.api._shared import get_tenant
from cip.api.auth import TenantContext
from cip.api.streaming import (
    EVENT_CHUNK,
    EVENT_DONE,
    EVENT_ERROR,
    format_sse_event,
    stream_text,
)
from cip.api.ws import notify_feedback_changed, notify_message_added
from cip.logging import get_logger
from cip.observability import (
    observe_chat_latency,
    record_chat_conversation_created,
    record_chat_feedback,
    record_chat_message_created,
)
from cip.rag.engine import RagResult

log = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ─────────────────────────────────────────────────────────────────────────
# Schemas (request/response)
# ─────────────────────────────────────────────────────────────────────────


class CreateConversationReq(BaseModel):
    """Body para criar uma conversa."""

    title: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageOut(BaseModel):
    """Representação de uma mensagem na resposta HTTP."""

    id: str
    conversation_id: str
    role: str
    content: str
    sources: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    tools_used: list[str] = []
    plan: dict[str, Any] | None = None
    latency_ms: int | None = None
    model_name: str | None = None
    cost_estimated_usd: float | None = None
    feedback: str | None = None
    feedback_note: str | None = None
    feedback_at: str | None = None
    created_at: str


class ConversationOut(BaseModel):
    """Representação de uma conversa."""

    id: str
    tenant_id: str
    title: str | None
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = {}
    # Mensagens (incluídas só se ?include=messages ou no detail endpoint)
    messages: list[MessageOut] | None = None


class ConversationListOut(BaseModel):
    items: list[ConversationOut]
    total: int


class AskInConversationReq(BaseModel):
    """Body para enviar uma pergunta numa conversa."""

    question: str = Field(..., min_length=1, max_length=4000)
    cloud: str | None = Field(default=None, description="aws/gcp/azure/multi")
    iac_payload: str | None = Field(default=None, description="Para /analyze")
    use_tools: bool = False
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeedbackReq(BaseModel):
    """Body para registrar feedback (👍/👎) em uma mensagem."""

    feedback: str = Field(..., pattern="^(up|down)$")
    note: str | None = Field(default=None, max_length=2000)


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _conversation_to_dict(row: Any, messages: list[dict] | None = None) -> dict[str, Any]:
    """Converte row do DB em dict pronto para response."""
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "title": row.title,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "metadata": row.metadata or {},
        "messages": messages,
    }


def _message_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "role": row.role,
        "content": row.content,
        "sources": row.sources or [],
        "findings": row.findings or [],
        "tools_used": row.tools_used or [],
        "plan": row.plan,
        "latency_ms": row.latency_ms,
        "model_name": row.model_name,
        "cost_estimated_usd": float(row.cost_estimated_usd) if row.cost_estimated_usd else None,
        "feedback": row.feedback,
        "feedback_note": row.feedback_note,
        "feedback_at": row.feedback_at.isoformat() if row.feedback_at else None,
        "created_at": row.created_at.isoformat(),
    }


async def _ensure_conversation_belongs_to_tenant(
    db: Any, conversation_id: str, tenant_id: str
) -> Any:
    """Busca conversa garantindo tenant. 404 se não existir OU for de outro tenant."""
    from sqlalchemy import text

    row = (
        await db.execute(
            text(
                "SELECT id, tenant_id, title, created_at, updated_at, metadata "
                "FROM conversations WHERE id = :id AND tenant_id = :tenant"
            ),
            {"id": conversation_id, "tenant": tenant_id},
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="conversation not found")
    return row


def _history_to_context(messages: list[Any], max_chars: int = 4000) -> str:
    """Formata histórico recente como system message para o LLM."""
    # Pega as últimas N mensagens do assistant/user (excluindo system)
    recent = [m for m in messages if m.role in ("user", "assistant")][-10:]
    if not recent:
        return ""
    lines = ["[HISTÓRICO DA CONVERSA]"]
    for m in recent:
        role = "Usuário" if m.role == "user" else "Assistente"
        content = m.content[:500]  # truncate para não estourar context
        lines.append(f"{role}: {content}")
    lines.append("[FIM DO HISTÓRICO]")
    ctx = "\n".join(lines)
    if len(ctx) > max_chars:
        ctx = ctx[-max_chars:]
        ctx = "...\n" + ctx
    return ctx


# ─────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    req: CreateConversationReq,
    request: Request,
    ctx: TenantContext = Depends(get_tenant),
) -> Any:
    """Cria uma conversa vazia (título opcional — auto-gerado depois)."""
    from sqlalchemy import text

    tenant_id = ctx.tenant_id
    conv_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    db = request.app.state.db
    await db.execute(
        text(
            "INSERT INTO conversations (id, tenant_id, title, created_at, updated_at, metadata) "
            "VALUES (:id, :tenant, :title, :now, :now, :metadata)"
        ),
        {
            "id": conv_id,
            "tenant": tenant_id,
            "title": req.title,
            "now": now,
            "metadata": json.dumps(req.metadata),
        },
    )
    await db.commit()

    record_chat_conversation_created(tenant_id)
    log.info("conversation_created", tenant_id=tenant_id, conv_id=conv_id)
    return _conversation_to_dict(
        type("Row", (), {
            "id": conv_id, "tenant_id": tenant_id, "title": req.title,
            "created_at": now, "updated_at": now, "metadata": req.metadata,
        })(),
        messages=[],
    )


@router.get("/conversations", response_model=ConversationListOut)
async def list_conversations(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    ctx: TenantContext = Depends(get_tenant),
) -> Any:
    """Lista conversas do tenant ordenadas por updated_at DESC."""
    from sqlalchemy import text

    tenant_id = ctx.tenant_id
    limit = min(limit, 200)
    db = request.app.state.db

    rows = (
        await db.execute(
            text(
                "SELECT id, tenant_id, title, created_at, updated_at, metadata "
                "FROM conversations WHERE tenant_id = :tenant "
                "ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
            ),
            {"tenant": tenant_id, "limit": limit, "offset": offset},
        )
    ).all()
    total = (
        await db.execute(
            text("SELECT count(*) FROM conversations WHERE tenant_id = :tenant"),
            {"tenant": tenant_id},
        )
    ).scalar()

    return {
        "items": [_conversation_to_dict(r, messages=None) for r in rows],
        "total": total,
    }


@router.get("/conversations/{conv_id}", response_model=ConversationOut)
async def get_conversation(conv_id: str, request: Request, ctx: TenantContext = Depends(get_tenant)) -> Any:
    """Detalhe + histórico completo de mensagens."""
    from sqlalchemy import text

    tenant_id = ctx.tenant_id
    db = request.app.state.db

    conv_row = await _ensure_conversation_belongs_to_tenant(db, conv_id, tenant_id)

    msg_rows = (
        await db.execute(
            text(
                "SELECT id, conversation_id, role, content, sources, findings, "
                "plan, tools_used, latency_ms, model_name, cost_estimated_usd, "
                "feedback, feedback_note, feedback_at, created_at "
                "FROM messages WHERE conversation_id = :id ORDER BY created_at ASC"
            ),
            {"id": conv_id},
        )
    ).all()

    return _conversation_to_dict(conv_row, messages=[_message_to_dict(m) for m in msg_rows])


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(conv_id: str, request: Request, ctx: TenantContext = Depends(get_tenant)) -> None:
    """Remove conversa + cascade delete em messages."""
    from sqlalchemy import text

    tenant_id = ctx.tenant_id
    db = request.app.state.db
    await _ensure_conversation_belongs_to_tenant(db, conv_id, tenant_id)

    await db.execute(
        text("DELETE FROM conversations WHERE id = :id"),
        {"id": conv_id},
    )
    await db.commit()
    log.info("conversation_deleted", tenant_id=tenant_id, conv_id=conv_id)


@router.post(
    "/conversations/{conv_id}/messages",
    response_model=MessageOut,
    status_code=201,
)
async def ask_in_conversation(
    conv_id: str,
    req: AskInConversationReq,
    request: Request,
    ctx: TenantContext = Depends(get_tenant),
) -> Any:
    """Adiciona pergunta + retorna resposta do orchestrator (com histórico).

    Fluxo:
      1. Verifica que conversa existe e é do tenant
      2. Carrega histórico (últimas 10 mensagens)
      3. Persiste a pergunta (role=user)
      4. Chama orchestrator com histórico como system message extra
      5. Persiste a resposta (role=assistant) com sources/findings/plan
      6. Atualiza título da conversa (se primeira msg e sem título)
      7. Retorna a mensagem do assistant

    Round 22+ streaming: se req.stream=True, retorna StreamingResponse SSE.
    Resposta do LLM é chunked (50 chars / 20ms) simulando token-by-token.
    Em produção, substituir stream_text() por orquestrador com LLM que suporte
    stream_generate (ex.: OpenAI streaming mode).
    """
    from sqlalchemy import text

    tenant_id = ctx.tenant_id

    # ── Se streaming, delega para a versão SSE ──────────────────────
    if req.stream:
        return await _ask_in_conversation_stream(conv_id, req, request, ctx)

    # ── (código non-streaming continua) ─────────────────────────────
    db = request.app.state.db
    conv_row = await _ensure_conversation_belongs_to_tenant(db, conv_id, tenant_id)

    # ── Busca histórico ─────────────────────────────────────────────
    history_rows = (
        await db.execute(
            text(
                "SELECT id, role, content FROM messages "
                "WHERE conversation_id = :id ORDER BY created_at DESC LIMIT 10"
            ),
            {"id": conv_id},
        )
    ).all()
    history_ctx = _history_to_context(list(reversed(history_rows)))

    # ── Persiste pergunta do user ────────────────────────────────────
    user_msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO messages (id, conversation_id, tenant_id, role, content, created_at, metadata) "
            "VALUES (:id, :cid, :tenant, 'user', :content, :now, :metadata)"
        ),
        {
            "id": user_msg_id, "cid": conv_id, "tenant": tenant_id,
            "content": req.question, "now": now, "metadata": json.dumps(req.metadata),
        },
    )
    await db.commit()

    # ── Chama orchestrator com histórico injetado ─────────────────
    orchestrator = request.app.state.orchestrator
    augmented_question = req.question
    if history_ctx:
        augmented_question = f"{history_ctx}\n\n[PERGUNTA ATUAL]\n{req.question}"

    t0 = time.perf_counter()
    try:
        # /analyze se iac_payload, /ask caso contrário
        if req.iac_payload:
            result = await orchestrator.handle(
                augmented_question, cloud=req.cloud, iac_payload=req.iac_payload,
            )
        else:
            result = await orchestrator.handle(augmented_question, cloud=req.cloud)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001
        log.exception("orchestrator_failed_in_conversation", conv_id=conv_id)
        raise HTTPException(status_code=500, detail=f"orchestrator error: {exc}")

    # ── Persiste resposta do assistant ─────────────────────────────
    answer = getattr(result, "summary", "") or ""
    sources = getattr(result, "sources", []) or []
    sources_dict = [
        getattr(s, "__dict__", {}) if hasattr(s, "__dict__") else (s if isinstance(s, dict) else {})
        for s in sources
    ]
    findings_list = [
        f.__dict__ if hasattr(f, "__dict__") else f
        for f in (getattr(result, "findings", []) or [])
    ]
    plan_obj = getattr(result, "plan", None)
    plan_dict = plan_obj.__dict__ if plan_obj and hasattr(plan_obj, "__dict__") else None

    asst_msg_id = str(uuid.uuid4())
    asst_now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO messages "
            "(id, conversation_id, tenant_id, role, content, sources, findings, "
            " plan, tools_used, latency_ms, model_name, cost_estimated_usd, created_at) "
            "VALUES (:id, :cid, :tenant, 'assistant', :content, "
            "        :sources::jsonb, :findings::jsonb, :plan::jsonb, "
            "        :tools::jsonb, :lat, :model, 0.0, :now)"
        ),
        {
            "id": asst_msg_id, "cid": conv_id, "tenant": tenant_id,
            "content": answer,
            "sources": json.dumps(sources_dict),
            "findings": json.dumps(findings_list),
            "plan": json.dumps(plan_dict) if plan_dict else None,
            "tools": json.dumps(getattr(result, "tools_used", []) or []),
            "lat": elapsed_ms,
            "model": (plan_dict or {}).get("model_name") if plan_dict else None,
            "now": asst_now,
        },
    )

    # ── Auto-gera título se for a primeira mensagem ────────────────
    title_row = (
        await db.execute(
            text("SELECT title FROM conversations WHERE id = :id"),
            {"id": conv_id},
        )
    ).first()
    if not title_row.title:
        # Usa primeiros 80 chars da pergunta como título
        await db.execute(
            text("UPDATE conversations SET title = :title WHERE id = :id"),
            {"title": req.question[:80], "id": conv_id},
        )

    await db.commit()

    # Métricas Prometheus
    record_chat_message_created(tenant_id, "user")
    record_chat_message_created(tenant_id, "assistant")
    observe_chat_latency("chat_message", tenant_id, elapsed_ms / 1000.0)

    log.info(
        "conversation_message_added",
        tenant_id=tenant_id,
        conv_id=conv_id,
        user_msg_id=user_msg_id,
        assistant_msg_id=asst_msg_id,
        latency_ms=elapsed_ms,
    )

    # WebSocket push (fire-and-forget)
    try:
        await notify_message_added(
            tenant_id, conv_id, _message_to_dict(_FakeMsg(
                id=asst_msg_id, conversation_id=conv_id, role="assistant",
                content=answer, sources=sources_dict, findings=findings_list,
                tools_used=getattr(result, "tools_used", []) or [],
                plan=plan_dict, latency_ms=elapsed_ms,
                model_name=(plan_dict or {}).get("model_name") if plan_dict else None,
                cost_estimated_usd=0.0,
                feedback=None, feedback_note=None, feedback_at=None,
                created_at=asst_now,
            )),
        )
    except Exception:  # noqa: BLE001
        log.warning("ws_notify_failed", conv_id=conv_id)

    return _message_to_dict(_FakeMsg(
        id=asst_msg_id, conversation_id=conv_id, role="assistant",
        content=answer, sources=sources_dict, findings=findings_list,
        tools_used=getattr(result, "tools_used", []) or [],
        plan=plan_dict, latency_ms=elapsed_ms,
        model_name=(plan_dict or {}).get("model_name") if plan_dict else None,
        cost_estimated_usd=0.0,
        feedback=None, feedback_note=None, feedback_at=None,
        created_at=asst_now,
    ))


class _FakeMsg:
    """Dataclass-like simples para _message_to_dict (evita ORM session em memória)."""
    __slots__ = ("id", "conversation_id", "role", "content", "sources", "findings",
                 "tools_used", "plan", "latency_ms", "model_name",
                 "cost_estimated_usd", "feedback", "feedback_note",
                 "feedback_at", "created_at")
    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            super().__setattr__(k, v)


@router.post("/messages/{msg_id}/feedback", status_code=200)
async def submit_feedback(
    msg_id: str,
    req: FeedbackReq,
    request: Request,
    ctx: TenantContext = Depends(get_tenant),
) -> dict[str, Any]:
    """Registra 👍/👎 em uma mensagem específica.

    Útil para:
      - Identificar respostas ruins para melhorar o prompt/specialist
      - Coletar dataset de feedback para fine-tuning futuro
      - Auditoria: "por que o usuário não gostou desta resposta?"
    """
    from sqlalchemy import text

    tenant_id = ctx.tenant_id
    db = request.app.state.db

    # Verifica que a mensagem existe E é do tenant (através da conversation)
    msg_row = (
        await db.execute(
            text(
                "SELECT m.id, m.conversation_id FROM messages m "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.id = :mid AND c.tenant_id = :tenant"
            ),
            {"mid": msg_id, "tenant": tenant_id},
        )
    ).first()
    if not msg_row:
        raise HTTPException(status_code=404, detail="message not found")

    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "UPDATE messages SET feedback = :fb, feedback_note = :note, feedback_at = :now "
            "WHERE id = :mid"
        ),
        {
            "fb": req.feedback, "note": req.note, "now": now, "mid": msg_id,
        },
    )
    await db.commit()

    record_chat_feedback(tenant_id, req.feedback)
    log.info(
        "feedback_submitted",
        tenant_id=tenant_id,
        msg_id=msg_id,
        feedback=req.feedback,
    )

    # WebSocket push
    try:
        await notify_feedback_changed(tenant_id, msg_row.conversation_id, msg_id, req.feedback)
    except Exception:  # noqa: BLE001
        log.warning("ws_notify_failed", msg_id=msg_id)
    return {
        "msg_id": msg_id,
        "feedback": req.feedback,
        "feedback_at": now.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────
# Streaming multi-turn (SSE)
# ─────────────────────────────────────────────────────────────────────────


async def _ask_in_conversation_stream(
    conv_id: str,
    req: AskInConversationReq,
    request: Request,
    ctx: TenantContext,
) -> StreamingResponse:
    """Versão SSE do ask_in_conversation.

    Fluxo:
      1. Persiste user message (igual ao non-streaming)
      2. Carrega histórico (10 últimas mensagens)
      3. Roda orchestrator (modo streaming se disponível)
      4. SSE chunks progressivos (`event: chunk`)
      5. Persiste assistant message com texto completo (no fim)
      6. SSE done com msg_id + sources + latency

    Nota sobre streaming real vs chunked:
      - O orchestrator atual não tem modo streaming (chama acomplete()).
      - Aqui chunkamos a resposta completa em pedaços de 50 chars/20ms,
        simulando o que seria token-by-token com um LLM que suportasse
        stream_generate. Trocar por orchestrator.handle_stream() quando
        disponível.
    """
    from sqlalchemy import text

    tenant_id = ctx.tenant_id
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator

    # ── 1. Valida conversa ────────────────────────────────────────
    await _ensure_conversation_belongs_to_tenant(db, conv_id, tenant_id)

    # ── 2. Carrega histórico ──────────────────────────────────────
    history_rows = (
        await db.execute(
            text(
                "SELECT id, role, content FROM messages "
                "WHERE conversation_id = :id ORDER BY created_at DESC LIMIT 10"
            ),
            {"id": conv_id},
        )
    ).all()
    history_ctx = _history_to_context(list(reversed(history_rows)))

    # ── 3. Persiste user message ──────────────────────────────────
    user_msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO messages (id, conversation_id, tenant_id, role, content, created_at, metadata) "
            "VALUES (:id, :cid, :tenant, 'user', :content, :now, :metadata)"
        ),
        {
            "id": user_msg_id, "cid": conv_id, "tenant": tenant_id,
            "content": req.question, "now": now, "metadata": json.dumps(req.metadata),
        },
    )
    await db.commit()

    augmented_question = req.question
    if history_ctx:
        augmented_question = f"{history_ctx}\n\n[PERGUNTA ATUAL]\n{req.question}"

    # ── 4. Generator SSE ─────────────────────────────────────────
    async def event_stream():
        # Header SSE explícito (alguns proxies precisam)
        yield ": SSE stream started\n\n"

        # 4a. Roda orchestrator (aguarda resposta completa)
        t0 = time.perf_counter()
        try:
            result = await orchestrator.handle(augmented_question, cloud=req.cloud)
        except Exception as exc:  # noqa: BLE001
            log.exception("orchestrator_failed_in_stream", conv_id=conv_id)
            yield format_sse_event(EVENT_ERROR, {
                "code": "orchestrator_failed",
                "message": f"{type(exc).__name__}: {str(exc)[:200]}",
            })
            return

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        answer = getattr(result, "summary", "") or ""
        sources = getattr(result, "sources", []) or []
        sources_dict = [
            getattr(s, "__dict__", {}) if hasattr(s, "__dict__") else (
                s if isinstance(s, dict) else {}
            )
            for s in sources
        ]
        findings_list = [
            f.__dict__ if hasattr(f, "__dict__") else f
            for f in (getattr(result, "findings", []) or [])
        ]
        plan_obj = getattr(result, "plan", None)
        plan_dict = plan_obj.__dict__ if plan_obj and hasattr(plan_obj, "__dict__") else None

        # 4b. Stream chunks da resposta (simulando token-by-token)
        async for chunk in stream_text(answer, chunk_size=50, delay_ms=20):
            yield format_sse_event(EVENT_CHUNK, {"delta": chunk})

        # 4c. Persiste assistant message (com texto completo)
        asst_msg_id = str(uuid.uuid4())
        asst_now = datetime.now(timezone.utc)
        await db.execute(
            text(
                "INSERT INTO messages "
                "(id, conversation_id, tenant_id, role, content, sources, findings, "
                " plan, tools_used, latency_ms, model_name, cost_estimated_usd, created_at) "
                "VALUES (:id, :cid, :tenant, 'assistant', :content, "
                "        :sources::jsonb, :findings::jsonb, :plan::jsonb, "
                "        :tools::jsonb, :lat, :model, 0.0, :now)"
            ),
            {
                "id": asst_msg_id, "cid": conv_id, "tenant": tenant_id,
                "content": answer,
                "sources": json.dumps(sources_dict),
                "findings": json.dumps(findings_list),
                "plan": json.dumps(plan_dict) if plan_dict else None,
                "tools": json.dumps(getattr(result, "tools_used", []) or []),
                "lat": elapsed_ms,
                "model": (plan_dict or {}).get("model_name") if plan_dict else None,
                "now": asst_now,
            },
        )

        # 4d. Auto-titulo se primeira msg
        title_row = (
            await db.execute(
                text("SELECT title FROM conversations WHERE id = :id"),
                {"id": conv_id},
            )
        ).first()
        if not title_row.title:
            await db.execute(
                text("UPDATE conversations SET title = :title WHERE id = :id"),
                {"title": req.question[:80], "id": conv_id},
            )
        await db.commit()

        # 4e. SSE done com metadata final
        yield format_sse_event(EVENT_DONE, {
            "msg_id": asst_msg_id,
            "user_msg_id": user_msg_id,
            "conversation_id": conv_id,
            "answer": answer,
            "sources": sources_dict,
            "findings": findings_list,
            "plan": plan_dict,
            "tools_used": getattr(result, "tools_used", []) or [],
            "latency_ms": elapsed_ms,
            "model_name": (plan_dict or {}).get("model_name") if plan_dict else None,
        })

        log.info(
            "conversation_stream_completed",
            tenant_id=tenant_id,
            conv_id=conv_id,
            user_msg_id=user_msg_id,
            assistant_msg_id=asst_msg_id,
            latency_ms=elapsed_ms,
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx: desativa buffering
            "Connection": "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────
# Export (markdown / json) + share link
# ─────────────────────────────────────────────────────────────────────────


@router.get("/conversations/{conv_id}/export")
async def export_conversation(
    conv_id: str,
    request: Request,
    format: str = "md",  # md | json
    ctx: TenantContext = Depends(get_tenant),
) -> Any:
    """Exporta conversa em markdown ou JSON.

    Formatos:
      - md  → markdown legível (titulo + mensagens + sources como footnotes)
      - json → dump completo com metadados (recomendado para arquivamento)
    """
    from fastapi.responses import PlainTextResponse, JSONResponse
    from sqlalchemy import text

    tenant_id = ctx.tenant_id
    db = request.app.state.db
    conv_row = await _ensure_conversation_belongs_to_tenant(db, conv_id, tenant_id)

    msg_rows = (
        await db.execute(
            text(
                "SELECT id, role, content, sources, plan, tools_used, "
                "latency_ms, model_name, feedback, feedback_note, created_at "
                "FROM messages WHERE conversation_id = :id ORDER BY created_at ASC"
            ),
            {"id": conv_id},
        )
    ).all()

    if format == "json":
        return JSONResponse(
            {
                "conversation": _conversation_to_dict(conv_row),
                "messages": [_message_to_dict(m) for m in msg_rows],
                "exported_at": datetime.now(timezone.utc).isoformat(),
            },
            headers={"Content-Disposition": f'attachment; filename="cip-{conv_id}.json"'},
        )

    # Default: markdown
    title = conv_row.title or "(sem título)"
    md_lines = [
        f"# {title}",
        "",
        f"**Tenant**: `{tenant_id}`  ",
        f"**Conversa**: `{conv_id}`  ",
        f"**Criada em**: {conv_row.created_at.isoformat()}  ",
        f"**Exportada em**: {datetime.now(timezone.utc).isoformat()}",
        "",
        "---",
        "",
    ]
    for i, m in enumerate(msg_rows, 1):
        if m.role == "user":
            md_lines.append(f"## 👤 Usuário")
            md_lines.append("")
            md_lines.append(m.content)
        else:
            md_lines.append(f"## 🤖 CIP")
            md_lines.append("")
            md_lines.append(m.content)
            # Metadata da resposta
            if m.latency_ms:
                md_lines.append("")
                md_lines.append(f"_Latência: {m.latency_ms / 1000:.1f}s_  ")
            if m.model_name:
                md_lines.append(f"_Modelo: {m.model_name}_  ")
            if m.tools_used:
                md_lines.append(f"_Tools: {', '.join(m.tools_used)}_  ")
            if m.feedback == "up":
                md_lines.append("_Feedback: 👍 útil_  ")
            elif m.feedback == "down":
                md_lines.append(f"_Feedback: 👎 não útil ({m.feedback_note or 'sem nota'})_  ")
            # Sources como footnotes
            if m.sources:
                md_lines.append("")
                md_lines.append("**Fontes:**")
                md_lines.append("")
                for j, s in enumerate(m.sources, 1):
                    if isinstance(s, dict):
                        url = s.get("url", "")
                        title = s.get("title", "(sem título)")
                        cloud = s.get("cloud", "?")
                        service = s.get("service", "?")
                        md_lines.append(f"{j}. [{cloud}/{service}] [{title}]({url})")
        md_lines.append("")

    return PlainTextResponse(
        "\n".join(md_lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="cip-{conv_id}.md"'},
    )


class ShareConversationReq(BaseModel):
    """Body para gerar link de compartilhamento."""

    expires_hours: int | None = Field(default=None, ge=1, le=8760, description="TTL do link")
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/conversations/{conv_id}/share", status_code=201)
async def create_share_link(
    conv_id: str,
    req: ShareConversationReq,
    request: Request,
    ctx: TenantContext = Depends(get_tenant),
) -> dict[str, Any]:
    """Gera link público read-only para a conversa.

    Returns: {share_url, token, expires_at}
    O cliente recebe um `token` (UUIDv4) que pode ser usado em
    GET /chat/share/{token} (sem precisar de auth).
    """
    from datetime import timedelta
    from sqlalchemy import text

    tenant_id = ctx.tenant_id
    db = request.app.state.db
    conv_row = await _ensure_conversation_belongs_to_tenant(db, conv_id, tenant_id)

    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = None
    if req.expires_hours:
        expires_at = now + timedelta(hours=req.expires_hours)

    await db.execute(
        text(
            "INSERT INTO share_tokens (token, conversation_id, tenant_id, created_at, expires_at, metadata) "
            "VALUES (:token, :cid, :tenant, :now, :exp, :metadata)"
        ),
        {
            "token": token, "cid": conv_id, "tenant": tenant_id,
            "now": now, "exp": expires_at, "metadata": json.dumps(req.metadata),
        },
    )
    await db.commit()

    log.info("share_link_created", tenant_id=tenant_id, conv_id=conv_id, token=token)
    return {
        "token": token,
        "share_url": f"/chat/share/{token}",  # frontend converte p/ URL absoluto
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": now.isoformat(),
    }


# Endpoint público (NÃO precisa de auth)
public_router = APIRouter(prefix="/chat", tags=["chat-public"])


@public_router.get("/share/{token}")
async def get_shared_conversation(token: str, request: Request) -> Any:
    """Acessa conversa compartilhada via token (read-only, sem auth).

    Incrementa access_count. Retorna 410 Gone se revogado ou expirado.
    """
    from fastapi import HTTPException as HTTPEx
    from sqlalchemy import text

    # Sem Depends(get_tenant) — endpoint público. O DB vem do Request injetado.
    db = request.app.state.db

    row = (
        await db.execute(
            text(
                "SELECT conversation_id, expires_at, revoked_at "
                "FROM share_tokens WHERE token = :token"
            ),
            {"token": token},
        )
    ).first()
    if not row:
        raise HTTPEx(status_code=404, detail="share link not found")
    if row.revoked_at:
        raise HTTPEx(status_code=410, detail="share link revoked")
    if row.expires_at and row.expires_at < datetime.now(timezone.utc):
        raise HTTPEx(status_code=410, detail="share link expired")

    # Incrementa counter
    await db.execute(
        text("UPDATE share_tokens SET access_count = access_count + 1 WHERE token = :token"),
        {"token": token},
    )
    await db.commit()

    # Retorna conversa
    conv_row = (
        await db.execute(
            text(
                "SELECT id, tenant_id, title, created_at, updated_at, metadata "
                "FROM conversations WHERE id = :id"
            ),
            {"id": row.conversation_id},
        )
    ).first()
    msg_rows = (
        await db.execute(
            text(
                "SELECT id, conversation_id, role, content, sources, "
                "feedback, feedback_note, created_at "
                "FROM messages WHERE conversation_id = :id ORDER BY created_at ASC"
            ),
            {"id": row.conversation_id},
        )
    ).all()
    return {
        "conversation": _conversation_to_dict(conv_row),
        "messages": [_message_to_dict(m) for m in msg_rows],
        "shared_via": token,
    }
