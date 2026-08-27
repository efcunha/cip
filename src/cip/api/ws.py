"""WebSocket endpoint para notificações cross-device (Round 22+ Phase 2).

Endpoint: WS /ws/chat?conversation_id=...&token=...

Por que WebSocket (e não SSE):
  - SSE é unidirecional (server -> client). Bom para stream de tokens.
  - WebSocket é bidirecional. Necessário para:
      - Notificar OUTROS devices do mesmo user quando nova msg chega
      - Receber eventos de typing indicator
      - Heartbeat bidirecional
      - Sincronização de feedback em tempo real

Eventos suportados (server -> client):
  - conversation_updated: metadata/title changed
  - message_added: nova msg (user ou assistant) na conversa
  - feedback_changed: user togglou 👍/👎 em alguma mensagem
  - ping: heartbeat (a cada 30s)

Eventos suportados (client -> server):
  - subscribe: {conversation_id} - subscribe aos eventos dessa conversa
  - unsubscribe: {conversation_id}
  - pong: resposta ao ping do server
  - typing: {conversation_id, is_typing} - "fulano está digitando..."

Auth: query param `token` (JWT) ou header `Authorization: Bearer <token>`.
      (implementação completa do JWT na feature de Auth/SSO — por enquanto
      aceita `?tenant_id=...` como fallback para dev)

Pub/sub: in-memory dict {tenant_id: {conversation_id: set(WebSocket)}}.
        Para produção multi-pod, trocar por Redis pub/sub.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from cip.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["websocket"])


# ─────────────────────────────────────────────────────────────────────────
# In-memory pub/sub (dev single-pod; trocar por Redis em prod)
# ─────────────────────────────────────────────────────────────────────────


class _Subscription:
    """Estado de uma subscription WebSocket."""

    def __init__(self, ws: WebSocket, tenant_id: str, conversations: set[str] | None = None):
        self.ws = ws
        self.tenant_id = tenant_id
        self.conversations = conversations or set()  # se vazio = subscribe a TUDO do tenant
        self.created_at = time.time()


class _PubSub:
    """Manager de subscriptions + helpers de broadcast."""

    def __init__(self) -> None:
        self._subs: list[_Subscription] = []
        self._lock = asyncio.Lock()

    async def add(self, sub: _Subscription) -> None:
        async with self._lock:
            self._subs.append(sub)

    async def remove(self, sub: _Subscription) -> None:
        async with self._lock:
            try:
                self._subs.remove(sub)
            except ValueError:
                pass

    async def broadcast(
        self, event: str, data: dict[str, Any], conversation_id: str | None = None,
    ) -> int:
        """Envia evento para todos subscribers relevantes.

        Returns: número de clients notificados.
        """
        msg = json.dumps({"event": event, "data": data, "ts": time.time()})
        notified = 0
        async with self._lock:
            targets = list(self._subs)
        for sub in targets:
            # Match: mesmo tenant E (sem conversation_id OR subscribed)
            if sub.tenant_id != data.get("tenant_id"):
                continue
            if conversation_id is not None:
                if sub.conversations and conversation_id not in sub.conversations:
                    continue
            try:
                await sub.ws.send_text(msg)
                notified += 1
            except Exception:  # noqa: BLE001
                # Socket morto — remove depois
                pass
        return notified


pubsub = _PubSub()


# ─────────────────────────────────────────────────────────────────────────
# Schema de mensagens
# ─────────────────────────────────────────────────────────────────────────


class SubscribeReq(BaseModel):
    event: str
    conversation_id: str | None = None


class TypingReq(BaseModel):
    event: str = "typing"
    conversation_id: str
    is_typing: bool = True


# ─────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────


@router.websocket("/ws/chat")
async def chat_websocket(
    websocket: WebSocket,
    tenant_id: str = Query("default", description="Tenant ID (dev: ?tenant_id=)"),
    conversation_id: str | None = Query(None, description="Auto-subscribe a uma conversa"),
    token: str | None = Query(None, description="JWT (futuro — feature Auth/SSO)"),
) -> None:
    """Conexão WebSocket principal do chat.

    Fluxo:
      1. accept() + handshake (envia `connected`)
      2. Loop: recebe mensagens do cliente, processa (subscribe/typing/pong)
      3. Em paralelo: envia pings a cada 30s (heartbeat)
      4. Cleanup no disconnect
    """
    # ── Auth (Round 22+ Phase 2: aceitar tenant_id como fallback; JWT virá na feature Auth) ──
    if not tenant_id:
        await websocket.close(code=4001, reason="missing tenant_id")
        return

    await websocket.accept()
    sub = _Subscription(websocket, tenant_id, {conversation_id} if conversation_id else None)
    await pubsub.add(sub)

    log.info("ws_connected", tenant_id=tenant_id, conversation_id=conversation_id)

    try:
        # ── Mensagem de boas-vindas ────────────────────────────────
        await websocket.send_json({
            "event": "connected",
            "data": {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "server_time": time.time(),
            },
        })

        # ── Loop principal + heartbeat em paralelo ───────────────
        async def receive_loop():
            while True:
                msg = await websocket.receive_text()
                try:
                    data = json.loads(msg)
                    ev = data.get("event")
                    if ev == "subscribe":
                        conv_id = data.get("conversation_id")
                        if conv_id:
                            sub.conversations.add(conv_id)
                            await websocket.send_json({
                                "event": "subscribed",
                                "data": {"conversation_id": conv_id},
                            })
                    elif ev == "unsubscribe":
                        conv_id = data.get("conversation_id")
                        if conv_id:
                            sub.conversations.discard(conv_id)
                    elif ev == "pong":
                        pass  # só não deixa morrer
                    elif ev == "typing":
                        # Repassa para outros clients na mesma conversa
                        conv_id = data.get("conversation_id")
                        if conv_id:
                            await pubsub.broadcast(
                                "typing",
                                {
                                    **data,
                                    "tenant_id": tenant_id,
                                },
                                conversation_id=conv_id,
                            )
                except json.JSONDecodeError:
                    pass  # ignora mensagens inválidas

        async def heartbeat_loop():
            while True:
                await asyncio.sleep(30)
                try:
                    await websocket.send_json({"event": "ping", "data": {"ts": time.time()}})
                except Exception:  # noqa: BLE001
                    break

        # Roda ambos em paralelo — qualquer um quebrar encerra a conexão
        await asyncio.gather(
            receive_loop(),
            heartbeat_loop(),
            return_exceptions=True,
        )

    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("ws_error", error=str(exc), tenant_id=tenant_id)
    finally:
        await pubsub.remove(sub)
        log.info("ws_disconnected", tenant_id=tenant_id, conversation_id=conversation_id)


# ─────────────────────────────────────────────────────────────────────────
# Helpers para outros módulos emitirem eventos
# ─────────────────────────────────────────────────────────────────────────


async def notify_message_added(tenant_id: str, conversation_id: str, msg: dict[str, Any]) -> None:
    """Chamado pelo chat.py quando uma message é adicionada."""
    await pubsub.broadcast(
        "message_added",
        {"tenant_id": tenant_id, "conversation": conversation_id, "message": msg},
        conversation_id=conversation_id,
    )


async def notify_feedback_changed(
    tenant_id: str, conversation_id: str, msg_id: str, feedback: str
) -> None:
    """Chamado pelo endpoint de feedback."""
    await pubsub.broadcast(
        "feedback_changed",
        {
            "tenant_id": tenant_id,
            "conversation": conversation_id,
            "msg_id": msg_id,
            "feedback": feedback,
        },
        conversation_id=conversation_id,
    )
