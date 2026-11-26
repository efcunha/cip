"""API FastAPI da Cloud Intelligence Platform.

Endpoints:
- GET  /health         → liveness simples (público)
- GET  /health/live    → k8s liveness (sempre 200 se processo vivo)
- GET  /health/ready   → k8s readiness (503 se dependências down)
- GET  /metrics        → Prometheus metrics
- POST /ask            → pergunta de conhecimento (RAG puro, com filtros)
- POST /ask/stream     → pergunta de conhecimento (Server-Sent Events)
- POST /analyze        → análise completa (orquestrador: RAG + tools + inspeção)
- POST /analyze/stream → análise completa (Server-Sent Events)

Fase 6/8 — Production Hardening:
- Auth middleware (X-API-Key + X-Tenant-Id)
- Rate limiting por tenant
- Tracing via Langfuse (opcional)
- Audit logging (CIP_AUDIT_LOG_PATH)
- Métricas Prometheus (cip_requests_total, latency, cost, etc.)

Round 16 — Streaming:
- Endpoints /ask/stream e /analyze/stream retornam SSE
- Chunks progressivos para melhor UX em respostas longas
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from cip.api.auth import (
    TenantContext,
    authenticate,
    check_rate_limit,
    get_rate_limiter,
)
from cip.api.health import router as health_router
from cip.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AskRequest,
    AskResponse,
    FindingOut,
    HealthResponse,
    SourceOut,
)
from cip.api.streaming import (
    EVENT_DONE,
    format_sse_event,
    stream_error,
    stream_live_events,
    stream_rag_result,
)
from cip.config import get_settings
from cip.logging import configure_logging, get_logger
from cip.observability import (
    AuditEntry,
    get_audit_logger,
    get_metrics,
    reset_audit_logger,
    reset_metrics,
)
from cip.tracing import get_tracer, instrument_handler

log = get_logger(__name__)

# Rotas que não passam por auth/controle de concorrência.
_UNTHROTTLED_PATHS = {"/health", "/health/live", "/metrics", "/docs", "/redoc", "/openapi.json"}


def _run_startup_migrations(settings) -> None:
    """Aplica migrations pendentes ANTES de criar o pool de conexões.

    Fail-closed: qualquer falha aqui impede o app de subir, então o health
    check NÃO reporta saudável com schema desatualizado. Usa o mecanismo
    oficial ``scripts/apply_migrations.py`` (idempotente, tabela de controle
    ``schema_migrations``), sem imprimir a URL do banco.
    """
    import os
    import subprocess
    import sys as _sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "apply_migrations.py"
    if not script.exists():
        # Imagem enxuta sem o script (improvável no estágio base) → fail-closed.
        raise RuntimeError(f"apply_migrations.py não encontrado: {script}")

    env = dict(os.environ)
    env["DATABASE_URL"] = settings.database_url
    log.info("startup_migrations_begin", script=str(script))
    result = subprocess.run(
        [_sys.executable, str(script)],
        cwd=str(script.parents[1]),
        env=env,
        capture_output=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"startup migrations failed (exit {result.returncode}) — serviço não iniciado"
        )
    log.info("startup_migrations_ok")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    # Reset singletons para estado limpo no startup
    reset_metrics()
    reset_audit_logger()

    # Semáforo criado dentro do event loop (limite de concorrência por processo).
    app.state.semaphore = asyncio.Semaphore(settings.max_concurrent_requests)

    # ── Round 25+: migrations pendentes ANTES do pool (fail-closed) ──
    _run_startup_migrations(settings)

    # ── Round 22+: pool de conexões asyncpg + orchestrator pré-inicializados ──
    # Chat multi-turn (api/chat.py) e /ask usam ambos via request.app.state.
    # Criar UMA VEZ aqui (em vez de lazy) evita o bug asyncpg+Py3.14 que cria
    # pools separados por request e corrompe o event loop.
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    app.state.db_engine = create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_recycle=settings.db_pool_recycle_s,
        pool_pre_ping=True,
    )
    app.state.db = async_sessionmaker(app.state.db_engine, expire_on_commit=False)()

    # Orchestrator pré-carregado (embedding model + LLM ficam em memória)
    from cip.agents.orchestrator import get_orchestrator

    app.state.orchestrator = get_orchestrator()

    log.info(
        "startup",
        env=settings.cip_env,
        readonly=settings.cip_readonly,
        max_concurrent=settings.max_concurrent_requests,
        request_timeout_s=settings.request_timeout_s,
        db_pool_size=settings.db_pool_size,
    )
    yield

    # Cleanup
    await app.state.db_engine.dispose()
    log.info("shutdown")


app = FastAPI(
    title="Cloud Intelligence Platform",
    description="LLM especialista em AWS, GCP e Azure (RAG + tools read-only).",
    version="0.2.0+integration",
    lifespan=lifespan,
)

# Health endpoints (k8s/Railway probes)
app.include_router(health_router)

# Chat multi-turn + feedback loop (Round 22+)
# Import local para evitar circular: chat.py -> auth.py (nao app.py)
from cip.api.chat import public_router as chat_public_router, router as chat_router  # noqa: E402
from cip.api.consult import router as consult_router  # noqa: E402  (Phase 3: consumido por outros chats)
from cip.api.oauth import router as oauth_router  # noqa: E402
from cip.api.ws import router as ws_router  # noqa: E402

app.include_router(chat_router)
app.include_router(chat_public_router)
app.include_router(ws_router)
app.include_router(oauth_router)
app.include_router(consult_router)


# ─────────────────────────────────────────────────────────────────────────
# Auth dependency (re-exported from _shared.py para manter compatibilidade)
# ─────────────────────────────────────────────────────────────────────────
from cip.api._shared import get_tenant  # noqa: E402,F401


# ─────────────────────────────────────────────────────────────────────────
# Middleware: backpressure + timeout + tracing + audit
# ─────────────────────────────────────────────────────────────────────────


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Backpressure + timeout + tracing + audit + metrics."""
    if request.url.path in _UNTHROTTLED_PATHS:
        return await call_next(request)

    settings = get_settings()
    sem: asyncio.Semaphore = request.app.state.semaphore
    metrics = get_metrics()
    tracer = get_tracer()
    audit = get_audit_logger()

    # Tenta entrar; se o sistema está saturado, recusa rápido (429).
    try:
        await asyncio.wait_for(sem.acquire(), timeout=0.1)
    except asyncio.TimeoutError:
        log.warning("overloaded_429", path=request.url.path)
        metrics.inc_counter(
            "cip_requests_total",
            labels={"endpoint": request.url.path, "method": request.method, "status": "429"},
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Servidor sobrecarregado. Tente novamente em instantes."},
            headers={"Retry-After": "2"},
        )

    started = time.perf_counter()
    tenant_id = "anonymous"
    audit_entry = AuditEntry(
        endpoint=request.url.path,
        method=request.method,
    )

    try:
        response = await asyncio.wait_for(
            call_next(request), timeout=settings.request_timeout_s
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        elapsed_s = elapsed_ms / 1000.0

        # Tenant context (se auth passou)
        tenant_obj = getattr(request.state, "tenant", None)
        if tenant_obj:
            tenant_id = tenant_obj.tenant_id
            audit_entry.tenant_id = tenant_id
            audit_entry.api_key_hash = tenant_obj.api_key

        audit_entry.status = response.status_code
        audit_entry.latency_ms = elapsed_ms
        audit_entry.user_agent = request.headers.get("user-agent", "")
        audit_entry.source_ip = request.client.host if request.client else ""

        # Metrics
        endpoint_label = request.url.path
        method_label = request.method
        status_label = str(response.status_code)
        metrics.inc_counter(
            "cip_requests_total",
            labels={
                "endpoint": endpoint_label,
                "method": method_label,
                "status": status_label,
                "tenant": tenant_id,
            },
        )
        metrics.observe_histogram(
            "cip_request_duration_seconds",
            elapsed_s,
            labels={"endpoint": endpoint_label, "method": method_label},
        )

        # Tracing
        if tracer:
            tracer.log_request(
                path=endpoint_label,
                method=method_label,
                status=response.status_code,
                latency_ms=elapsed_ms,
                tenant_id=tenant_id,
            )

        return response
    except asyncio.TimeoutError:
        log.warning("request_timeout_504", path=request.url.path)
        audit_entry.status = 504
        audit_entry.error = "request_timeout"
        metrics.inc_counter(
            "cip_requests_total",
            labels={"endpoint": request.url.path, "method": request.method, "status": "504"},
        )
        return JSONResponse(
            status_code=504,
            content={"detail": "Tempo limite excedido ao processar a requisição."},
        )
    finally:
        # Audit log (async-safe, file IO)
        try:
            audit.log(audit_entry)
        except Exception as exc:  # noqa: BLE001
            log.warning("audit_log_call_failed", error=str(exc))
        sem.release()


# ─────────────────────────────────────────────────────────────────────────
# Metrics endpoint
# ─────────────────────────────────────────────────────────────────────────


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> Response:
    """Endpoint de métricas no formato Prometheus (text/plain).

    Sem auth — métricas são públicas em prod (atrás de firewall corporativo).
    """
    registry = get_metrics()
    return Response(content=registry.render(), media_type="text/plain; version=0.0.4")


# ─────────────────────────────────────────────────────────────────────────
# Authenticated endpoints
# ─────────────────────────────────────────────────────────────────────────


@app.post("/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    ctx: TenantContext = Depends(get_tenant),
) -> AskResponse:
    """Pergunta de conhecimento (RAG puro)."""
    check_rate_limit(ctx)
    metrics = get_metrics()
    audit = get_audit_logger()

    from cip.rag.engine import get_engine

    try:
        with instrument_handler(
            operation="ask",
            tenant_id=ctx.tenant_id,
            question=req.question,
        ):
            result = await get_engine().query(
                req.question, cloud=req.cloud, service=req.service, category=req.category
            )
    except Exception as exc:
        log.error("ask_failed", error=str(exc), tenant=ctx.tenant_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Métricas de grounding
    if result.has_grounding:
        metrics.inc_counter(
            "cip_grounded_responses_total", labels={"tenant": ctx.tenant_id}
        )
    metrics.inc_counter(
        "cip_requests_total",
        labels={"endpoint": "/ask", "method": "POST", "status": "200", "tenant": ctx.tenant_id},
    )
    metrics.observe_histogram(
        "cip_response_length_chars",
        len(result.answer),
        labels={"endpoint": "/ask"},
    )

    return AskResponse(
        answer=result.answer,
        sources=[SourceOut(**s.__dict__) for s in result.sources],
        has_grounding=result.has_grounding,
    )


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    req: AnalyzeRequest,
    ctx: TenantContext = Depends(get_tenant),
) -> AnalyzeResponse:
    """Análise completa (orquestrador: RAG + tools + inspeção)."""
    check_rate_limit(ctx)
    metrics = get_metrics()
    audit = get_audit_logger()

    from cip.agents.orchestrator import get_orchestrator

    try:
        with instrument_handler(
            operation="analyze",
            tenant_id=ctx.tenant_id,
            question=req.question,
            cloud=req.cloud,
            has_iac=bool(req.iac_payload),
        ):
            result = await get_orchestrator().handle(
                req.question,
                cloud=req.cloud,
                iac_payload=req.iac_payload,
                react_mode=req.react_mode,
            )
    except Exception as exc:
        log.error("analyze_failed", error=str(exc), tenant=ctx.tenant_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Métricas de findings
    for f in result.findings:
        metrics.inc_counter(
            "cip_findings_total",
            labels={"severity": f.severity, "domain": f.domain, "tenant": ctx.tenant_id},
        )

    # Métricas de specialists
    if result.plan:
        for s in result.plan.specialists:
            metrics.inc_counter(
                "cip_specialist_executions_total",
                labels={"specialist": s, "tenant": ctx.tenant_id},
            )

    ordered = result.prioritized_findings()
    return AnalyzeResponse(
        summary=result.summary,
        intent=result.plan.intent.value if result.plan else None,
        clouds=result.plan.clouds if result.plan else [],
        findings=[FindingOut(**f.model_dump()) for f in ordered],
        sources=[SourceOut(**s) for s in result.sources],
        tools_used=result.tools_used,
    )


# ─────────────────────────────────────────────────────────────────────────
# Round 16 — Streaming endpoints (Server-Sent Events)
# ─────────────────────────────────────────────────────────────────────────


@app.post("/ask/stream")
async def ask_stream(
    req: AskRequest,
    ctx: TenantContext = Depends(get_tenant),
) -> StreamingResponse:
    """Pergunta de conhecimento com resposta em streaming (SSE).

    Retorna Server-Sent Events com chunks progressivos:
    - event: chunk (múltiplos) → data: {"delta": "..."}
    - event: done (um final) → data: {answer, sources, ...}
    """
    check_rate_limit(ctx)

    from cip.rag.engine import get_engine

    async def event_generator() -> Any:
        try:
            if get_settings().llm_provider == "local":
                # Streaming real (Ollama): chunks assim que o modelo os produz.
                state: dict[str, Any] = {}
                async for sse in stream_live_events(
                    get_engine().query_stream(
                        req.question,
                        cloud=req.cloud,
                        service=req.service,
                        category=req.category,
                    ),
                    state,
                ):
                    yield sse
                live = state["result"]
                yield format_sse_event(EVENT_DONE, {
                    "answer": live.answer,
                    "sources": [s.__dict__ for s in live.sources],
                    "has_grounding": live.has_grounding,
                    "refusal_reason": live.refusal_reason,
                    "from_cache": live.from_cache,
                    "fallback": live.fallback,
                    "ttft_ms": state.get("ttft_ms"),
                })
                return
            with instrument_handler(
                operation="ask_stream",
                tenant_id=ctx.tenant_id,
                question=req.question,
            ):
                result = await get_engine().query(
                    req.question,
                    cloud=req.cloud,
                    service=req.service,
                    category=req.category,
                )

            # Stream chunks + done event
            sources = [s.__dict__ for s in result.sources]
            async for chunk in stream_rag_result(
                answer=result.answer,
                sources=sources,
                has_grounding=result.has_grounding,
                refusal_reason=result.refusal_reason,
                from_cache=result.from_cache,
            ):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            log.error("ask_stream_failed", error=str(exc))
            async for chunk in stream_error(str(exc), code="ask_failed"):
                yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@app.post("/analyze/stream")
async def analyze_stream(
    req: AnalyzeRequest,
    ctx: TenantContext = Depends(get_tenant),
) -> StreamingResponse:
    """Análise completa (orchestrator) com resposta em streaming (SSE)."""
    check_rate_limit(ctx)
    metrics = get_metrics()

    async def event_generator() -> Any:
        try:
            live_state: dict[str, Any] = {}
            live = get_settings().llm_provider == "local"
            with instrument_handler(
                operation="analyze_stream",
                tenant_id=ctx.tenant_id,
                question=req.question,
                cloud=req.cloud,
                has_iac=bool(req.iac_payload),
            ):
                if live:
                    # Streaming real (Ollama): deltas emitidos durante a geração.
                    async for sse in stream_live_events(
                        get_orchestrator().handle_stream(
                            req.question,
                            cloud=req.cloud,
                            iac_payload=req.iac_payload,
                            react_mode=req.react_mode,
                        ),
                        live_state,
                    ):
                        yield sse
                    result = live_state["result"]
                else:
                    result = await get_orchestrator().handle(
                        req.question,
                        cloud=req.cloud,
                        iac_payload=req.iac_payload,
                        react_mode=req.react_mode,
                    )

            # Métricas
            for f in result.findings:
                metrics.inc_counter(
                    "cip_findings_total",
                    labels={"severity": f.severity, "domain": f.domain, "tenant": ctx.tenant_id},
                )

            sources = [s for s in result.sources]
            if live:
                yield format_sse_event(EVENT_DONE, {
                    "answer": result.summary,
                    "sources": sources,
                    "has_grounding": True,
                    "refusal_reason": None,
                    "from_cache": False,
                    "fallback": result.fallback,
                    "ttft_ms": live_state.get("ttft_ms"),
                })
                return
            # Stream summary + done event
            async for chunk in stream_rag_result(
                answer=result.summary,
                sources=sources,
                has_grounding=True,
                refusal_reason=None,
                from_cache=False,
            ):
                yield chunk
        except Exception as exc:  # noqa: BLE001
            log.error("analyze_stream_failed", error=str(exc))
            async for chunk in stream_error(str(exc), code="analyze_failed"):
                yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )