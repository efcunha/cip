"""Orchestrator.handle_stream: um único caminho de eventos (delta... result)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from cip.agents.orchestrator import Orchestrator

SEP = "\n\n--- Resposta base ---\n"


class _FakeEngine:
    def __init__(self, fallback: str | None = None) -> None:
        self.queries: list[dict[str, Any]] = []
        self.stream_calls = 0
        self._fallback = fallback

    async def query(self, question: str, cloud: Any = None, **kw: Any) -> Any:
        self.queries.append({"question": question, "cloud": cloud, **kw})
        return SimpleNamespace(
            answer="ANSWER", sources=[], has_grounding=True, fallback=None
        )

    async def query_stream(self, question: str, cloud: Any = None, **kw: Any):
        self.stream_calls += 1
        yield ("delta", "BA")
        yield ("delta", "SE")
        yield (
            "result",
            SimpleNamespace(
                answer="BASE", sources=[], has_grounding=True, fallback=self._fallback
            ),
        )


def _orch(provider: str, engine: _FakeEngine) -> Orchestrator:
    orch = object.__new__(Orchestrator)
    orch._engine = engine
    orch._settings = SimpleNamespace(llm_provider=provider)
    return orch


Q = "como reduzir custo do S3 na AWS com seguranca?"


async def _collect(orch: Orchestrator) -> tuple[list[str], Any]:
    deltas: list[str] = []
    result = None
    async for kind, payload in orch.handle_stream(Q, react_mode=False):
        if kind == "delta":
            deltas.append(payload)
        else:
            result = payload
    return deltas, result


async def test_local_specialists_forced_extractive_single_generation() -> None:
    eng = _FakeEngine()
    deltas, result = await _collect(_orch("local", eng))
    assert eng.queries, "especialistas devem ter consultado o engine"
    assert all(q.get("force_extractive") is True for q in eng.queries)
    assert eng.stream_calls == 1


async def test_local_delta_order_and_summary() -> None:
    eng = _FakeEngine()
    deltas, result = await _collect(_orch("local", eng))
    assert deltas[-2:] == ["BA", "SE"]
    if len(deltas) > 2:
        assert deltas[0].endswith(SEP)
    assert result.summary == "".join(deltas)
    assert result.fallback is None


async def test_non_local_uses_plain_query() -> None:
    eng = _FakeEngine()
    deltas, result = await _collect(_orch("extractive", eng))
    assert eng.stream_calls == 0
    assert all("force_extractive" not in q for q in eng.queries)
    assert deltas[-1] == "ANSWER"
    assert result.summary == "".join(deltas)
    assert result.summary.endswith("ANSWER")


async def test_handle_matches_stream_result() -> None:
    eng = _FakeEngine()
    orch = _orch("local", eng)
    res = await orch.handle(Q, react_mode=False)
    assert res.summary.endswith("BASE")
    assert res.plan is not None


async def test_fallback_propagates() -> None:
    eng = _FakeEngine(fallback="timeout_total")
    _, result = await _collect(_orch("local", eng))
    assert result.fallback == "timeout_total"


@pytest.mark.parametrize("provider", ["local", "extractive"])
async def test_react_mode_yields_single_delta(provider: str, monkeypatch) -> None:
    orch = _orch(provider, _FakeEngine())

    async def fake_handle(*a: Any, **k: Any) -> Any:
        return SimpleNamespace(summary="REACT")

    monkeypatch.setattr(orch, "handle", fake_handle)
    events = [e async for e in orch.handle_stream(Q, react_mode=True)]
    assert events[0] == ("delta", "REACT")
    assert events[1][0] == "result"
