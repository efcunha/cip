"""Query translation (PT-BR -> EN) antes do retrieval.

O modelo de embeddings (bge-large-en-v1.5) e' so' ingles; perguntas em portugues
recuperam pior (recall@1 81% vs 100%). Aqui a pergunta e' traduzida para ingles
APENAS para embedding/retrieval. O gerador continua recebendo a pergunta original.

Falha segura: qualquer erro/timeout/saida vazia => pergunta original.
"""
from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any

from cip.logging import get_logger
from cip.rag.query_cache import QueryResultCache

log = get_logger(__name__)

_DIACRITICS = re.compile(r"[ãõçáéíóúâêôàü]", re.IGNORECASE)
_WORD = re.compile(r"[a-zA-Z']+")
# Palavras tipicamente portuguesas, sem colisao com ingles comum (sem "a", "do", "as", "me"...).
_PT_WORDS = frozenset(
    "que como qual quais quando onde porque por para uma um uns umas nao não com sem "
    "os de da das dos na nas no nos em ao aos pelo pela pelos pelas ser sao são posso "
    "preciso devo fazer usar criar configurar diferenca diferença entre quanto quantos "
    "sobre voce você meu minha seu sua isso esse essa este esta tem tenho existe "
    "funciona serve melhor ou mais ja já ainda também tambem".split()
)
_EN_WORDS = frozenset(
    "the is are what how which when where why can does do should to of in on for with "
    "and or a an it this that be my i you from by at as not".split()
)

_SYSTEM = (
    "You are a translation engine. Translate the user's question into English. "
    "Keep service names, product names, identifiers, commands and acronyms "
    "(e.g. EC2, S3, IAM, VPC, GKE, AKS) exactly as written. "
    "Output ONLY the English translation, with no quotes, notes or explanation. "
    "Do not answer the question."
)

_MAX_TOKENS = 128
_MAX_QUESTION_CHARS = 1000

_cache: QueryResultCache | None = None


def get_translation_cache(ttl: float = 86400.0) -> QueryResultCache:
    global _cache
    if _cache is None:
        _cache = QueryResultCache(default_ttl=ttl)
    return _cache


def reset_translation_cache() -> None:
    global _cache
    _cache = None


def is_non_english(question: str) -> bool:
    """Heuristica barata (sem chamada externa): True se a pergunta parece PT."""
    if _DIACRITICS.search(question):
        return True
    words = [w.lower() for w in _WORD.findall(question)]
    pt = sum(1 for w in words if w in _PT_WORDS)
    en = sum(1 for w in words if w in _EN_WORDS)
    return pt >= 2 or (pt >= 1 and en == 0)


def _clean(text: str) -> str:
    line = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
    return line.strip().strip("\"'`").strip()


async def _call_llm(llm: Any, question: str) -> str:
    from llama_index.core.llms import ChatMessage

    messages = [
        ChatMessage(role="system", content=_SYSTEM),
        ChatMessage(role="user", content=question[:_MAX_QUESTION_CHARS]),
    ]
    resp = llm.achat(messages, temperature=0.0, max_tokens=_MAX_TOKENS)
    if inspect.isawaitable(resp):
        resp = await resp
    msg = getattr(resp, "message", None)
    return str(getattr(msg, "content", None) or getattr(resp, "text", "") or "")


async def translate_query(
    question: str,
    llm: Any,
    *,
    timeout_s: float,
    tenant_id: str | None = None,
    include_global: bool = True,
    cache: QueryResultCache | None = None,
) -> str:
    """Retorna a pergunta em ingles para retrieval, ou a original em qualquer falha."""
    key = QueryResultCache.make_key(
        question, tenant_id=tenant_id, include_global=include_global
    )
    if cache is not None:
        hit = cache.get(key)
        if hit:
            log.debug("query_translation_cache_hit", key=key[:8])
            return str(hit)
    try:
        raw = await asyncio.wait_for(_call_llm(llm, question), timeout=max(0.001, timeout_s))
        translated = _clean(raw)
    except Exception as exc:  # noqa: BLE001 - nunca bloqueia a requisicao
        log.warning(
            "query_translation_failed",
            error=type(exc).__name__,
            timeout=isinstance(exc, asyncio.TimeoutError),
        )
        return question
    if not translated or len(translated) > 4 * len(question) + 200:
        log.warning("query_translation_empty_or_invalid")
        return question
    if cache is not None:
        cache.set(key, translated)
    log.info("query_translated", original_len=len(question), translated_len=len(translated))
    return translated
