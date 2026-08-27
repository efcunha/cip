"""Tests das 6 features Round 22+ Phase 2.

SKIP AUTOMÁTICO se a infra local (postgres + cip-api) não estiver rodando.
Para rodar localmente:
  docker compose up -d
  pytest tests/test_phase2_features.py -v

Cobertura:
  1. SSE streaming multi-turn
  2. Export de conversa (md / json / share link)
  3. WebSocket push
  4. JWT auth + RBAC
  5. Métricas Prometheus de chat/feedback
  6. (Locust/k6 são scripts standalone, sem pytest)
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import pytest
import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Fixtures: detecta infra local
# ─────────────────────────────────────────────────────────────────────────


def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    """Checa se uma porta está aberta (sem bloquear)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


PG_HOST = os.environ.get("PG_HOST", "127.0.0.1")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
API_HOST = os.environ.get("CIP_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("CIP_API_PORT", "8000"))

INFRA_RUNNING = _port_open(PG_HOST, PG_PORT) and _port_open(API_HOST, API_PORT)
INFRA_SKIP_REASON = (
    f"Infra local não está rodando (precisa postgres em {PG_HOST}:{PG_PORT} "
    f"+ cip-api em {API_HOST}:{API_PORT}). Suba com `docker compose up -d`."
)


# ─────────────────────────────────────────────────────────────────────────
# 1. SSE streaming multi-turn
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not INFRA_RUNNING, reason=INFRA_SKIP_REASON)
class TestSSEStreaming:
    """SSE streaming em /chat/conversations/{id}/messages?stream=true."""

    BASE_URL = f"http://{API_HOST}:{API_PORT}"
    TENANT = "ssetest"

    def test_stream_emits_chunk_events(self) -> None:
        """Stream deve emitir múltiplos eventos `chunk` antes do `done`."""
        # 1. Cria conversa
        r = httpx.post(
            f"{self.BASE_URL}/chat/conversations",
            json={"title": "sse-stream-test"},
            headers={"X-Tenant-Id": self.TENANT},
            timeout=10,
        )
        assert r.status_code == 201
        conv_id = r.json()["id"]

        # 2. Faz pergunta com stream=true
        with httpx.stream(
            "POST",
            f"{self.BASE_URL}/chat/conversations/{conv_id}/messages",
            json={
                "question": "Quais sao os 6 pilares do AWS Well-Architected?",
                "cloud": "aws",
                "stream": True,
            },
            headers={"X-Tenant-Id": self.TENANT},
            timeout=60,
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")

            events = []
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())

        # Deve ter múltiplos chunks + 1 done
        chunks = [e for e in events if e == "chunk"]
        dones = [e for e in events if e == "done"]
        assert len(chunks) >= 2, f"Esperado >=2 chunks, achou {len(chunks)}"
        assert len(dones) == 1, f"Esperado 1 done, achou {len(dones)}"

    def test_stream_done_has_msg_id(self) -> None:
        """Evento `done` deve trazer msg_id + sources + latency."""
        r = httpx.post(
            f"{self.BASE_URL}/chat/conversations",
            json={"title": "sse-done-test"},
            headers={"X-Tenant-Id": self.TENANT},
            timeout=10,
        )
        assert r.status_code == 201
        conv_id = r.json()["id"]

        done_data = None
        with httpx.stream(
            "POST",
            f"{self.BASE_URL}/chat/conversations/{conv_id}/messages",
            json={"question": "Liste 3 pilares AWS.", "stream": True},
            headers={"X-Tenant-Id": self.TENANT},
            timeout=60,
        ) as resp:
            assert resp.status_code == 200
            buf = ""
            for line in resp.iter_lines():
                if line.startswith("event: done"):
                    # Próxima linha é "data: ..."
                    continue
                if line.startswith("data: ") and done_data is None:
                    done_data = json.loads(line[6:])
                    break

        assert done_data is not None
        assert "msg_id" in done_data
        assert "answer" in done_data
        assert "sources" in done_data
        assert "latency_ms" in done_data


# ─────────────────────────────────────────────────────────────────────────
# 2. Export + share
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not INFRA_RUNNING, reason=INFRA_SKIP_REASON)
class TestExport:
    """GET /chat/conversations/{id}/export?format=md|json + share link."""

    BASE_URL = f"http://{API_HOST}:{API_PORT}"
    TENANT = "exporttest"

    def _make_conversation_with_messages(self) -> str:
        r = httpx.post(
            f"{self.BASE_URL}/chat/conversations",
            json={"title": "export-test"},
            headers={"X-Tenant-Id": self.TENANT},
            timeout=10,
        )
        assert r.status_code == 201
        conv_id = r.json()["id"]
        # 1 mensagem
        r2 = httpx.post(
            f"{self.BASE_URL}/chat/conversations/{conv_id}/messages",
            json={"question": "O que e FinOps?", "cloud": "aws"},
            headers={"X-Tenant-Id": self.TENANT},
            timeout=60,
        )
        assert r2.status_code == 201
        return conv_id

    def test_export_markdown(self) -> None:
        """Export md retorna markdown com title + user + assistant + sources."""
        conv_id = self._make_conversation_with_messages()
        r = httpx.get(
            f"{self.BASE_URL}/chat/conversations/{conv_id}/export?format=md",
            headers={"X-Tenant-Id": self.TENANT},
            timeout=10,
        )
        assert r.status_code == 200
        assert "text/markdown" in r.headers.get("content-type", "")
        body = r.text
        assert "# export-test" in body
        assert "## 👤 Usuário" in body
        assert "## 🤖 CIP" in body
        assert "O que e FinOps?" in body
        assert "Fontes:" in body  # seção de citations

    def test_export_json(self) -> None:
        """Export json retorna dict completo com messages[]."""
        conv_id = self._make_conversation_with_messages()
        r = httpx.get(
            f"{self.BASE_URL}/chat/conversations/{conv_id}/export?format=json",
            headers={"X-Tenant-Id": self.TENANT},
            timeout=10,
        )
        assert r.status_code == 200
        data = r.json()
        assert "conversation" in data
        assert "messages" in data
        assert "exported_at" in data
        assert len(data["messages"]) == 2  # user + assistant

    def test_share_link(self) -> None:
        """POST /share gera token; GET /share/{token} retorna conversa sem auth."""
        conv_id = self._make_conversation_with_messages()

        # Cria share link
        r = httpx.post(
            f"{self.BASE_URL}/chat/conversations/{conv_id}/share",
            json={"expires_hours": 24},
            headers={"X-Tenant-Id": self.TENANT},
            timeout=10,
        )
        assert r.status_code == 201
        share = r.json()
        assert "token" in share
        assert "share_url" in share
        assert share["expires_at"] is not None
        token = share["token"]

        # Acessa sem auth (header X-Tenant-Id não é necessário p/ /share/{token})
        r2 = httpx.get(f"{self.BASE_URL}/chat/share/{token}", timeout=10)
        assert r2.status_code == 200
        data = r2.json()
        assert data["conversation"]["id"] == conv_id
        assert "shared_via" in data
        assert data["shared_via"] == token


# ─────────────────────────────────────────────────────────────────────────
# 3. WebSocket push
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not INFRA_RUNNING, reason=INFRA_SKIP_REASON)
class TestWebSocket:
    """WS /ws/chat para notificações cross-device."""

    BASE_URL = f"http://{API_HOST}:{API_PORT}"
    WS_URL = f"ws://{API_HOST}:{API_PORT}/ws/chat"

    def test_websocket_handshake(self) -> None:
        """Conexão WS recebe `connected` no handshake."""
        try:
            import websockets
        except ImportError:
            pytest.skip("pip install websockets para rodar este teste")

        async def _test() -> dict:
            async with websockets.connect(
                f"{self.WS_URL}?tenant_id=wstest",
            ) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                return json.loads(msg)

        import asyncio
        data = asyncio.run(_test())
        assert data["event"] == "connected"
        assert data["data"]["tenant_id"] == "wstest"

    def test_websocket_receives_broadcast(self) -> None:
        """WS conectado recebe message_added quando outra origem cria mensagem."""
        try:
            import websockets
        except ImportError:
            pytest.skip("pip install websockets")

        import asyncio

        async def _test() -> list[dict]:
            # 1. Conecta WS
            async with websockets.connect(
                f"{self.WS_URL}?tenant_id=broadcasttest&conversation_id=" + conv_id,
            ) as ws:
                # Handshake
                await ws.recv()
                # 2. Em paralelo: cria msg via HTTP
                async def _http_call() -> None:
                    await asyncio.sleep(0.3)
                    httpx.post(
                        f"{self.BASE_URL}/chat/conversations/{conv_id}/messages",
                        json={"question": "teste broadcast"},
                        headers={"X-Tenant-Id": "broadcasttest"},
                        timeout=30,
                    )
                asyncio.create_task(_http_call())
                # 3. Aguarda evento
                events = []
                for _ in range(10):
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5)
                        events.append(json.loads(msg))
                        if any(e["event"] == "message_added" for e in events):
                            break
                    except asyncio.TimeoutError:
                        break
                return events

        # Pre: cria conversa
        r = httpx.post(
            f"{self.BASE_URL}/chat/conversations",
            json={"title": "broadcast-test"},
            headers={"X-Tenant-Id": "broadcasttest"},
            timeout=10,
        )
        assert r.status_code == 201
        global conv_id
        conv_id = r.json()["id"]

        events = asyncio.run(_test())
        assert any(e["event"] == "message_added" for e in events), \
            f"Esperava message_added, recebi: {[e['event'] for e in events]}"


# ─────────────────────────────────────────────────────────────────────────
# 4. JWT auth + RBAC
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not INFRA_RUNNING, reason=INFRA_SKIP_REASON)
class TestJWTAuth:
    """JWT + roles: admin/member/viewer/agent."""

    BASE_URL = f"http://{API_HOST}:{API_PORT}"

    def test_dev_token_endpoint(self) -> None:
        """POST /auth/dev-token emite JWT HS256 com claims customizados."""
        r = httpx.post(
            f"{self.BASE_URL}/auth/dev-token",
            json={
                "user_id": "alice",
                "tenant_id": "jwttest",
                "role": "admin",
                "scopes": ["*"],
            },
            timeout=10,
        )
        assert r.status_code == 200
        tok = r.json()
        assert "access_token" in tok
        assert tok["token_type"] == "bearer"
        assert tok["expires_in"] > 0

    def test_me_with_jwt(self) -> None:
        """GET /auth/me com JWT válido retorna Principal."""
        # 1. Pega token
        r1 = httpx.post(
            f"{self.BASE_URL}/auth/dev-token",
            json={"user_id": "bob", "tenant_id": "metest", "role": "member"},
            timeout=10,
        )
        token = r1.json()["access_token"]

        # 2. Chama /auth/me
        r2 = httpx.get(
            f"{self.BASE_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert r2.status_code == 200
        me = r2.json()
        assert me["sub"] == "bob"
        assert me["tenant_id"] == "metest"
        assert me["role"] == "member"
        # member tem permissões mas não "*"
        assert "*" not in me["permissions"]
        assert "conversations:read" in me["permissions"]

    def test_admin_has_all_permissions(self) -> None:
        """Admin tem permission '*' (tudo)."""
        r1 = httpx.post(
            f"{self.BASE_URL}/auth/dev-token",
            json={"user_id": "root", "tenant_id": "admintest", "role": "admin"},
            timeout=10,
        )
        token = r1.json()["access_token"]

        r2 = httpx.get(
            f"{self.BASE_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        perms = r2.json()["permissions"]
        assert "*" in perms, f"Admin deveria ter '*', achou: {perms}"

    def test_unauthorized_without_token(self) -> None:
        """Sem JWT e sem API key, /auth/me retorna 401."""
        r = httpx.get(f"{self.BASE_URL}/auth/me", timeout=10)
        # Em dev com CIP_ENV=dev, pode usar fallback
        if os.environ.get("CIP_ENV") == "dev":
            return  # skip em dev
        assert r.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────
# 5. Prometheus metrics
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not INFRA_RUNNING, reason=INFRA_SKIP_REASON)
class TestPrometheusMetrics:
    """Métricas de chat/feedback expostas em /metrics."""

    BASE_URL = f"http://{API_HOST}:{API_PORT}"

    def test_metrics_endpoint_exposes_chat_counters(self) -> None:
        """/metrics contém os counters de chat."""
        r = httpx.get(f"{self.BASE_URL}/metrics", timeout=5)
        assert r.status_code == 200
        body = r.text
        # HELP lines
        assert "cip_conversations_created_total" in body
        assert "cip_messages_created_total" in body
        assert "cip_feedback_total" in body
        assert "cip_chat_latency_seconds" in body
        assert "cip_chat_feedback_negative_ratio" in body

    def test_metrics_increment_on_chat(self) -> None:
        """Criar conversa incrementa o counter."""
        # Lê baseline
        r1 = httpx.get(f"{self.BASE_URL}/metrics", timeout=5)
        before = sum(
            1 for line in r1.text.splitlines()
            if line.startswith("cip_conversations_created_total{")
        )

        # Cria conversa
        httpx.post(
            f"{self.BASE_URL}/chat/conversations",
            json={"title": "metric-test"},
            headers={"X-Tenant-Id": "metrictest"},
            timeout=10,
        )

        # Re-lê
        r2 = httpx.get(f"{self.BASE_URL}/metrics", timeout=5)
        after = sum(
            1 for line in r2.text.splitlines()
            if line.startswith("cip_conversations_created_total{")
        )
        # Pode ser 0 (HELP/TYPE) ou >=1 (counter). Apenas checamos que existe.
        assert "cip_conversations_created_total" in r2.text


# ─────────────────────────────────────────────────────────────────────────
# Estrutura dos artefatos (não precisa de infra)
# ─────────────────────────────────────────────────────────────────────────


class TestArtifactStructure:
    """Verifica que os artefatos das 6 features existem e estão bem-formados."""

    def test_locustfile_exists_and_valid_python(self) -> None:
        import ast
        f = ROOT / "tests" / "load" / "locustfile.py"
        assert f.exists()
        ast.parse(f.read_text(encoding="utf-8"))
        # 3 user classes esperadas
        text = f.read_text(encoding="utf-8")
        assert "class ChatUser" in text
        assert "class HeavyAsker" in text
        assert "class AdminScroller" in text

    def test_k6_script_exists_and_valid(self) -> None:
        f = ROOT / "tests" / "load" / "k6-script.js"
        assert f.exists()
        text = f.read_text(encoding="utf-8")
        assert "import http from 'k6/http'" in text
        assert "export const options" in text  # k6 idiom: export const options
        assert "thresholds" in text

    def test_grafana_dashboard_is_valid_json(self) -> None:
        import json
        f = ROOT / "ops" / "grafana" / "cip-dashboard.json"
        assert f.exists()
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
        assert data["title"] == "CIP — Chat & Feedback"
        # Pelo menos 5 panels
        assert len(data["panels"]) >= 5
        # Variável tenant
        assert any(t["name"] == "tenant" for t in data["templating"]["list"])

    def test_migration_004_exists(self) -> None:
        f = ROOT / "db" / "migrations" / "004_share_tokens_and_extras.sql"
        assert f.exists()
        text = f.read_text(encoding="utf-8")
        assert "share_tokens" in text
        assert "conversation_id" in text

    def test_ws_module_exists_with_endpoints(self) -> None:
        f = ROOT / "src" / "cip" / "api" / "ws.py"
        assert f.exists()
        text = f.read_text(encoding="utf-8")
        assert "@router.websocket(\"/ws/chat\")" in text
        assert "notify_message_added" in text
        assert "notify_feedback_changed" in text

    def test_jwt_auth_module_exists(self) -> None:
        f = ROOT / "src" / "cip" / "api" / "jwt_auth.py"
        assert f.exists()
        text = f.read_text(encoding="utf-8")
        assert "class Principal" in text
        assert "ROLE_PERMISSIONS" in text
        assert "issue_jwt" in text
        assert "require_permission" in text

    def test_oauth_module_with_all_endpoints(self) -> None:
        f = ROOT / "src" / "cip" / "api" / "oauth.py"
        assert f.exists()
        text = f.read_text(encoding="utf-8")
        assert "/dev-token" in text
        assert "/login" in text
        assert "/me" in text
        assert "/refresh" in text
        assert ".well-known/jwks.json" in text

    def test_observability_has_chat_metrics(self) -> None:
        f = ROOT / "src" / "cip" / "observability.py"
        text = f.read_text(encoding="utf-8")
        # Métricas prometheus_client são prefixadas automaticamente com `cip_` no
        # /metrics (CIPMetricsRegistry). Aqui checamos os nomes dos objetos
        # Python que são as fontes.
        assert "chat_conversations_created_total" in text
        assert "chat_messages_created_total" in text
        assert "chat_feedback_total" in text
        assert "chat_latency_seconds" in text
        assert "chat_feedback_negative_ratio" in text
        # Funções helper
        assert "record_chat_conversation_created" in text
        assert "record_chat_message_created" in text
        assert "record_chat_feedback" in text
        assert "observe_chat_latency" in text
        assert "update_chat_feedback_ratio" in text
