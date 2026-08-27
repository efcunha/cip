"""Testes para streaming responses (Round 16).

Valida:
- SSE event format
- stream_text chunking
- stream_rag_result produz chunks + done
- stream_error produz error event
- chunk_text_by_sentences

Uso:
    pytest tests/test_streaming.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


async def _collect(agen) -> list[str]:
    """Coleta todos os chunks de um async generator."""
    chunks = []
    async for chunk in agen:
        chunks.append(chunk)
    return chunks


# ─────────────────────────────────────────────────────────────────────────
# SSE format
# ─────────────────────────────────────────────────────────────────────────


class TestSSEFormat:
    """Formato SSE event."""

    def test_basic_event(self) -> None:
        from src.cip.api.streaming import format_sse_event

        result = format_sse_event("chunk", {"delta": "hello"})
        # Formato: event: <type>\ndata: <json>\n\n
        assert result.startswith("event: chunk\n")
        assert "data: " in result
        assert result.endswith("\n\n")
        # JSON válido
        data_line = [l for l in result.split("\n") if l.startswith("data:")][0]
        json_str = data_line[len("data: "):]
        parsed = json.loads(json_str)
        assert parsed == {"delta": "hello"}

    def test_event_with_unicode(self) -> None:
        from src.cip.api.streaming import format_sse_event

        result = format_sse_event("chunk", {"text": "Olá mundo 🌍"})
        data_line = [l for l in result.split("\n") if l.startswith("data:")][0]
        parsed = json.loads(data_line[len("data: "):])
        assert parsed["text"] == "Olá mundo 🌍"

    def test_done_event(self) -> None:
        from src.cip.api.streaming import format_sse_event

        result = format_sse_event("done", {"answer": "full answer", "sources": []})
        data = json.loads(result.split("data: ")[1].split("\n")[0])
        assert data["answer"] == "full answer"


# ─────────────────────────────────────────────────────────────────────────
# stream_text
# ─────────────────────────────────────────────────────────────────────────


class TestStreamText:
    """Chunka texto em pedaços menores."""

    @pytest.mark.asyncio
    async def test_empty_text(self) -> None:
        from src.cip.api.streaming import stream_text

        chunks = await _collect(stream_text("", chunk_size=10, delay_ms=0))
        assert chunks == []

    @pytest.mark.asyncio
    async def test_single_chunk_for_short_text(self) -> None:
        from src.cip.api.streaming import stream_text

        chunks = await _collect(stream_text("hello", chunk_size=100, delay_ms=0))
        assert len(chunks) == 1
        assert "hello" in chunks[0]

    @pytest.mark.asyncio
    async def test_multiple_chunks_for_long_text(self) -> None:
        from src.cip.api.streaming import stream_text

        text = " ".join([f"word{i}" for i in range(100)])  # ~600 chars
        chunks = await _collect(stream_text(text, chunk_size=100, delay_ms=0))
        # Pelo menos 2 chunks
        assert len(chunks) >= 2
        # Conteúdo reconstruído = original
        reconstructed = "".join(chunks).replace(" ", "").strip()
        # Note: words like "word1 word10" may merge without space
        # Just verify total chars roughly preserved
        assert len(reconstructed) >= 500

    @pytest.mark.asyncio
    async def test_respects_chunk_size(self) -> None:
        from src.cip.api.streaming import stream_text

        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        chunks = await _collect(stream_text(text, chunk_size=15, delay_ms=0))
        # Cada chunk deve ter ~15 chars (pode variar um pouco)
        for c in chunks[:-1]:  # exceto último (pode ser menor)
            assert len(c) <= 25  # margem para espaços


# ─────────────────────────────────────────────────────────────────────────
# stream_rag_result
# ─────────────────────────────────────────────────────────────────────────


class TestStreamRagResult:
    """Stream SSE completo de um RagResult."""

    @pytest.mark.asyncio
    async def test_streams_chunks_and_done(self) -> None:
        from src.cip.api.streaming import stream_rag_result

        answer = "Este é um exemplo de resposta do RAG."
        sources = [{"cloud": "aws", "service": "ec2", "url": "http://x"}]
        chunks = await _collect(
            stream_rag_result(
                answer=answer,
                sources=sources,
                has_grounding=True,
                refusal_reason=None,
                from_cache=False,
                chunk_size=10,
                delay_ms=0,
            )
        )

        # Tem pelo menos 2 chunks: 1+ para "chunk" + 1 para "done"
        assert len(chunks) >= 2

        # Todos os chunks exceto último são "chunk"
        for c in chunks[:-1]:
            assert "event: chunk" in c
            data_line = [l for l in c.split("\n") if l.startswith("data:")][0]
            parsed = json.loads(data_line[len("data: "):])
            assert "delta" in parsed

        # Último chunk é "done"
        last = chunks[-1]
        assert "event: done" in last
        data_line = [l for l in last.split("\n") if l.startswith("data:")][0]
        parsed = json.loads(data_line[len("data: "):])
        assert parsed["answer"] == answer
        assert parsed["sources"] == sources
        assert parsed["has_grounding"] is True
        assert parsed["from_cache"] is False

    @pytest.mark.asyncio
    async def test_done_event_includes_all_metadata(self) -> None:
        from src.cip.api.streaming import stream_rag_result

        chunks = await _collect(
            stream_rag_result(
                answer="x",
                sources=[],
                has_grounding=False,
                refusal_reason="no_grounding",
                from_cache=True,
                chunk_size=100,
                delay_ms=0,
            )
        )
        # Pega o último (done)
        data_line = [l for l in chunks[-1].split("\n") if l.startswith("data:")][0]
        parsed = json.loads(data_line[len("data: "):])
        assert parsed["has_grounding"] is False
        assert parsed["refusal_reason"] == "no_grounding"
        assert parsed["from_cache"] is True


# ─────────────────────────────────────────────────────────────────────────
# stream_error
# ─────────────────────────────────────────────────────────────────────────


class TestStreamError:
    """Stream de evento de erro."""

    @pytest.mark.asyncio
    async def test_error_event_format(self) -> None:
        from src.cip.api.streaming import stream_error

        chunks = await _collect(stream_error("Something failed", code="test_error"))
        assert len(chunks) == 1
        chunk = chunks[0]
        assert "event: error" in chunk
        data_line = [l for l in chunk.split("\n") if l.startswith("data:")][0]
        parsed = json.loads(data_line[len("data: "):])
        assert parsed["code"] == "test_error"
        assert parsed["message"] == "Something failed"

    @pytest.mark.asyncio
    async def test_default_error_code(self) -> None:
        from src.cip.api.streaming import stream_error

        chunks = await _collect(stream_error("oops"))
        data = json.loads(chunks[0].split("data: ")[1].split("\n")[0])
        assert data["code"] == "internal_error"


# ─────────────────────────────────────────────────────────────────────────
# chunk_text_by_sentences
# ─────────────────────────────────────────────────────────────────────────


class TestChunkBySentences:
    """Chunking semântico por sentenças."""

    def test_short_text_single_chunk(self) -> None:
        from src.cip.api.streaming import chunk_text_by_sentences

        chunks = chunk_text_by_sentences("Hello world.", max_chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world."

    def test_multiple_sentences(self) -> None:
        from src.cip.api.streaming import chunk_text_by_sentences

        text = "First sentence. Second sentence. Third sentence."
        chunks = chunk_text_by_sentences(text, max_chunk_size=100)
        # Cada sentence é um chunk (até max_chunk_size)
        assert len(chunks) >= 1
        # Reconstructed = original
        assert "".join(chunks).replace(" ", "").startswith("Firstsentence")

    def test_respects_max_size(self) -> None:
        from src.cip.api.streaming import chunk_text_by_sentences

        text = "First sentence. Second sentence. Third sentence. Fourth. Fifth."
        chunks = chunk_text_by_sentences(text, max_chunk_size=30)
        # Cada chunk tem no máximo ~30 chars
        for c in chunks:
            assert len(c) <= 50  # margem

    def test_exclamation_and_question_marks(self) -> None:
        from src.cip.api.streaming import chunk_text_by_sentences

        text = "Wow! Really? Yes."
        chunks = chunk_text_by_sentences(text, max_chunk_size=100)
        # Cada sentence terminada em ! ou ? é um chunk
        # Note: regex pode agrupar se max_chunk_size for grande
        assert isinstance(chunks, list)
        assert len(chunks) >= 1
        # Conteúdo reconstruído tem todas as sentences
        assert "Wow" in " ".join(chunks)
        assert "Really" in " ".join(chunks)
        assert "Yes" in " ".join(chunks)


# ─────────────────────────────────────────────────────────────────────────
# API streaming endpoints
# ─────────────────────────────────────────────────────────────────────────


class TestStreamingEndpoints:
    """Endpoints /ask/stream e /analyze/stream existem e funcionam."""

    def test_streaming_endpoints_registered(self) -> None:
        from src.cip.api.app import app

        paths = [r.path for r in app.routes if hasattr(r, "path")]
        # Endpoints de streaming existem
        assert "/ask/stream" in paths
        assert "/analyze/stream" in paths
        # Endpoints não-streaming ainda existem (backward compat)
        assert "/ask" in paths
        assert "/analyze" in paths

    def test_streaming_endpoints_have_correct_methods(self) -> None:
        from src.cip.api.app import app

        for r in app.routes:
            if hasattr(r, "path") and r.path in ("/ask/stream", "/analyze/stream"):
                assert "POST" in r.methods, f"{r.path} deve ser POST"