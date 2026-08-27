"""Guardas de segurança comuns às tools.

Toda tool DEVE ser read-only. A trava `CIP_READONLY` é verificada aqui e qualquer
ação potencialmente mutante levanta exceção antes de tocar a API da cloud.
"""

from __future__ import annotations

from cip.config import get_settings
from cip.logging import get_logger

log = get_logger(__name__)

# Verbos que jamais podem ser executados pelas tools.
_MUTATING_PREFIXES = (
    "create", "delete", "update", "put", "modify", "terminate", "run", "start",
    "stop", "attach", "detach", "authorize", "revoke", "set", "remove", "add",
)


class WriteOperationBlocked(RuntimeError):
    """Levantada quando uma operação mutante é tentada em modo read-only."""


def assert_readonly(operation: str) -> None:
    settings = get_settings()
    op = operation.lower().lstrip("get").lstrip("_")
    if settings.cip_readonly and operation.lower().startswith(_MUTATING_PREFIXES):
        log.error("write_blocked", operation=operation)
        raise WriteOperationBlocked(
            f"Operação '{operation}' bloqueada: CIP opera em modo read-only."
        )
