"""Query result cache — caches full RAG+LLM responses for repeated queries.

Quando a mesma query chega múltiplas vezes (com mesmos parâmetros), retorna
a resposta cacheada em vez de chamar o LLM novamente. Isso reduz:
- Latência (de 1-2s para ~10ms)
- Custo (zero tokens do LLM para cache hit)
- Carga no vector store

**Estratégia de cache:**
- Key = hash(question + cloud + service + category)
- TTL configurável (default: 1h)
- Stats: hits, misses, evictions
- Thread-safe (RLock)
- Opcional: persistência em Redis (TODO)

**Importante:** cache é uma **otimização de performance**, não uma decisão de
negócio. RAG + LLM continuam sendo a fonte da verdade. Se a base de conhecimento
mudar, invalide o cache (já feito no `cip.ingestion.ingest`).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from cip.logging import get_logger

log = get_logger(__name__)


@dataclass
class CacheStats:
    """Estatísticas do cache."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0
    hit_rate: float = 0.0

    def update_hit_rate(self) -> None:
        total = self.hits + self.misses
        self.hit_rate = self.hits / total if total > 0 else 0.0


@dataclass
class CacheEntry:
    """Entrada do cache com TTL."""

    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.monotonic)


class QueryResultCache:
    """Cache thread-safe de respostas de query com TTL.

    Para ativar: `CIP_QUERY_CACHE_TTL > 0` (em segundos).
    Default: 0 (desabilitado).
    """

    def __init__(self, default_ttl: float = 3600.0) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._default_ttl = default_ttl
        self._stats = CacheStats()

    @staticmethod
    def make_key(
        question: str,
        cloud: str | None = None,
        service: str | None = None,
        category: str | None = None,
        tenant_id: str | None = None,
        include_global: bool = True,
    ) -> str:
        """Gera chave determinística baseada nos parâmetros da query.

        ``tenant_id`` e ``include_global`` fazem parte da chave para que dois
        tenants NUNCA compartilhem a mesma entrada de cache (isolamento).
        """
        payload = json.dumps(
            {
                "q": question.strip().lower(),
                "c": cloud or "",
                "s": service or "",
                "cat": category or "",
                "t": tenant_id or "",
                "g": bool(include_global),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def get(self, key: str) -> Any | None:
        """Busca valor pela chave. Retorna None se expirado ou ausente."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats.misses += 1
                self._stats.update_hit_rate()
                return None
            if time.monotonic() > entry.expires_at:
                # Expirado — remove
                del self._cache[key]
                self._stats.evictions += 1
                self._stats.misses += 1
                self._stats.size = len(self._cache)
                self._stats.update_hit_rate()
                return None
            self._stats.hits += 1
            self._stats.update_hit_rate()
            return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Armazena valor com TTL."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        if effective_ttl <= 0:
            return  # cache desabilitado
        with self._lock:
            self._cache[key] = CacheEntry(
                value=value,
                expires_at=time.monotonic() + effective_ttl,
            )
            self._stats.size = len(self._cache)

    def invalidate(self, key: str | None = None) -> None:
        """Invalida uma chave específica ou todo o cache."""
        with self._lock:
            if key is None:
                count = len(self._cache)
                self._cache.clear()
                log.info("cache_cleared_all", count=count)
            else:
                if key in self._cache:
                    del self._cache[key]
                    log.info("cache_invalidated", key=key[:8])
            self._stats.size = len(self._cache)

    def cleanup_expired(self) -> int:
        """Remove entradas expiradas. Retorna número de entries removidas."""
        with self._lock:
            now = time.monotonic()
            expired = [k for k, e in self._cache.items() if now > e.expires_at]
            for k in expired:
                del self._cache[k]
            self._stats.evictions += len(expired)
            self._stats.size = len(self._cache)
            if expired:
                log.info("cache_cleanup", evicted=len(expired), remaining=self._stats.size)
            return len(expired)

    def stats(self) -> dict[str, Any]:
        """Retorna snapshot das estatísticas."""
        with self._lock:
            return {
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "evictions": self._stats.evictions,
                "size": self._stats.size,
                "hit_rate": round(self._stats.hit_rate, 4),
            }

    def size(self) -> int:  # type: ignore[no-redef]
        with self._lock:
            return len(self._cache)


# Singleton lazy
_query_cache: QueryResultCache | None = None


def get_query_cache(ttl: float = 0.0) -> QueryResultCache:
    """Retorna cache singleton.

    Args:
        ttl: TTL em segundos. 0 = desabilitado.
    """
    global _query_cache
    if _query_cache is None:
        # Default TTL: 1h se habilitado
        _query_cache = QueryResultCache(default_ttl=ttl if ttl > 0 else 3600.0)
    return _query_cache


def reset_query_cache() -> None:
    """Limpa singleton (para testes)."""
    global _query_cache
    _query_cache = None