"""Testes para auth + rate limiting (Fase 6 — Production Hardening).

Valida:
- API key validation
- Tenant ID consistency
- Rate limiting por tenant
- Dev mode (sem auth)
- Headers retornados em erros
- Singleton rate limiter reset entre testes

Uso:
    pytest tests/test_auth.py -v
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from cip.api.auth import (
    RateLimiter,
    TenantContext,
    authenticate,
    check_rate_limit,
    get_rate_limiter,
)


# ─────────────────────────────────────────────────────────────────────────
# Rate Limiter
# ─────────────────────────────────────────────────────────────────────────


class TestRateLimiter:
    """Token bucket rate limiter."""

    def test_first_request_allowed(self) -> None:
        rl = RateLimiter()
        allowed, _ = rl.check("tenant-a", 60)
        assert allowed is True

    def test_burst_under_limit_allowed(self) -> None:
        """Até o limite, requests passam."""
        rl = RateLimiter()
        # 10 requests sequenciais com limite 60 → todos passam
        for _ in range(10):
            allowed, _ = rl.check("tenant-burst", 60)
            assert allowed is True

    def test_exceeding_limit_returns_retry_after(self) -> None:
        """Acima do limite, retorna retry_after > 0."""
        rl = RateLimiter()
        # Limite 2 → 3ª deve ser bloqueada
        rl.check("tenant-cap", 2)
        rl.check("tenant-cap", 2)
        allowed, retry_after = rl.check("tenant-cap", 2)
        assert allowed is False
        assert retry_after >= 1

    def test_separate_tenants_independent(self) -> None:
        """Cada tenant tem bucket independente."""
        rl = RateLimiter()
        rl.check("tenant-x", 1)
        rl.check("tenant-x", 1)  # esgota X
        # Y ainda tem tokens
        allowed_y, _ = rl.check("tenant-y", 1)
        assert allowed_y is True

    def test_reset_clears_buckets(self) -> None:
        rl = RateLimiter()
        rl.check("tenant-r", 1)
        rl.check("tenant-r", 1)  # esgota
        rl.reset("tenant-r")
        # Após reset, deve ter tokens novamente
        allowed, _ = rl.check("tenant-r", 1)
        assert allowed is True

    def test_reset_all_tenants(self) -> None:
        rl = RateLimiter()
        rl.check("t1", 1)
        rl.check("t2", 1)
        rl.reset()  # limpa tudo
        # Após reset, ambos têm tokens
        assert rl.check("t1", 1)[0] is True
        assert rl.check("t2", 1)[0] is True


# ─────────────────────────────────────────────────────────────────────────
# Authentication
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Limpa bucket do rate limiter entre testes."""
    rl = get_rate_limiter()
    rl.reset()
    yield
    rl.reset()


@pytest.fixture
def mock_env_dev(monkeypatch):
    """Dev mode: sem chaves configuradas."""
    monkeypatch.setenv("CIP_ENV", "dev")
    monkeypatch.delenv("CIP_API_KEYS", raising=False)


@pytest.fixture
def mock_env_prod(monkeypatch):
    """Prod mode: chaves configuradas."""
    monkeypatch.setenv("CIP_ENV", "prod")
    monkeypatch.setenv("CIP_API_KEYS", "key-abc:tenant-abc:60,key-def:tenant-def:120")


def _make_request(api_key: str | None = None, tenant_id: str | None = None) -> MagicMock:
    """Cria mock Request com headers."""
    headers = {}
    if api_key is not None:
        headers["X-API-Key"] = api_key
    if tenant_id is not None:
        headers["X-Tenant-Id"] = tenant_id
    request = MagicMock()
    request.headers = headers
    return request


class TestAuthenticateDevMode:
    """Em dev, sem auth é permitido."""

    def test_no_api_key_in_dev(self, mock_env_dev: None) -> None:
        ctx = authenticate(_make_request())
        assert ctx.tenant_id == "default"
        assert ctx.rate_limit_rpm == 999
        assert ctx.api_key == "dev-no-key"

    def test_tenant_id_header_in_dev(self, mock_env_dev: None) -> None:
        ctx = authenticate(_make_request(tenant_id="my-tenant"))
        assert ctx.tenant_id == "my-tenant"


class TestAuthenticateProdMode:
    """Em prod, API key é obrigatória."""

    def test_no_api_key_in_prod_raises_401(self, mock_env_prod: None) -> None:
        with pytest.raises(HTTPException) as exc_info:
            authenticate(_make_request())
        assert exc_info.value.status_code == 401

    def test_invalid_api_key_raises_403(self, mock_env_prod: None) -> None:
        with pytest.raises(HTTPException) as exc_info:
            authenticate(_make_request(api_key="invalid-key"))
        assert exc_info.value.status_code == 403

    def test_valid_api_key_returns_context(self, mock_env_prod: None) -> None:
        ctx = authenticate(_make_request(api_key="key-abc", tenant_id="tenant-abc"))
        assert ctx.tenant_id == "tenant-abc"
        assert ctx.rate_limit_rpm == 60

    def test_api_key_with_explicit_tenant_id(self, mock_env_prod: None) -> None:
        ctx = authenticate(_make_request(api_key="key-abc", tenant_id="tenant-abc"))
        assert ctx.tenant_id == "tenant-abc"

    def test_tenant_id_mismatch_raises_403(self, mock_env_prod: None) -> None:
        with pytest.raises(HTTPException) as exc_info:
            authenticate(_make_request(api_key="key-abc", tenant_id="tenant-wrong"))
        assert exc_info.value.status_code == 403

    def test_higher_rate_limit_for_second_tenant(self, mock_env_prod: None) -> None:
        ctx = authenticate(_make_request(api_key="key-def", tenant_id="tenant-def"))
        assert ctx.rate_limit_rpm == 120

    def test_missing_tenant_id_raises_401(self, mock_env_prod: None) -> None:
        # Sem header X-Tenant-Id em produção → 401 (contrato estrito).
        with pytest.raises(HTTPException) as exc_info:
            authenticate(_make_request(api_key="key-abc"))
        assert exc_info.value.status_code == 401


class TestAuthNoKeysConfigured:
    """Em prod sem chaves configuradas."""

    def test_prod_no_keys_blocks_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_ENV", "prod")
        monkeypatch.delenv("CIP_API_KEYS", raising=False)
        with pytest.raises(HTTPException) as exc_info:
            authenticate(_make_request(api_key="anything"))
        assert exc_info.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────
# Rate limit check
# ─────────────────────────────────────────────────────────────────────────


class TestCheckRateLimit:
    """Integração com auth."""

    def test_first_request_passes(self, mock_env_dev: None) -> None:
        ctx = authenticate(_make_request())
        check_rate_limit(ctx)  # não deve levantar

    def test_exceeding_limit_raises_429(self) -> None:
        ctx = TenantContext(
            tenant_id="rl-test",
            api_key="hash",
            rate_limit_rpm=1,
            authenticated_at=0.0,
        )
        # Esgota o bucket manualmente
        rl = get_rate_limiter()
        rl.reset(ctx.tenant_id)
        rl.check(ctx.tenant_id, 1)  # consome 1 token
        # 2ª request deve falhar
        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit(ctx)
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers
        assert int(exc_info.value.headers["Retry-After"]) >= 1

    def test_separate_tenants_dont_share_bucket(self) -> None:
        ctx_a = TenantContext(
            tenant_id="tenant-a-rl", api_key="h", rate_limit_rpm=1, authenticated_at=0.0
        )
        ctx_b = TenantContext(
            tenant_id="tenant-b-rl", api_key="h", rate_limit_rpm=1, authenticated_at=0.0
        )
        rl = get_rate_limiter()
        rl.reset()
        check_rate_limit(ctx_a)  # consome bucket de A
        # B ainda pode fazer request
        check_rate_limit(ctx_b)  # não levanta