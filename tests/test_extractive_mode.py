"""Testes do modo extrativo local (``LLM_PROVIDER=extractive``) — sem LLM externo."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest


def _fake_node(title: str, url: str, text: str, score: float = 0.9) -> Any:
    return SimpleNamespace(
        text=text,
        score=score,
        metadata={"title": title, "url": url, "cloud": "aws", "service": "s3"},
    )


def test_extractive_llm_guard_raises_on_generate() -> None:
    """O LLM-guard extrativo nunca gera: qualquer chamada de geração levanta erro."""
    from cip.rag.llm import _ExtractiveLLM

    llm = _ExtractiveLLM()
    with pytest.raises(RuntimeError, match="extractive"):
        llm.complete("prompt")
    with pytest.raises(RuntimeError, match="extractive"):
        asyncio.run(llm.acomplete("prompt"))


def test_build_llm_extractive_returns_guard(monkeypatch) -> None:
    """LLM_PROVIDER=extractive retorna o guard, sem cliente de geração."""
    import cip.rag.llm as llm_mod

    monkeypatch.setattr(
        llm_mod, "get_settings", lambda: SimpleNamespace(llm_provider="extractive")
    )
    llm = llm_mod.build_llm()
    assert isinstance(llm, llm_mod._ExtractiveLLM)


def test_synthesize_extractive_grounded() -> None:
    """Síntese cita trechos com título/URL/score — dado, não instrução."""
    from cip.rag.extractive import synthesize_extractive

    nodes = [
        _fake_node(
            "S3 Lifecycle",
            "https://docs.aws.amazon.com/s3/lifecycle",
            "Transição de objetos para classes mais baratas reduz custo.",
        ),
        _fake_node(
            "S3 Storage Classes",
            "https://docs.aws.amazon.com/s3/classes",
            "S3 Standard vs Glacier.",
        ),
    ]
    answer = synthesize_extractive("como reduzir custo s3", nodes)
    assert "S3 Lifecycle" in answer
    assert "https://docs.aws.amazon.com/s3/lifecycle" in answer
    assert "Transição de objetos" in answer


def test_synthesize_extractive_no_nodes() -> None:
    """Sem nós → resposta vazia (o engine preenche refusal)."""
    from cip.rag.extractive import synthesize_extractive

    assert synthesize_extractive("q", []) == ""


def test_react_blocked_in_extractive(monkeypatch) -> None:
    """ReAct exige LLM externo; no modo extrativo deve falhar explicitamente."""
    import cip.agents.orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod, "get_settings", lambda: SimpleNamespace(llm_provider="extractive")
    )
    orch = orch_mod.Orchestrator(engine=object())
    with pytest.raises(RuntimeError, match="extractive"):
        asyncio.run(orch.handle("pergunta qualquer", react_mode=True))
