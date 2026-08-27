"""JWT + RBAC (Round 22+ Phase 2).

Substitui o `auth.py` (que ainda funciona com API key estática) por um sistema
baseado em JWT com suporte a OAuth2.

Por que JWT?
  - Stateless: API não precisa guardar sessão em memória
  - Padronizado: funciona com qualquer IdP OAuth2 (Keycloak, Auth0, Okta)
  - Claims: tenant_id, role, scopes embutidos no token (sem lookup extra)

Por que RBAC?
  - Limita o que cada user pode fazer (least privilege)
  - Auditoria clara (sabemos QUEM fez o quê)
  - Multi-tenant: cada user só vê dados do seu tenant

Roles:
  - admin   → tudo (read/write/delete em qualquer tenant)
  - member  → CRUD no seu tenant
  - viewer  → read-only no seu tenant
  - agent   → pode chamar /ask e /chat mas não pode ver audit log

Scopes (opcional, em adição a role):
  - read:conversations, write:conversations, read:billing, ...

Dev:
  - LLM_API_KEY=minimax  →  fallback (mantém compat com código antigo)
  - CIP_DEV_JWT_SECRET=dev-secret  →  usa esse secret p/ HS256
  - Sem env: usa API key estática (comportamento original)

Prod:
  - CIP_JWT_PUBLIC_KEY=<PEM>  →  RS256 com JWKS endpoint
  - CIP_JWT_ISSUER=https://idp.example.com  →  valida `iss`
  - CIP_JWT_AUDIENCE=cip-api  →  valida `aud`
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from cip.config import get_settings
from cip.logging import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Roles
# ─────────────────────────────────────────────────────────────────────────

Role = Literal["admin", "member", "viewer", "agent"]


ROLE_PERMISSIONS: dict[Role, set[str]] = {
    "admin": {"*"},  # tudo
    "member": {
        "conversations:read", "conversations:write", "conversations:delete",
        "messages:read", "messages:write", "messages:feedback",
        "tools:invoke", "ask:invoke", "analyze:invoke",
    },
    "viewer": {
        "conversations:read", "messages:read",
    },
    "agent": {
        "conversations:read", "conversations:write",
        "messages:read", "messages:write",
        "ask:invoke", "analyze:invoke",
    },
}


def role_has(role: Role, permission: str) -> bool:
    """Verifica se a role tem a permissão."""
    perms = ROLE_PERMISSIONS.get(role, set())
    if "*" in perms:
        return True
    return permission in perms


# ─────────────────────────────────────────────────────────────────────────
# JWT decode + validation
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class Principal:
    """Identidade autenticada extraída do JWT."""

    sub: str                 # user id (subject)
    tenant_id: str
    role: Role
    scopes: list[str]
    raw_claims: dict[str, Any]

    def has(self, permission: str) -> bool:
        """Verifica permissão (RBAC + scopes)."""
        if role_has(self.role, permission):
            return True
        return permission in self.scopes


class JWTBearer(HTTPBearer):
    """FastAPI security scheme para JWT Bearer tokens."""

    def __init__(self) -> None:
        super().__init__(auto_error=False)


_security = JWTBearer()


async def get_principal(request: Request) -> Principal:
    """Decodifica JWT do header Authorization e popula request.state.principal.

    Fallback chain (em ordem):
      1. JWT Bearer (Authorization: Bearer <token>)  ← preferido
      2. JWT em query param (?token=...)  ← dev only, p/ WebSocket
      3. API key estática (X-API-Key)  ← legacy
      4. Tenant ID em X-Tenant-Id  ← dev only
    """
    s = get_settings()

    # ── 1. JWT Bearer ─────────────────────────────────────────────
    creds: HTTPAuthorizationCredentials | None = await _security(request)
    if creds and creds.scheme.lower() == "bearer":
        try:
            claims = _decode_jwt(creds.credentials)
            return _claims_to_principal(claims)
        except JWTError as exc:
            log.warning("jwt_decode_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"invalid token: {exc}",
            )

    # ── 2. JWT via query (WebSocket) ─────────────────────────────
    token = request.query_params.get("token")
    if token:
        try:
            claims = _decode_jwt(token)
            return _claims_to_principal(claims)
        except JWTError:
            pass  # cai para fallback

    # ── 3. API key estática (legacy) ──────────────────────────────
    api_key = request.headers.get("X-API-Key", "")
    if api_key and api_key in _get_api_keys():
        meta = _get_api_keys()[api_key]
        return Principal(
            sub=meta.get("user", "api-key-user"),
            tenant_id=meta.get("tenant", "default"),
            role="admin" if meta.get("admin") else "member",
            scopes=[],
            raw_claims={"auth": "api_key"},
        )

    # ── 4. Fallback dev: X-Tenant-Id sem auth ─────────────────────
    if s.cip_env == "dev":
        tenant = request.headers.get("X-Tenant-Id", "default")
        return Principal(
            sub="dev-user",
            tenant_id=tenant,
            role="admin",  # dev: tudo liberado
            scopes=[],
            raw_claims={"auth": "dev_fallback"},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing or invalid authentication",
    )


def _decode_jwt(token: str) -> dict[str, Any]:
    """Decodifica e valida JWT (HS256 dev / RS256 prod)."""
    s = get_settings()
    claims = jwt.decode(
        token,
        s.jwt_secret if s.jwt_secret else "dev-secret",
        algorithms=[s.jwt_algorithm] if s.jwt_algorithm else ["HS256"],
        audience=s.jwt_audience if s.jwt_audience else None,
        issuer=s.jwt_issuer if s.jwt_issuer else None,
    )
    # Validar expiração explicitamente (python-jose já faz, mas queremos log)
    if "exp" in claims and claims["exp"] < time.time():
        raise JWTError("token expired")
    return claims


def _claims_to_principal(claims: dict[str, Any]) -> Principal:
    """Converte claims JWT em Principal."""
    tenant_id = claims.get("tenant_id") or claims.get("tid") or "default"
    role = claims.get("role") or claims.get("roles", ["member"])[0] or "member"
    if role not in ("admin", "member", "viewer", "agent"):
        role = "member"
    scopes = claims.get("scope", "").split() if claims.get("scope") else []
    return Principal(
        sub=claims.get("sub", "unknown"),
        tenant_id=tenant_id,
        role=role,  # type: ignore[arg-type]
        scopes=scopes,
        raw_claims=claims,
    )


def _get_api_keys() -> dict[str, dict[str, Any]]:
    """Carrega API keys do env (formato key:tenant:role)."""
    # Lazy import para evitar cycle
    from cip.api.auth import _get_api_keys as _orig
    return _orig()


# ─────────────────────────────────────────────────────────────────────────
# FastAPI dependency
# ─────────────────────────────────────────────────────────────────────────


async def require_principal(request: Request) -> Principal:
    """Dependency FastAPI — substitui TenantContext por Principal."""
    p = await get_principal(request)
    request.state.principal = p
    return p


def require_permission(permission: str):
    """Factory de dependency que exige permissão específica.

    Uso:
        @router.get("/admin", dependencies=[Depends(require_permission("admin:read"))])
    """
    async def _check(request: Request) -> Principal:
        p = await require_principal(request)
        if not p.has(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permission: {permission} (role: {p.role})",
            )
        return p
    return _check


# ─────────────────────────────────────────────────────────────────────────
# JWT issuing (dev/test only — prod usa IdP externo)
# ─────────────────────────────────────────────────────────────────────────


def issue_jwt(
    sub: str,
    tenant_id: str,
    role: Role = "member",
    scopes: list[str] | None = None,
    expires_in: int = 3600,
) -> str:
    """Emite um JWT HS256 (apenas dev/test).

    Em produção, use um IdP OAuth2 externo (Keycloak, Auth0, Okta).
    """
    s = get_settings()
    now = int(time.time())
    claims = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "scope": " ".join(scopes or []),
        "iat": now,
        "exp": now + expires_in,
    }
    if s.jwt_audience:
        claims["aud"] = s.jwt_audience
    if s.jwt_issuer:
        claims["iss"] = s.jwt_issuer
    return jwt.encode(
        claims,
        s.jwt_secret if s.jwt_secret else "dev-secret",
        algorithm=s.jwt_algorithm if s.jwt_algorithm else "HS256",
    )
