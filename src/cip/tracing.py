"""Tracing via Langfuse (ou no-op stub).

Quando LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY estão configurados, envia
traces para Langfuse. Caso contrário, usa stub local (não bloqueia).

Tracing capta por request:
- Latência (ms)
- Status code HTTP
- Tenant ID
- Operação (ask/analyze)
- Tokens estimados input/output
- Custo estimado USD

Em produção, Langfuse dashboard dá:
- Latência p50/p95/p99 por endpoint
- Custo total e por tenant
- Trace detalhado de cada request (retrieval, generation, tools)
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from cip.logging import get_logger

log = get_logger(__name__)


@dataclass
class TraceSpan:
    """Span individual de tracing."""

    name: str
    started_at: float
    ended_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    parent: "TraceSpan | None" = None

    @property
    def duration_ms(self) -> float:
        if self.ended_at is None:
            return 0.0
        return (self.ended_at - self.started_at) * 1000


class Tracer:
    """Interface de tracing — implementação real ou stub."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._client: Any = None
        if enabled:
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                    host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
                )
                log.info("langfuse_tracing_enabled")
            except Exception as exc:  # noqa: BLE001
                log.warning("langfuse_init_failed", error=str(exc))
                self.enabled = False

    def log_request(
        self,
        path: str,
        method: str,
        status: int,
        latency_ms: int,
        tenant_id: str | None = None,
        **extra: Any,
    ) -> None:
        """Log de request HTTP (best-effort, não bloqueia)."""
        if not self.enabled:
            return
        try:
            self._client.trace(
                name=f"{method} {path}",
                metadata={
                    "status": status,
                    "latency_ms": latency_ms,
                    "tenant_id": tenant_id or "anonymous",
                    **extra,
                },
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("langfuse_log_failed", error=str(exc))

    def log_span(self, span: TraceSpan) -> None:
        """Log de span interno (retrieval, generation, etc.)."""
        if not self.enabled or span.ended_at is None:
            return
        try:
            self._client.span(
                name=span.name,
                start_time=span.started_at,
                end_time=span.ended_at,
                metadata=span.metadata,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("langfuse_span_failed", error=str(exc))


# Singleton lazy
_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    """Retorna tracer singleton (lazy init baseado em env)."""
    global _tracer
    if _tracer is None:
        enabled = bool(os.getenv("LANGFUSE_PUBLIC_KEY")) and bool(
            os.getenv("LANGFUSE_SECRET_KEY")
        )
        _tracer = Tracer(enabled=enabled)
    return _tracer


def reset_tracer() -> None:
    """Para testes — limpa singleton."""
    global _tracer
    _tracer = None


@contextmanager
def instrument_handler(
    operation: str,
    tenant_id: str,
    **metadata: Any,
) -> Any:
    """Context manager para instrumentar um handler.

    Mede duração e loga via Langfuse (se habilitado).
    """
    tracer = get_tracer()
    started = time.monotonic()
    span = TraceSpan(
        name=operation,
        started_at=started,
        metadata={"tenant_id": tenant_id, **metadata},
    )
    try:
        yield span
    finally:
        span.ended_at = time.monotonic()
        if tracer.enabled:
            tracer.log_span(span)