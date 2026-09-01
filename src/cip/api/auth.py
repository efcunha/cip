"""Auth middleware: API key + tenant_id para multi-tenant.

Validação:
- Header `X-API-Key` deve corresponder a uma chave válida (CIP_API_KEYS env var)
- Header `X-Tenant-Id` é obrigatório em produção; opcional em dev
- Cada tenant tem seu próprio rate limit + isolamento de dados

Em dev (CIP_ENV=dev):
- API key pode ser omitida (warning log)
- Tenant_id default = "default"
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from cip.logging import get_logger

log = get_logger(__name__)


@dataclass
class TenantContext:
    """Contexto do tenant autenticado."""

    tenant_id: str
    api_key: str  # hashed, não o valor raw
    rate_limit_rpm: int  # requests per minute
    authenticated_at: float


# ─────────────────────────────────────────────────────────────────────────
# API Key validation
# ─────────────────────────────────────────────────────────────────────────


def _get_api_keys() -> dict[str, dict[str, Any]]:
    """Carrega mapa de API keys válidas do ambiente.

    Formato: CIP_API_KEYS = "key1:tenant1:60,key2:tenant2:120"
    Cada chave é um hash simples; em produção usar algo mais robusto.
    """
    raw = os.getenv("CIP_API_KEYS", "")
    keys: dict[str, dict[str, Any]] = {}
    if not raw:
        return keys
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) >= 2:
            api_key = parts[0]
            tenant_id = parts[1]
            rate_limit = int(parts[2]) if len(parts) >= 3 else 60
            keys[api_key] = {
                "tenant_id": tenant_id,
                "rate_limit_rpm": rate_limit,
            }
    return keys


def _hash_api_key(api_key: str) -> str:
    """Hash simples para logs (não para auth — auth usa match exato)."""
    import hashlib

    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────
# Rate limiting (in-memory token bucket)
# ─────────────────────────────────────────────────────────────────────────


class RateLimiter:
    """Token bucket por tenant.

    Refill: tokens_added = (now - last_refill) * (rate / 60)
    Cada request consome 1 token.
    Se tokens < 1 → 429 Too Many Requests.
    Bucket começa com tokens cheios (rate_limit_rpm) para permitir burst inicial.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, dict[str, float]] = {}

    def _get_bucket(self, tenant_id: str, rate_limit_rpm: int) -> dict[str, float]:
        """Lazy init do bucket com tokens cheios."""
        if tenant_id not in self._buckets:
            now = time.monotonic()
            self._buckets[tenant_id] = {
                "tokens": float(rate_limit_rpm),  # cheio = permite burst inicial
                "last_refill": now,
                "rate_limit_rpm": float(rate_limit_rpm),
            }
        return self._buckets[tenant_id]

    def check(self, tenant_id: str, rate_limit_rpm: int) -> tuple[bool, int]:
        """Verifica se tenant pode fazer request.

        Returns:
            (allowed, retry_after_seconds)
        """
        bucket = self._get_bucket(tenant_id, rate_limit_rpm)
        now = time.monotonic()
        # Refill tokens baseado no tempo decorrido
        elapsed = now - bucket["last_refill"]
        refill = elapsed * (rate_limit_rpm / 60.0)
        bucket["tokens"] = min(bucket["tokens"] + refill, float(rate_limit_rpm))
        bucket["last_refill"] = now

        if bucket["tokens"] < 1.0:
            # Calcular tempo até próximo token
            deficit = 1.0 - bucket["tokens"]
            seconds_until_next = (deficit / (rate_limit_rpm / 60.0)) if rate_limit_rpm > 0 else 60
            return False, max(1, int(seconds_until_next))

        bucket["tokens"] -= 1.0
        return True, 0

    def reset(self, tenant_id: str | None = None) -> None:
        """Limpa bucket(s) — útil para testes."""
        if tenant_id is None:
            self._buckets.clear()
        else:
            self._buckets.pop(tenant_id, None)


_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Retorna instância singleton do rate limiter."""
    return _rate_limiter


# ─────────────────────────────────────────────────────────────────────────
# Auth flow
# ─────────────────────────────────────────────────────────────────────────


def _is_dev_mode() -> bool:
    return os.getenv("CIP_ENV", "dev") == "dev"


def authenticate(request: Request) -> TenantContext:
    """Extrai e valida API key + tenant_id do request.

    Raises:
        HTTPException: 401 (sem API key em prod), 403 (API key inválida)
    """
    api_key = request.headers.get("X-API-Key")
    tenant_id_header = request.headers.get("X-Tenant-Id")

    # Em dev, aceitar sem auth mas avisar
    if not api_key:
        if _is_dev_mode():
            tenant_id = tenant_id_header or "default"
            return TenantContext(
                tenant_id=tenant_id,
                api_key="dev-no-key",
                rate_limit_rpm=999,  # sem limite em dev
                authenticated_at=time.time(),
            )
        log.warning("auth_missing_api_key")
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    # Validar API key
    valid_keys = _get_api_keys()
    if not valid_keys:
        # Sem chaves configuradas em prod → bloquear tudo
        if _is_dev_mode():
            log.warning("auth_no_keys_configured")
            return TenantContext(
                tenant_id=tenant_id_header or "default",
                api_key=_hash_api_key(api_key),
                rate_limit_rpm=999,
                authenticated_at=time.time(),
            )
        raise HTTPException(status_code=401, detail="Server API keys not configured")

    if api_key not in valid_keys:
        log.warning("auth_invalid_api_key", key_hash=_hash_api_key(api_key))
        raise HTTPException(status_code=403, detail="Invalid API key")

    key_data = valid_keys[api_key]
    # X-Tenant-Id é OBRIGATÓRIO em produção (contrato declarado). Em dev,
    # derivamos da chave quando ausente (comportamento tolerante documentado).
    if not tenant_id_header:
        if _is_dev_mode():
            log.warning(
                "auth_missing_tenant_id_dev",
                key_tenant=key_data["tenant_id"],
            )
            tenant_id_header = key_data["tenant_id"]
        else:
            log.warning("auth_missing_tenant_id")
            raise HTTPException(status_code=401, detail="X-Tenant-Id header required")

    # Tenant_id do header deve bater com o registrado na chave.
    if tenant_id_header != key_data["tenant_id"]:
        log.warning(
            "auth_tenant_mismatch",
            header_tenant=tenant_id_header,
            key_tenant=key_data["tenant_id"],
        )
        raise HTTPException(status_code=403, detail="Tenant ID mismatch")

    return TenantContext(
        tenant_id=key_data["tenant_id"],
        api_key=_hash_api_key(api_key),
        rate_limit_rpm=key_data["rate_limit_rpm"],
        authenticated_at=time.time(),
    )


def check_rate_limit(ctx: TenantContext) -> None:
    """Verifica rate limit. Raises 429 se excedido."""
    allowed, retry_after = _rate_limiter.check(ctx.tenant_id, ctx.rate_limit_rpm)
    if not allowed:
        log.warning(
            "rate_limit_exceeded",
            tenant=ctx.tenant_id,
            retry_after=retry_after,
        )
        from fastapi.responses import JSONResponse

        # Não dá pra levantar HTTPException com headers customizados via raise
        # → lançamos e o middleware converte
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Retry after {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )