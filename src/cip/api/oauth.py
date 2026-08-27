"""OAuth2 + JWT endpoints (Round 22+ Phase 2).

Em prod, use um IdP externo (Keycloak, Auth0, Okta). Em dev, este módulo
emite JWTs HS256 via /auth/dev-token (autenticação fraca por design — só
disponível em CIP_ENV=dev).

Endpoints:
  POST /auth/dev-token    →  emite JWT (dev only)
  POST /auth/login        →  OAuth2 password flow → JWT (esqueleto; usa IdP em prod)
  GET  /auth/me           →  info do Principal atual
  POST /auth/refresh      →  refresh JWT (rotaciona)
  GET  /auth/.well-known/jwks.json  →  JWKS (p/ IdPs validarem nossos tokens)
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from cip.api._shared import get_tenant
from cip.api.auth import TenantContext
from cip.api.jwt_auth import Principal, issue_jwt, require_principal
from cip.config import get_settings
from cip.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ─────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────


class DevTokenReq(BaseModel):
    """Body para gerar JWT (dev only)."""

    user_id: str = Field(default="dev-user", min_length=1, max_length=100)
    tenant_id: str = Field(default="default", min_length=1, max_length=100)
    role: str = Field(default="member", pattern="^(admin|member|viewer|agent)$")
    scopes: list[str] = Field(default_factory=list)
    expires_in: int = Field(default=3600, ge=60, le=86400)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    scope: str = ""


class LoginReq(BaseModel):
    """OAuth2 password grant (placeholder — em prod usa IdP)."""

    username: str
    password: str


class RefreshReq(BaseModel):
    token: str


# ─────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────


@router.post("/dev-token", response_model=TokenOut)
async def dev_issue_token(req: DevTokenReq) -> TokenOut:
    """Emite JWT HS256. **APENAS EM DEV** (CIP_ENV=dev)."""
    s = get_settings()
    if s.cip_env != "dev":
        raise HTTPException(
            status_code=403,
            detail="/auth/dev-token only available when CIP_ENV=dev",
        )
    token = issue_jwt(
        sub=req.user_id,
        tenant_id=req.tenant_id,
        role=req.role,  # type: ignore[arg-type]
        scopes=req.scopes,
        expires_in=req.expires_in,
    )
    log.info("dev_jwt_issued", sub=req.user_id, tenant_id=req.tenant_id, role=req.role)
    return TokenOut(
        access_token=token,
        expires_in=req.expires_in,
        scope=" ".join(req.scopes),
    )


@router.post("/login", response_model=TokenOut)
async def oauth2_password_login(req: LoginReq) -> TokenOut:
    """OAuth2 password flow (placeholder).

    Em prod, redirecione para o IdP (Authorization Code Flow com PKCE).
    Aqui retornamos 501 a menos que esteja em dev.
    """
    s = get_settings()
    if s.cip_env != "dev":
        raise HTTPException(
            status_code=501,
            detail="OAuth2 password flow não implementado; use IdP externo (Keycloak, Auth0, Okta)",
        )
    # Dev: aceita user "dev" / pass "dev" → emite token admin
    if req.username == "dev" and req.password == "dev":
        token = issue_jwt(
            sub="dev-user", tenant_id="default", role="admin",
            scopes=["*"], expires_in=3600,
        )
        return TokenOut(access_token=token, expires_in=3600, scope="*")
    raise HTTPException(status_code=401, detail="invalid credentials (dev: try dev/dev)")


@router.get("/me", response_model=dict[str, Any])
async def whoami(p: Principal = Depends(require_principal)) -> dict[str, Any]:
    """Retorna info do Principal autenticado."""
    return {
        "sub": p.sub,
        "tenant_id": p.tenant_id,
        "role": p.role,
        "scopes": p.scopes,
        "permissions": sorted(_effective_permissions(p)),
    }


@router.post("/refresh", response_model=TokenOut)
async def refresh_token(req: RefreshReq) -> TokenOut:
    """Emite novo JWT a partir de um JWT válido (mesmo sub/tenant/role, novo exp)."""
    from jose import JWTError, jwt

    s = get_settings()
    try:
        claims = jwt.decode(
            req.token,
            s.jwt_secret if s.jwt_secret else "dev-secret",
            algorithms=[s.jwt_algorithm] if s.jwt_algorithm else ["HS256"],
            audience=s.jwt_audience if s.jwt_audience else None,
            issuer=s.jwt_issuer if s.jwt_issuer else None,
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid refresh token: {exc}")

    role = claims.get("role", "member")
    if role not in ("admin", "member", "viewer", "agent"):
        role = "member"
    new_token = issue_jwt(
        sub=claims["sub"],
        tenant_id=claims.get("tenant_id", "default"),
        role=role,  # type: ignore[arg-type]
        scopes=claims.get("scope", "").split() if claims.get("scope") else [],
        expires_in=3600,
    )
    return TokenOut(access_token=new_token, expires_in=3600, scope=claims.get("scope", ""))


@router.get("/.well-known/jwks.json")
async def jwks() -> dict[str, Any]:
    """JWKS endpoint — IdPs validam tokens emitidos pelo CIP.

    Em dev retorna vazio (HS256 não usa chaves públicas).
    Em prod com RS256, retorna as chaves públicas correspondentes.
    """
    s = get_settings()
    if s.jwt_algorithm == "HS256":
        return {"keys": []}  # dev: sem chaves públicas
    # TODO: ler chave pública do disco e retornar
    return {"keys": []}


def _effective_permissions(p: Principal) -> set[str]:
    """Retorna todas as permissões efetivas do Principal (RBAC + scopes)."""
    from cip.api.jwt_auth import ROLE_PERMISSIONS
    base = ROLE_PERMISSIONS.get(p.role, set()) | set(p.scopes)
    if "*" in base:
        return {"*"}
    return base
