"""Query translation PT-BR -> EN antes do retrieval."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from cip.rag.query_cache import QueryResultCache
from cip.rag.query_translation import is_non_english, translate_query
from tests.test_engine_local_llm import _engine, _FakeLLM, _Index, _node


class _TLLM:
    def __init__(self, reply: Any = "How do I create an S3 bucket?") -> None:
        self.reply = reply
        self.calls = 0
        self.kwargs: dict[str, Any] = {}

    async def achat(self, messages: list[Any], **kw: Any) -> Any:
        self.calls += 1
        self.kwargs = kw
        if isinstance(self.reply, Exception):
            raise self.reply
        if isinstance(self.reply, (int, float)):
            await asyncio.sleep(self.reply)
            return SimpleNamespace(message=SimpleNamespace(content="late"))
        return SimpleNamespace(message=SimpleNamespace(content=self.reply))


@pytest.mark.parametrize(
    "q",
    ["Como criar um bucket S3?", "Qual a diferença entre EC2 e Lambda?", "como?",
     "Quando devo usar o IAM role para uma função?"],
)
def test_detects_portuguese(q: str) -> None:
    assert is_non_english(q)


@pytest.mark.parametrize(
    "q",
    ["How do I create an S3 bucket?", "What is the difference between EC2 and Lambda?",
     "Can I do this with IAM roles?", "S3 versioning"],
)
def test_english_not_flagged(q: str) -> None:
    assert not is_non_english(q)


async def test_translate_success_and_cache() -> None:
    llm = _TLLM('"How do I create an S3 bucket?"\nextra')
    cache = QueryResultCache(default_ttl=60)
    q = "Como criar um bucket S3?"
    out = await translate_query(q, llm, timeout_s=1, cache=cache)
    assert out == "How do I create an S3 bucket?"
    assert llm.kwargs["temperature"] == 0.0 and llm.kwargs["max_tokens"] <= 128
    assert await translate_query(q, llm, timeout_s=1, cache=cache) == out
    assert llm.calls == 1


async def test_cache_key_scoped_by_tenant() -> None:
    llm = _TLLM()
    cache = QueryResultCache(default_ttl=60)
    q = "Como criar um bucket S3?"
    await translate_query(q, llm, timeout_s=1, cache=cache, tenant_id="a")
    await translate_query(q, llm, timeout_s=1, cache=cache, tenant_id="b")
    assert llm.calls == 2


@pytest.mark.parametrize("reply", [RuntimeError("boom"), "   ", 5.0])
async def test_translate_failure_falls_back(reply: Any) -> None:
    llm = _TLLM(reply)
    cache = QueryResultCache(default_ttl=60)
    q = "Como criar um bucket S3?"
    assert await translate_query(q, llm, timeout_s=0.05, cache=cache) == q
    assert cache.get(QueryResultCache.make_key(q)) is None


class _RecRetriever:
    def __init__(self, sink: list[str], nodes: list[Any]) -> None:
        self.sink, self.nodes = sink, nodes

    async def aretrieve(self, q: str) -> list[Any]:
        self.sink.append(q)
        return self.nodes


class _RecIndex(_Index):
    def __init__(self, nodes: list[Any], sink: list[str]) -> None:
        super().__init__(nodes)
        self.sink = sink

    def as_retriever(self, **kw: Any) -> Any:
        return _RecRetriever(self.sink, self._nodes)


class _Both(_FakeLLM, _TLLM):
    def __init__(self) -> None:
        _FakeLLM.__init__(self, ["S3 guarda [1]."])
        self.tcalls = 0

    async def achat(self, messages: list[Any], **kw: Any) -> Any:
        self.tcalls += 1
        return SimpleNamespace(message=SimpleNamespace(content="How to create an S3 bucket?"))


async def _drive(eng: Any, q: str) -> Any:
    res = None
    async for kind, payload in eng.query_stream(q):
        if kind == "result":
            res = payload
    return res


async def test_engine_retrieves_with_translation_generates_with_original() -> None:
    from cip.rag.query_translation import reset_translation_cache

    reset_translation_cache()
    sink: list[str] = []
    llm = _Both()
    eng = _engine([_node(1)], llm)
    eng._index = _RecIndex([_node(1)], sink)
    res = await _drive(eng, "Como criar um bucket S3?")
    assert sink == ["How to create an S3 bucket?"]
    assert llm.tcalls == 1 and res.has_grounding


async def test_engine_english_no_extra_call() -> None:
    sink: list[str] = []
    llm = _Both()
    eng = _engine([_node(1)], llm)
    eng._index = _RecIndex([_node(1)], sink)
    await _drive(eng, "How do I create an S3 bucket?")
    assert sink == ["How do I create an S3 bucket?"] and llm.tcalls == 0


async def test_engine_skips_when_disabled_or_extractive() -> None:
    for over in ({"query_translation_enabled": False}, {"llm_provider": "extractive"}):
        sink: list[str] = []
        llm = _Both()
        eng = _engine([_node(1)], llm, **over)
        eng._index = _RecIndex([_node(1)], sink)
        q = "Como criar um bucket S3?"
        assert await eng._maybe_translate(q, None, True) == q
        assert llm.tcalls == 0


class _QE:
    def __init__(self, sink: list[Any], nodes: list[Any]) -> None:
        self.sink, self.nodes = sink, nodes

    async def aquery(self, q: Any) -> Any:
        self.sink.append(q)
        return SimpleNamespace(source_nodes=self.nodes, __str__=lambda s: "ok")


class _QEIndex:
    def __init__(self, sink: list[Any], nodes: list[Any]) -> None:
        self.sink, self.nodes = sink, nodes

    def as_query_engine(self, **kw: Any) -> _QE:
        return _QE(self.sink, self.nodes)


def _nonlocal_engine(sink: list[Any], llm: Any) -> Any:
    eng = _engine([_node(1)], llm, llm_provider="openai")
    eng._index = _QEIndex(sink, [_node(1)])
    return eng


async def test_nonlocal_provider_translates_for_embedding_only() -> None:
    from cip.rag.query_translation import reset_translation_cache

    reset_translation_cache()
    sink: list[Any] = []
    llm = _Both()
    eng = _nonlocal_engine(sink, llm)
    q = "Como criar um bucket S3?"
    res = await eng.query(q)
    bundle = sink[0]
    assert bundle.query_str == q
    assert bundle.embedding_strs == ["How to create an S3 bucket?"]
    assert llm.tcalls == 1 and res.has_grounding


async def test_nonlocal_provider_english_no_extra_call() -> None:
    sink: list[Any] = []
    llm = _Both()
    eng = _nonlocal_engine(sink, llm)
    q = "How do I create an S3 bucket?"
    await eng.query(q)
    assert sink == [q] and llm.tcalls == 0
