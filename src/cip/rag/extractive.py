"""Síntese extrativa determinística (sem LLM) para ``LLM_PROVIDER=extractive``.

Constrói uma resposta fundamentada EXCLUSIVAMENTE a partir dos nós recuperados,
citando cada trecho com título/URL/score. O texto do documento é sempre
apresentado como dado citado (blockquote), nunca como instrução operacional:
a resposta não dá ordens nem instrui o usuário a executar comandos derivados do
documento — apenas reproduz trechos com proveniência.
"""
from __future__ import annotations

from typing import Any

_MAX_EXCERPT_CHARS = 320
_MAX_SOURCES = 5


def _clean(text: str | None, limit: int) -> str:
    """Normaliza whitespace e trunca sem quebrar no meio de token."""
    if not text:
        return ""
    collapsed = " ".join(str(text).split())
    return collapsed[:limit]


def synthesize_extractive(question: str, nodes: list[Any]) -> str:
    """Sintetiza resposta determinística citando os nós recuperados (sem LLM)."""
    if not nodes:
        return ""

    parts: list[str] = [
        "**Resposta fundamentada na documentação oficial (modo local extrativo).**",
        "",
    ]

    for i, n in enumerate(nodes[: _MAX_SOURCES], 1):
        meta = getattr(n, "metadata", {}) or {}
        title = _clean(meta.get("title") or "documento", 120)
        url = meta.get("url") or meta.get("canonical_url") or ""
        excerpt = _clean(getattr(n, "text", ""), _MAX_EXCERPT_CHARS)
        score = getattr(n, "score", None)

        parts.append(f"**{i}. {title}**")
        if url:
            parts.append(f"Fonte: {url}")
        if score is not None:
            try:
                parts.append(f"Score: {float(score):.2f}")
            except (TypeError, ValueError):
                pass
        if excerpt:
            parts.append(f"> {excerpt}")
        parts.append("")

    parts.append(
        "_Resposta baseada exclusivamente nos trechos acima (síntese extrativa, "
        "sem inferência de modelo externo). Verifique as fontes antes de aplicar "
        "qualquer ação em produção._"
    )
    return "\n".join(parts).strip()
