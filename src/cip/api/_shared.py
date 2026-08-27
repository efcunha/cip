"""Helpers compartilhados entre routers (evita circular imports).

Coloque aqui coisas que `app.py`, `chat.py` e futuros routers precisam
compartilhar, sem que um precise importar o outro.
"""
from __future__ import annotations

from fastapi import Request

from cip.api.auth import TenantContext, authenticate


async def get_tenant(request: Request) -> TenantContext:
    """Dependency FastAPI: autentica request e popula request.state.tenant.

    Usado em TODOS os routers via Depends(get_tenant). Quebra o ciclo:
    app.py -> chat.py -> _shared.py (em vez de app.py -> chat.py -> app.py).
    """
    ctx = authenticate(request)
    request.state.tenant = ctx
    return ctx
