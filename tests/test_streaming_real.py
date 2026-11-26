"""Streaming SSE real (LLM_PROVIDER=local): chunks chegam durante a geração."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from cip.api.streaming import stream_live_events


def _parse(sse: str) -> tuple[str, dict[str, Any]]:
    lines = sse.strip().split("\n")
    return lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))


async def test_chunks_arrive_before_engine_finishes() -> None:
    release = asyncio.Event()
    finished = False

    async def events():
        nonlocal finished
        yield ("delta", "ola ")
        await release.wait()  # só continua depois que o consumidor viu o 1o chunk
        yield ("delta", "mundo")
        finished = True
        yield ("result", SimpleNamespace(answer="ola mundo"))

    state: dict[str, Any] = {}
    out: list[str] = []
    agen = stream_live_events(events(), state)
    first = await agen.__anext__()
    assert _parse(first) == ("chunk", {"delta": "ola "})
    assert finished is False  # prova: nada foi bufferizado até o fim
    release.set()
    async for sse in agen:
        out.append(sse)
    assert [_parse(s)[1]["delta"] for s in out] == ["mundo"]
    assert state["result"].answer == "ola mundo"
    assert isinstance(state["ttft_ms"], int)


async def test_error_midstream_propagates() -> None:
    async def events():
        yield ("delta", "a")
        raise RuntimeError("boom")

    agen = stream_live_events(events(), {})
    await agen.__anext__()
    with pytest.raises(RuntimeError, match="boom"):
        await agen.__anext__()


async def test_missing_result_is_error() -> None:
    async def events():
        yield ("delta", "a")

    with pytest.raises(RuntimeError, match="without a result"):
        async for _ in stream_live_events(events(), {}):
            pass


# ── endpoints (TestClient, sem lifespan/DB) ───────────────────────────────


def _client(monkeypatch, engine: Any, provider: str = "local"):
    from fastapi.testclient import TestClient

    import cip.api.app as app_mod
    import cip.rag.engine as engine_mod

    settings = app_mod.get_settings().model_copy(update={"llm_provider": provider})
    monkeypatch.setattr(app_mod, "get_settings", lambda: settings)
    app_mod.app.state.semaphore = asyncio.Semaphore(10)  # normalmente criado no lifespan
    monkeypatch.setattr(engine_mod, "get_engine", lambda: engine)
    monkeypatch.setattr(app_mod, "check_rate_limit", lambda ctx: None)
    app_mod.app.dependency_overrides[app_mod.get_tenant] = lambda: SimpleNamespace(
        tenant_id="t1"
    )
    return TestClient(app_mod.app), app_mod


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    return [_parse(b) for b in body.strip().split("\n\n") if b.startswith("event:")]


class _Engine:
    def __init__(self, fallback: str | None = None, fail: bool = False) -> None:
        self.fallback = fallback
        self.fail = fail

    async def query_stream(self, question: str, **kw: Any):
        yield ("delta", "parte1 ")
        if self.fail:
            raise RuntimeError("boom")
        yield ("delta", "parte2 [1]")
        yield (
            "result",
            SimpleNamespace(
                answer="parte1 parte2 [1]",
                sources=[SimpleNamespace(url="https://x.test/1", __dict__={"url": "https://x.test/1"})],
                has_grounding=True,
                refusal_reason=None,
                from_cache=False,
                fallback=self.fallback,
            ),
        )


def test_ask_stream_local_real_chunks_and_done(monkeypatch) -> None:
    client, app_mod = _client(monkeypatch, _Engine())
    try:
        r = client.post("/ask/stream", json={"question": "como reduzir custo no S3?"})
    finally:
        app_mod.app.dependency_overrides.clear()
    ev = _events(r.text)
    assert [e for e, _ in ev] == ["chunk", "chunk", "done"]
    done = ev[-1][1]
    assert done["answer"] == "parte1 parte2 [1]"
    assert done["fallback"] is None and "ttft_ms" in done
    assert done["has_grounding"] is True


def test_ask_stream_local_fallback_field(monkeypatch) -> None:
    client, app_mod = _client(monkeypatch, _Engine(fallback="timeout_total"))
    try:
        r = client.post("/ask/stream", json={"question": "como reduzir custo no S3?"})
    finally:
        app_mod.app.dependency_overrides.clear()
    assert _events(r.text)[-1][1]["fallback"] == "timeout_total"


def test_ask_stream_error_midstream_single_error_event(monkeypatch) -> None:
    client, app_mod = _client(monkeypatch, _Engine(fail=True))
    try:
        r = client.post("/ask/stream", json={"question": "como reduzir custo no S3?"})
    finally:
        app_mod.app.dependency_overrides.clear()
    kinds = [e for e, _ in _events(r.text)]
    assert kinds == ["chunk", "error"]


def test_ask_stream_non_local_uses_stream_text(monkeypatch) -> None:
    async def query(question: str, **kw: Any) -> Any:
        return SimpleNamespace(
            answer="palavra " * 30,
            sources=[],
            has_grounding=True,
            refusal_reason=None,
            from_cache=False,
        )

    engine = SimpleNamespace(query=query)
    client, app_mod = _client(monkeypatch, engine, provider="extractive")
    try:
        r = client.post("/ask/stream", json={"question": "como reduzir custo no S3?"})
    finally:
        app_mod.app.dependency_overrides.clear()
    ev = _events(r.text)
    assert len([e for e, _ in ev if e == "chunk"]) > 1
    assert ev[-1][0] == "done" and "fallback" not in ev[-1][1]
