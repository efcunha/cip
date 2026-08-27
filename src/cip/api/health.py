"""Health checks profundos (k8s/Railway-style liveness e readiness).

Endpoints:
- /health        — liveness simples (público)
- /health/live   — processo está vivo? (k8s livenessProbe)
- /health/ready  — pode receber tráfego? (k8s readinessProbe)
                 — verifica DB, model, embeddings

Princípios:
- /health/live: NUNCA depende de dependências externas (DB, LLM). Se falhar, restart.
- /health/ready: PODE depender. Se falhar, remove do load balancer mas não restart.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from fastapi import APIRouter, Response, status

from cip.config import get_settings
from cip.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@dataclass
class HealthCheckResult:
    """Resultado de um check individual."""

    name: str
    healthy: bool
    latency_ms: float = 0.0
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class OverallHealth:
    """Saúde agregada do sistema."""

    healthy: bool
    checks: list[HealthCheckResult] = field(default_factory=list)
    timestamp: str = ""
    version: str = "0.2.0+integration"


async def _check_database() -> HealthCheckResult:
    """Verifica conectividade com Postgres+pgvector."""
    t0 = time.perf_counter()
    engine = None
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from cip.config import get_settings

        s = get_settings()
        engine = create_async_engine(
            s.database_url.replace("postgresql://", "postgresql+asyncpg://"),
            pool_pre_ping=True,
        )

        # Endpoint já roda dentro do event loop do uvicorn — usar await direto
        # (NUNCA asyncio.run() aqui: dispara "cannot be called from a running
        # event loop" e o check falha antes de tocar o banco).
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            ok = result.scalar() == 1

        latency_ms = (time.perf_counter() - t0) * 1000

        if ok:
            return HealthCheckResult(
                name="database",
                healthy=True,
                latency_ms=latency_ms,
                message=f"Postgres+pgvector OK ({latency_ms:.0f}ms)",
            )
        return HealthCheckResult(
            name="database",
            healthy=False,
            latency_ms=latency_ms,
            message="Postgres query returned unexpected result",
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t0) * 1000
        return HealthCheckResult(
            name="database",
            healthy=False,
            latency_ms=latency_ms,
            message=f"Database error: {str(exc)[:200]}",
        )
    finally:
        if engine is not None:
            await engine.dispose()


def _check_llm_provider() -> HealthCheckResult:
    """Verifica se LLM provider está acessível."""
    t0 = time.perf_counter()
    try:
        from cip.rag.llm import build_llm

        llm = build_llm()
        provider = get_settings().llm_provider
        latency_ms = (time.perf_counter() - t0) * 1000
        return HealthCheckResult(
            name="llm",
            healthy=True,
            latency_ms=latency_ms,
            message=f"LLM provider '{provider}' initialized",
            details={"provider": provider, "model": get_settings().llm_model},
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t0) * 1000
        return HealthCheckResult(
            name="llm",
            healthy=False,
            latency_ms=latency_ms,
            message=f"LLM error: {str(exc)[:200]}",
        )


async def _check_vector_store() -> HealthCheckResult:
    """Verifica se vector store tem dados (chunks > 0)."""
    t0 = time.perf_counter()
    engine = None
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from cip.config import get_settings

        s = get_settings()
        engine = create_async_engine(
            s.database_url.replace("postgresql://", "postgresql+asyncpg://"),
            pool_pre_ping=True,
        )

        # await direto (dentro do event loop do uvicorn). A tabela física é
        # `data_cloud_docs`: o PGVectorStore do llama-index prefixa `data_` ao
        # table_name="cloud_docs" configurado em rag/vector_store.py. A ingestão
        # (ingest.py) popula exatamente essa tabela — contar aqui reflete o KB.
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM data_cloud_docs"))
            n = result.scalar() or 0

        latency_ms = (time.perf_counter() - t0) * 1000

        if n > 0:
            return HealthCheckResult(
                name="vector_store",
                healthy=True,
                latency_ms=latency_ms,
                message=f"{n} chunks indexed",
                details={"chunks": n},
            )
        return HealthCheckResult(
            name="vector_store",
            healthy=False,
            latency_ms=latency_ms,
            message="Vector store empty (0 chunks). Run ingestion first.",
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t0) * 1000
        return HealthCheckResult(
            name="vector_store",
            healthy=False,
            latency_ms=latency_ms,
            message=f"Vector store error: {str(exc)[:200]}",
        )


def _check_rate_limiter() -> HealthCheckResult:
    """Verifica que rate limiter está operacional."""
    t0 = time.perf_counter()
    try:
        from cip.api.auth import get_rate_limiter

        rl = get_rate_limiter()
        # Smoke test
        allowed, _ = rl.check("healthcheck", 1000)
        latency_ms = (time.perf_counter() - t0) * 1000
        if not allowed:
            return HealthCheckResult(
                name="rate_limiter",
                healthy=False,
                latency_ms=latency_ms,
                message="Rate limiter rejecting requests unexpectedly",
            )
        return HealthCheckResult(
            name="rate_limiter",
            healthy=True,
            latency_ms=latency_ms,
            message="Rate limiter operational",
            details={"active_tenants": len(rl._buckets)},  # type: ignore[attr-defined]
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t0) * 1000
        return HealthCheckResult(
            name="rate_limiter",
            healthy=False,
            latency_ms=latency_ms,
            message=f"Rate limiter error: {str(exc)[:200]}",
        )


async def run_all_checks() -> OverallHealth:
    """Roda todos os checks de readiness."""
    import asyncio
    from datetime import datetime, timezone

    # DB checks são async nativos (await direto).
    # LLM/rate_limiter são sync e PODEM bloquear (build_llm faz handshake de
    # rede que pendura o event loop) — rodar em threadpool via to_thread para
    # não congelar o handler async do readiness.
    async def _bounded(fn: Any, name: str, timeout_s: float) -> HealthCheckResult:
        """Roda um check sync em threadpool com teto de tempo.

        Sem isso, build_llm()/OpenAILike pode pendurar em I/O de rede e o
        readiness nunca retorna (503 é preferível a travar o probe).
        """
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_s)
        except asyncio.TimeoutError:
            return HealthCheckResult(
                name=name,
                healthy=False,
                latency_ms=timeout_s * 1000,
                message=f"Check timed out after {timeout_s:.0f}s",
            )

    checks = [
        await _check_database(),
        await _bounded(_check_llm_provider, "llm", 10.0),
        await _check_vector_store(),
        await _bounded(_check_rate_limiter, "rate_limiter", 5.0),
    ]
    return OverallHealth(
        healthy=all(c.healthy for c in checks),
        checks=checks,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/live", response_model=None)
async def liveness() -> dict[str, str]:
    """Liveness probe (k8s): processo está vivo?

    NÃO depende de DB/LLM — sempre retorna 200 se o processo está rodando.
    Se falhar, orchestrador faz restart do pod.
    """
    return {"status": "alive"}


@router.get("/ready", response_model=None)
async def readiness(response: Response) -> dict[str, Any]:
    """Readiness probe (k8s): pode receber tráfego?

    Verifica DB, vector store, LLM provider, rate limiter.
    Se algum falhar, retorna 503 → orchestrator remove do LB (sem restart).
    """
    health = await run_all_checks()
    if not health.healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return asdict(health)
    return asdict(health)


@router.get("", response_model=None)
async def health() -> dict[str, str]:
    """Health check simples (público, sem auth)."""
    s = get_settings()
    return {
        "status": "ok",
        "version": "0.2.0+integration",
        "env": s.cip_env,
        "readonly": str(s.cip_readonly),
    }