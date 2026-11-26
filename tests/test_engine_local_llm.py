"""RagEngine com LLM local (Ollama): streaming, grounding e fallback extrativo."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from cip.rag.engine import RagEngine
from cip.rag.query_cache import QueryResultCache


def _node(i: int, score: float = 0.9) -> Any:
    return SimpleNamespace(
        text=f"conteudo {i}",
        score=score,
        metadata={"title": f"Doc {i}", "url": f"https://x.test/{i}", "cloud": "aws"},
    )


class _Retriever:
    def __init__(self, nodes: list[Any]) -> None:
        self._nodes = nodes

    async def aretrieve(self, question: str) -> list[Any]:
        return self._nodes


class _Index:
    def __init__(self, nodes: list[Any]) -> None:
        self._nodes = nodes

    def as_retriever(self, **kw: Any) -> _Retriever:
        return _Retriever(self._nodes)


class _FakeLLM:
    """astream_chat devolve um async generator a partir de um script de passos."""

    def __init__(self, steps: list[Any]) -> None:
        self.steps = steps
        self.calls = 0

    async def astream_chat(self, messages: list[Any]) -> Any:
        self.calls += 1

        async def gen() -> Any:
            for step in self.steps:
                if isinstance(step, Exception):
                    raise step
                if isinstance(step, (int, float)):
                    await asyncio.sleep(step)
                    continue
                yield SimpleNamespace(delta=step)

        return gen()


def _engine(nodes: list[Any], llm: _FakeLLM, **over: Any) -> RagEngine:
    eng = object.__new__(RagEngine)
    eng._index = _Index(nodes)
    eng._llm = llm
    eng._cache_enabled = False
    eng._cache = None
    base = dict(
        llm_provider="local",
        llm_model="cip-llm",
        retrieval_top_k=8,
        retrieval_min_score=0.5,
        llm_context_top_k=4,
        llm_context_chunk_chars=1200,
        llm_first_token_timeout_s=0.05,
        llm_timeout_s=0.3,
    )
    base.update(over)
    eng._settings = SimpleNamespace(**base)
    return eng


async def _run(eng: RagEngine, q: str = "como?") -> tuple[list[str], Any]:
    deltas: list[str] = []
    result = None
    async for kind, payload in eng.query_stream(q):
        if kind == "delta":
            deltas.append(payload)
        else:
            result = payload
    return deltas, result


async def test_grounded_answer_streams() -> None:
    llm = _FakeLLM(["S3 guarda ", "objetos [1]", " e mais [2]."])
    deltas, res = await _run(_engine([_node(1), _node(2)], llm))
    assert deltas[:3] == ["S3 guarda ", "objetos [1]", " e mais [2]."]
    assert deltas[-1].startswith("\n\nFontes:")
    assert res.has_grounding and res.fallback is None
    assert [s.url for s in res.sources] == ["https://x.test/1", "https://x.test/2"]
    assert "https://x.test/2" in res.answer


async def test_below_min_score_refuses_without_llm() -> None:
    llm = _FakeLLM(["x [1]"])
    deltas, res = await _run(_engine([_node(1, 0.2)], llm))
    assert llm.calls == 0
    assert not res.has_grounding and res.refusal_reason == "no_grounding_above_min_score"


async def test_llm_error_falls_back(capsys) -> None:
    llm = _FakeLLM([RuntimeError("conn refused")])
    deltas, res = await _run(_engine([_node(1)], llm))
    assert res.fallback == "llm_error:RuntimeError"
    assert "Doc 1" in res.answer and res.has_grounding
    assert "Doc 1" in "".join(deltas)
    assert "llm_fallback_extractive" in capsys.readouterr().out


async def test_first_token_timeout_falls_back() -> None:
    deltas, res = await _run(_engine([_node(1)], _FakeLLM([0.5, "tarde [1]"])))
    assert res.fallback == "timeout_first_token"


async def test_total_timeout_falls_back_with_notice() -> None:
    llm = _FakeLLM(["comeco [1] ", 0.6, "fim"])
    deltas, res = await _run(_engine([_node(1)], llm, llm_first_token_timeout_s=0.2))
    assert res.fallback == "timeout_total"
    assert deltas[0] == "comeco [1] "
    assert "interrompida" in deltas[-1] and "Doc 1" in deltas[-1]
    assert "interrompida" not in res.answer


async def test_invalid_citation_falls_back() -> None:
    deltas, res = await _run(_engine([_node(1)], _FakeLLM(["resposta [7]"])))
    assert res.fallback == "validation:citation_out_of_range"
    assert "Doc 1" in res.answer


async def test_empty_output_falls_back() -> None:
    _, res = await _run(_engine([_node(1)], _FakeLLM([])))
    assert res.fallback == "empty_output"


async def test_model_declined_is_refusal_and_not_leaked() -> None:
    deltas, res = await _run(_engine([_node(1)], _FakeLLM(["NAO_", "ENCONTRADO"])))
    assert not res.has_grounding and res.refusal_reason == "model_declined"
    assert "NAO_ENCONTRADO" not in "".join(deltas)
    assert res.fallback is None


async def test_force_extractive_never_touches_llm() -> None:
    llm = _FakeLLM(["x [1]"])
    eng = _engine([_node(1)], llm)
    res = await eng.query("como?", force_extractive=True)
    assert llm.calls == 0
    assert "Doc 1" in res.answer


async def test_query_collects_stream_for_local() -> None:
    res = await _engine([_node(1)], _FakeLLM(["ok [1]"])).query("como?")
    assert res.has_grounding and res.fallback is None


async def test_cache_validated_yes_fallback_no() -> None:
    eng = _engine([_node(1)], _FakeLLM(["ok [1]"]))
    eng._cache_enabled = True
    eng._cache = QueryResultCache(default_ttl=60)
    await _run(eng, "pergunta valida")
    key = QueryResultCache.make_key("pergunta valida", None, None, None, None, True)
    assert eng._cache.get(key) is not None

    eng2 = _engine([_node(1)], _FakeLLM([RuntimeError("x")]))
    eng2._cache_enabled = True
    eng2._cache = QueryResultCache(default_ttl=60)
    await _run(eng2, "pergunta falha")
    key2 = QueryResultCache.make_key("pergunta falha", None, None, None, None, True)
    assert eng2._cache.get(key2) is None
