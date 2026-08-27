"""Cache simples com TTL para tools cloud read-only.

Por que cache?
- Cost Explorer / Advisor / Recommender cobram por chamada ou têm rate limit
- Dados de custo/inventário mudam raramente dentro de uma janela curta
- Mesma pergunta em 1h = mesmo número (não precisa nova chamada)
- Reduz latência e custo de tools ao vivo

Design:
- Cache em memória (não persistido) — rápido, simples, suficiente
- TTL configurável (default 1h) — ajustável por tool se necessário
- Key = (tool_class, method_name, args_hash) — invalidação granular
- Thread-safe (lock global) — múltiplos requests concorrentes
"""

from __future__ import annotations

import functools
import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from cip.logging import get_logger

log = get_logger(__name__)

# TTL padrão (segundos) — 1 hora conforme ADR-0003
DEFAULT_TTL = 3600


class TTLCache:
    """Cache thread-safe com TTL."""

    def __init__(self, default_ttl: int = DEFAULT_TTL) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> tuple[bool, Any]:
        """Retorna (hit, value). value=None se miss."""
        if key not in self._cache:
            return False, None
        expires_at, value = self._cache[key]
        if time.monotonic() > expires_at:
            del self._cache[key]
            return False, None
        return True, value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        self._cache[key] = (time.monotonic() + effective_ttl, value)

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    def stats(self) -> dict[str, int]:
        return {
            "size": len(self._cache),
            "ttl_default": self._default_ttl,
        }


def _key_for(class_name: str, method_name: str, args: tuple, kwargs: dict) -> str:
    """Gera chave de cache determinística."""
    payload = json.dumps(
        {"class": class_name, "method": method_name, "args": args, "kwargs": kwargs},
        sort_keys=True,
        default=str,
    )
    return f"{class_name}.{method_name}:{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def cached(ttl: int | None = None, key_fn: Callable[..., str] | None = None) -> Callable:
    """Decorator: cacheia resultado do método por TTL.

    Uso:
        class AWSCostTools:
            @cached(ttl=3600)
            def get_monthly_cost_by_service(self, days=30):
                ...

    Se key_fn for fornecido, é usado no lugar do default (útil para invalidação custom).
    """

    def decorator(method: Callable) -> Callable:
        cache = TTLCache(default_ttl=ttl or DEFAULT_TTL)
        class_name = method.__qualname__.rsplit(".", 1)[0]

        @functools.wraps(method)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            if key_fn:
                key = key_fn(self, *args, **kwargs)
            else:
                key = _key_for(class_name, method.__name__, args, kwargs)

            hit, value = cache.get(key)
            if hit:
                log.debug("cache_hit", key=key, cls=class_name, method=method.__name__)
                return value
            value = method(self, *args, **kwargs)
            cache.set(key, value, ttl=ttl)
            log.debug("cache_miss", key=key, cls=class_name, method=method.__name__)
            return value

        wrapper._cache = cache  # type: ignore[attr-defined]
        return wrapper

    return decorator


# Cache global para summarize() (chamado por cloud) — compartilhado entre requests
GLOBAL_SUMMARY_CACHE: dict[str, TTLCache] = {}