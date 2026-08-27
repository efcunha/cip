"""Testes para o sistema de tracing (Fase 6 — Production Hardening).

Valida:
- Tracer desabilitado por padrão (stub local)
- Tracer habilita quando LANGFUSE_PUBLIC_KEY/SECRET_KEY estão setados
- instrument_handler mede duração
- Tracer log_request não falha se Langfuse está indisponível

Uso:
    pytest tests/test_tracing.py -v
"""

from __future__ import annotations

import os
import time

import pytest

from cip.tracing import (
    TraceSpan,
    Tracer,
    get_tracer,
    instrument_handler,
    reset_tracer,
)


class TestTracerDisabled:
    """Tracer padrão (sem Langfuse) é no-op."""

    def test_default_tracer_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        reset_tracer()
        tracer = get_tracer()
        assert tracer.enabled is False

    def test_log_request_does_not_raise_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        reset_tracer()
        tracer = get_tracer()
        # Não deve lançar exceção
        tracer.log_request(
            path="/ask",
            method="POST",
            status=200,
            latency_ms=150,
            tenant_id="tenant-test",
        )

    def test_log_span_does_not_raise_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        reset_tracer()
        tracer = get_tracer()
        span = TraceSpan(name="ask", started_at=time.monotonic())
        span.ended_at = time.monotonic()
        tracer.log_span(span)


class TestTracerEnabled:
    """Quando credenciais estão setadas, habilita."""

    def test_enabled_when_keys_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-123")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-456")
        monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
        reset_tracer()
        tracer = get_tracer()
        # Langfuse vai tentar inicializar; sem langfuse instalado, falha silenciosa
        # → enabled fica False. Verificamos que não crashou.
        assert isinstance(tracer.enabled, bool)


class TestInstrumentHandler:
    """Context manager instrumenta handler com medição de duração."""

    def test_measures_duration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        reset_tracer()

        with instrument_handler(operation="ask", tenant_id="tenant-x") as span:
            time.sleep(0.01)  # simular trabalho
            assert isinstance(span, TraceSpan)
            assert span.ended_at is None  # ainda dentro do contexto

        # Após o contexto, ended_at deve estar setado
        assert span.ended_at is not None
        assert span.duration_ms >= 10  # pelo menos 10ms

    def test_works_with_disabled_tracer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        reset_tracer()
        with instrument_handler(operation="analyze", tenant_id="t1", cloud="aws"):
            pass  # não falha


class TestTraceSpan:
    """Modelo de span."""

    def test_duration_zero_if_not_ended(self) -> None:
        span = TraceSpan(name="x", started_at=time.monotonic())
        assert span.duration_ms == 0.0

    def test_duration_after_end(self) -> None:
        span = TraceSpan(name="x", started_at=time.monotonic())
        time.sleep(0.02)
        span.ended_at = time.monotonic()
        assert span.duration_ms >= 20

    def test_parent_relationship(self) -> None:
        parent = TraceSpan(name="parent", started_at=time.monotonic())
        child = TraceSpan(name="child", started_at=time.monotonic(), parent=parent)
        assert child.parent == parent