"""Auth estrita (CIP_ENV != dev): matriz 401/403 de X-API-Key + X-Tenant-Id.

Contrato (Round 25):
- Sem X-API-Key            → 401
- API key inválida         → 403
- Sem X-Tenant-Id          → 401  (obrigatório em produção)
- Tenant divergente da key → 403
- Key + tenant corretos    → sucesso
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cip.api.auth import HTTPException, authenticate


def _req(headers: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(headers=headers)


@pytest.fixture(autouse=True)
def _production_env(monkeypatch) -> None:
    monkeypatch.setenv("CIP_ENV", "production")
    monkeypatch.setenv("CIP_API_KEYS", "key-a:tenant-a:60")


def test_no_api_key_returns_401() -> None:
    with pytest.raises(HTTPException) as exc:
        authenticate(_req({}))
    assert exc.value.status_code == 401


def test_invalid_api_key_returns_403() -> None:
    with pytest.raises(HTTPException) as exc:
        authenticate(_req({"X-API-Key": "wrong", "X-Tenant-Id": "tenant-a"}))
    assert exc.value.status_code == 403


def test_missing_tenant_id_returns_401() -> None:
    with pytest.raises(HTTPException) as exc:
        authenticate(_req({"X-API-Key": "key-a"}))
    assert exc.value.status_code == 401


def test_tenant_mismatch_returns_403() -> None:
    with pytest.raises(HTTPException) as exc:
        authenticate(_req({"X-API-Key": "key-a", "X-Tenant-Id": "tenant-b"}))
    assert exc.value.status_code == 403


def test_valid_key_and_tenant_succeeds() -> None:
    ctx = authenticate(_req({"X-API-Key": "key-a", "X-Tenant-Id": "tenant-a"}))
    assert ctx.tenant_id == "tenant-a"


def test_dev_mode_derives_tenant_from_key(monkeypatch) -> None:
    """Em dev, tenant ausente é derivado da chave (tolerância documentada)."""
    monkeypatch.setenv("CIP_ENV", "dev")
    ctx = authenticate(_req({"X-API-Key": "key-a"}))
    assert ctx.tenant_id == "tenant-a"
