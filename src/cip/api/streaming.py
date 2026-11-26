"""Streaming responses via Server-Sent Events (SSE) — Round 16.

Permite que o cliente receba a resposta em chunks progressivos, similar a
ChatGPT/Claude. Melhora significativamente a UX para respostas longas
(Inspection com 14 findings, ReAct com múltiplos tools).

**Formato SSE:**
```
event: chunk
data: {"delta": "Este é "}

event: chunk
data: {"delta": "um exemplo."}

event: done
data: {"answer": "Este é um exemplo.", "sources": [...]}
```

**Compatibilidade:**
- Endpoint padrão `/ask` e `/analyze` retornam JSON completo (não streaming)
- Endpoint `/ask/stream` e `/analyze/stream` retornam SSE
- Cliente pode escolher via URL

**Chunking strategy:**
- LLM_PROVIDER=local (Ollama): streaming REAL token-by-token via
  `stream_live_events` (deltas emitidos assim que o modelo os produz)
- Demais providers: chunka a resposta completa em pedaços ~50 chars (`stream_text`)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from cip.logging import get_logger

log = get_logger(__name__)


# SSE event types
EVENT_CHUNK = "chunk"
EVENT_DONE = "done"
EVENT_ERROR = "error"


def format_sse_event(event: str, data: dict[str, Any]) -> str:
    """Formata um evento SSE padrão.

    Formato: event: <type>\\ndata: <json>\\n\\n
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_text(
    text: str, chunk_size: int = 50, delay_ms: int = 20
) -> AsyncIterator[str]:
    """Chunka texto em pedaços menores, simulando streaming de LLM.

    Args:
        text: texto completo a ser chunkado
        chunk_size: tamanho aproximado de cada chunk (caracteres)
        delay_ms: delay artificial entre chunks (simula latência de LLM)

    Yields:
        Strings de chunks (não words) para simular SSE.
    """
    if not text:
        return

    words = text.split(" ")
    current_chunk: list[str] = []

    for word in words:
        current_chunk.append(word)
        # Calcula tamanho atual (com espaços)
        chunk_text = " ".join(current_chunk)
        if len(chunk_text) >= chunk_size:
            # Adiciona espaço (exceto último chunk antes de ponto final)
            yield chunk_text + " "
            current_chunk = []
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

    # Emit chunk final (sem espaço extra)
    if current_chunk:
        yield " ".join(current_chunk)


async def stream_rag_result(
    answer: str,
    sources: list[dict[str, Any]] | None = None,
    has_grounding: bool = True,
    refusal_reason: str | None = None,
    from_cache: bool = False,
    chunk_size: int = 50,
    delay_ms: int = 20,
) -> AsyncIterator[str]:
    """Gera stream SSE completo de um RagResult.

    Yields:
        Strings no formato SSE:
        - event: chunk (múltiplos)
        - event: done (um final)
    """
    sources = sources or []

    # Stream o answer em chunks
    async for chunk in stream_text(answer, chunk_size=chunk_size, delay_ms=delay_ms):
        yield format_sse_event(EVENT_CHUNK, {"delta": chunk})

    # Event done com metadata
    yield format_sse_event(EVENT_DONE, {
        "answer": answer,
        "sources": sources,
        "has_grounding": has_grounding,
        "refusal_reason": refusal_reason,
        "from_cache": from_cache,
    })


async def stream_live_events(
    events: AsyncIterator[tuple[str, Any]], state: dict[str, Any]
) -> AsyncIterator[str]:
    """Converte eventos ``("delta", str)`` em SSE ``chunk`` assim que chegam.

    O evento final ``("result", obj)`` não vira SSE: fica em ``state["result"]``
    para o chamador montar o ``done``. ``state["ttft_ms"]`` recebe o tempo até o
    primeiro delta. Contrato SSE existente (chunk/done/error) permanece igual.
    """
    t0 = time.perf_counter()
    state.setdefault("ttft_ms", None)
    state["result"] = None
    async for kind, payload in events:
        if kind == "delta":
            if not payload:
                continue
            if state["ttft_ms"] is None:
                state["ttft_ms"] = int((time.perf_counter() - t0) * 1000)
            yield format_sse_event(EVENT_CHUNK, {"delta": payload})
        elif kind == "result":
            state["result"] = payload
    if state["result"] is None:
        raise RuntimeError("stream ended without a result event")


async def stream_error(message: str, code: str = "internal_error") -> AsyncIterator[str]:
    """Gera evento de erro SSE."""
    yield format_sse_event(EVENT_ERROR, {
        "code": code,
        "message": message,
    })


# ─────────────────────────────────────────────────────────────────────────
# LangChain-style fallback: chunkar resposta para LLM que não suporta stream
# ─────────────────────────────────────────────────────────────────────────


def chunk_text_by_sentences(text: str, max_chunk_size: int = 100) -> list[str]:
    """Chunka texto por sentenças (preserva contexto semântico).

    Útil quando LLM não suporta streaming e queremos simular.
    """
    import re

    # Split por sentenças (., !, ? + whitespace/newline)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current: list[str] = []

    for sentence in sentences:
        current.append(sentence)
        chunk_text = " ".join(current)
        if len(chunk_text) >= max_chunk_size:
            chunks.append(chunk_text)
            current = []

    if current:
        chunks.append(" ".join(current))

    return chunks