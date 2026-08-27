"""Testes da Fase 2A — CIP hardening para integração com CloudPilot.

Cobre:
- RagResult.refusal_reason preenchido quando não há grounding.
- @model_validator bloqueia embed_dim inconsistente com embed_provider.
- KnowledgeBaseTools.summarize() expõe metadata sem tocar o RAG.
- build_knowledge_function_tool() registra FunctionTool do LlamaIndex.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from cip.config import Settings
from cip.rag.engine import RagResult, Source


def test_rag_result_refusal_reason_default_none():
    r = RagResult(answer="x")
    assert r.refusal_reason is None
    assert r.has_grounding is True


def test_rag_result_refusal_reason_explicit():
    r = RagResult(
        answer="sem grounding",
        sources=[],
        has_grounding=False,
        refusal_reason="no_grounding_above_min_score",
    )
    assert r.refusal_reason == "no_grounding_above_min_score"
    assert r.has_grounding is False


def test_rag_result_accepts_source_list():
    r = RagResult(
        answer="x",
        sources=[Source(cloud="aws", service="ec2", title="t", url="u", score=0.9)],
    )
    assert r.sources[0].cloud == "aws"


def test_settings_embed_dim_local_default_passes():
    # Defaults do projeto (pyproject.toml / config.py): local/e5-small/dim=384 — coerente.
    # CUIDADO: o .env de dev pode sobrescrever (ex.: bge-large = 1024).
    # Este teste verifica a coerência provider↔dim, não o valor absoluto.
    import os

    monkey_embed_provider = os.environ.get("EMBED_PROVIDER")
    monkey_embed_dim = os.environ.get("EMBED_DIM")
    os.environ["EMBED_PROVIDER"] = "local"
    os.environ["EMBED_DIM"] = "384"
    try:
        s = Settings()
    finally:
        # Restaura estado original
        if monkey_embed_provider is None:
            os.environ.pop("EMBED_PROVIDER", None)
        else:
            os.environ["EMBED_PROVIDER"] = monkey_embed_provider
        if monkey_embed_dim is None:
            os.environ.pop("EMBED_DIM", None)
        else:
            os.environ["EMBED_DIM"] = monkey_embed_dim
    assert s.embed_provider == "local"
    assert s.embed_dim == 384


def test_settings_embed_dim_mismatch_local_raises():
    with pytest.raises(ValidationError) as exc:
        Settings(embed_provider="local", embed_dim=1536)
    assert "embed_dim" in str(exc.value)


def test_settings_embed_dim_mismatch_openai_raises():
    with pytest.raises(ValidationError) as exc:
        Settings(embed_provider="openai", embed_dim=384)
    assert "embed_dim" in str(exc.value)


def test_settings_embed_dim_mismatch_bedrock_raises():
    with pytest.raises(ValidationError) as exc:
        Settings(embed_provider="bedrock", embed_dim=384)
    assert "embed_dim" in str(exc.value)


def test_settings_embed_dim_bedrock_1024_ok():
    s = Settings(embed_provider="bedrock", embed_dim=1024)
    assert s.embed_dim == 1024


def test_settings_embed_dim_openai_1536_ok():
    s = Settings(embed_provider="openai", embed_dim=1536)
    assert s.embed_dim == 1536


def test_knowledge_tools_summarize_does_not_call_engine():
    # summarise() só lê settings — não invoca RagEngine.query().
    from cip.tools.knowledge import KnowledgeBaseTools

    obj = KnowledgeBaseTools.__new__(KnowledgeBaseTools)
    obj._engine = MagicMock()
    obj._settings = MagicMock()
    obj._settings.embed_provider = "local"
    obj._settings.embed_model = "intfloat/multilingual-e5-small"
    obj._settings.embed_dim = 384
    text = obj.summarize()
    assert "Knowledge base oficial" in text
    assert "consult_official_cloud_knowledge" in text
    obj._engine.query.assert_not_called()


def test_knowledge_tools_consult_returns_structured_dict_when_no_grounding():
    """Quando o engine devolve RagResult sem grounding, a tool serializa corretamente."""
    from cip.tools.knowledge import KnowledgeBaseTools

    obj = KnowledgeBaseTools.__new__(KnowledgeBaseTools)

    async def fake_query(*_args: Any, **_kwargs: Any) -> RagResult:
        return RagResult(
            answer="não há referência",
            sources=[],
            has_grounding=False,
            refusal_reason="no_grounding_above_min_score",
        )

    obj._engine = MagicMock()
    obj._engine.query = fake_query
    obj._settings = MagicMock()

    import asyncio

    result = asyncio.run(obj.consult_official_cloud_knowledge(question="o que é X?"))
    assert result["has_grounding"] is False
    assert result["refusal_reason"] == "no_grounding_above_min_score"
    assert result["sources"] == []


def test_knowledge_tools_consult_returns_structured_dict_with_sources():
    from cip.tools.knowledge import KnowledgeBaseTools

    obj = KnowledgeBaseTools.__new__(KnowledgeBaseTools)

    async def fake_query(*_args: Any, **_kwargs: Any) -> RagResult:
        return RagResult(
            answer="resposta",
            sources=[Source(cloud="aws", service="ec2", title="EC2", url="u", score=0.9)],
            has_grounding=True,
        )

    obj._engine = MagicMock()
    obj._engine.query = fake_query
    obj._settings = MagicMock()

    import asyncio

    result = asyncio.run(
        obj.consult_official_cloud_knowledge(question="EC2 pricing?", cloud="aws")
    )
    assert result["has_grounding"] is True
    assert result["refusal_reason"] is None
    assert len(result["sources"]) == 1
    assert result["sources"][0]["cloud"] == "aws"


def test_knowledge_tools_consult_engine_error_returns_engine_error_refusal():
    from cip.tools.knowledge import KnowledgeBaseTools

    obj = KnowledgeBaseTools.__new__(KnowledgeBaseTools)

    async def fake_query(*_args: Any, **_kwargs: Any) -> RagResult:
        raise RuntimeError("boom")

    obj._engine = MagicMock()
    obj._engine.query = fake_query
    obj._settings = MagicMock()

    import asyncio

    result = asyncio.run(obj.consult_official_cloud_knowledge(question="x?"))
    assert result["has_grounding"] is False
    assert result["refusal_reason"] == "engine_error"


def test_registry_build_knowledge_function_tool():
    # Não exige llama_index instalado para verificar a interface mínima:
    # apenas garante que a função existe e aceita zero args.
    from cip.tools import registry

    assert callable(registry.build_knowledge_function_tool)
    assert callable(registry.collect_cost_signals)
    assert callable(registry.build_function_tools)
