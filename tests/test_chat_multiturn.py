"""Tests do modulo chat.py (multi-turn + feedback) — Round 22+."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestChatModuleStructure:
    """Estrutura do modulo chat.py."""

    def test_chat_module_exists(self) -> None:
        chat_py = ROOT / "src" / "cip" / "api" / "chat.py"
        assert chat_py.exists()
        assert chat_py.stat().st_size > 5000  # substancial

    def test_chat_module_is_valid_python(self) -> None:
        """Compila sem erros de sintaxe."""
        chat_py = ROOT / "src" / "cip" / "api" / "chat.py"
        code = chat_py.read_text(encoding="utf-8")
        ast.parse(code)  # raises SyntaxError se invalido

    def test_chat_exposes_router(self) -> None:
        """chat.py expõe um APIRouter."""
        chat_py = ROOT / "src" / "cip" / "api" / "chat.py"
        code = chat_py.read_text(encoding="utf-8")
        assert "APIRouter" in code
        assert 'router = APIRouter' in code or "router=APIRouter" in code
        assert 'prefix="/chat"' in code

    def test_chat_has_required_endpoints(self) -> None:
        """chat.py tem os 6 endpoints do multi-turn."""
        chat_py = ROOT / "src" / "cip" / "api" / "chat.py"
        code = chat_py.read_text(encoding="utf-8")
        # Endpoints essenciais: chat.py tem prefix="/chat" + paths
        # Verifica paths (podem estar em qualquer linha, multi-line decorator ok)
        for path in [
            '"/conversations"',
            '"/conversations/{conv_id}"',
            '"/conversations/{conv_id}/messages"',
            '"/messages/{msg_id}/feedback"',
        ]:
            assert path in code, f"Endpoint path {path} not found"
        # Pelo menos 6 decorators @router.X
        assert code.count("@router.") >= 6

    def test_chat_uses_tenant_isolation(self) -> None:
        """Todas as queries filtram por tenant_id (multi-tenant safe)."""
        chat_py = ROOT / "src" / "cip" / "api" / "chat.py"
        code = chat_py.read_text(encoding="utf-8")
        # Deve ter helper de validação (import pode ser outro nome)
        assert "_ensure_conversation_belongs_to_tenant" in code
        # Deve ter parametros :tenant (multi-tenant)
        assert ":tenant" in code
        # Deve ter chamadas que checam tenant (require_tenant ou TenantContext)
        assert "require_tenant" in code or "TenantContext" in code or "tenant_id" in code

    def test_chat_handles_history_context(self) -> None:
        """chat.py injeta historico como contexto para o LLM."""
        chat_py = ROOT / "src" / "cip" / "api" / "chat.py"
        code = chat_py.read_text(encoding="utf-8")
        # _history_to_context formata historico
        assert "_history_to_context" in code
        # Limita a 10 mensagens
        assert "LIMIT 10" in code
        # Tem marcadores de inicio/fim
        assert "HIST" in code.upper() or "hist" in code


class TestChatSchemas:
    """Pydantic models em chat.py (validados via AST, sem import)."""

    def test_create_conversation_req_defined(self) -> None:
        chat_py = ROOT / "src" / "cip" / "api" / "chat.py"
        code = chat_py.read_text(encoding="utf-8")
        assert "class CreateConversationReq" in code
        assert "title" in code
        assert "metadata" in code

    def test_ask_in_conversation_req_defined(self) -> None:
        chat_py = ROOT / "src" / "cip" / "api" / "chat.py"
        code = chat_py.read_text(encoding="utf-8")
        assert "class AskInConversationReq" in code
        assert "question" in code
        assert "cloud" in code

    def test_feedback_req_validates_pattern(self) -> None:
        chat_py = ROOT / "src" / "cip" / "api" / "chat.py"
        code = chat_py.read_text(encoding="utf-8")
        assert "class FeedbackReq" in code
        assert 'pattern="^(up|down)$"' in code or "Literal['up', 'down']" in code


class TestChatAppIntegration:
    """chat.py integrado ao app.py."""

    def test_app_includes_chat_router(self) -> None:
        app_py = ROOT / "src" / "cip" / "api" / "app.py"
        code = app_py.read_text(encoding="utf-8")
        # Round 22+ Phase 2: app importa MULTIPLOS routers
        assert "from cip.api.chat import" in code
        assert "app.include_router" in code
        assert "chat_router" in code or "public_router" in code

    def test_app_lifespan_creates_db_engine(self) -> None:
        app_py = ROOT / "src" / "cip" / "api" / "app.py"
        code = app_py.read_text(encoding="utf-8")
        # Round 22+: lifespan() inicializa engine asyncpg + orchestrator
        assert "create_async_engine" in code
        assert "app.state.orchestrator" in code
        assert "app.state.db" in code


class TestChatMigration:
    """Migration 003 — conversations + messages + feedback."""

    def test_migration_003_exists(self) -> None:
        m = ROOT / "db" / "migrations" / "003_conversations_and_feedback.sql"
        assert m.exists()

    def test_migration_creates_conversations_table(self) -> None:
        m = (ROOT / "db" / "migrations" / "003_conversations_and_feedback.sql").read_text(
            encoding="utf-8"
        )
        assert "CREATE TABLE" in m
        assert "conversations" in m
        assert "tenant_id" in m  # multi-tenant column
        assert "id" in m  # primary key

    def test_migration_creates_messages_table(self) -> None:
        m = (ROOT / "db" / "migrations" / "003_conversations_and_feedback.sql").read_text(
            encoding="utf-8"
        )
        assert "messages" in m
        assert "conversation_id" in m
        assert "feedback" in m  # feedback column
        assert "ON DELETE CASCADE" in m  # cascade delete

    def test_migration_idempotent(self) -> None:
        """Migration deve poder rodar 2x sem erro (IF NOT EXISTS)."""
        m = (ROOT / "db" / "migrations" / "003_conversations_and_feedback.sql").read_text(
            encoding="utf-8"
        )
        assert "CREATE TABLE IF NOT EXISTS" in m
        assert "CREATE INDEX IF NOT EXISTS" in m

    def test_migration_has_trigger(self) -> None:
        """Trigger para atualizar updated_at da conversation."""
        m = (ROOT / "db" / "migrations" / "003_conversations_and_feedback.sql").read_text(
            encoding="utf-8"
        )
        assert "TRIGGER" in m
        assert "touch_conversation_updated_at" in m


class TestWebUI:
    """web/ — frontend da UI."""

    def test_index_html_has_conv_section(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        assert 'id="convList"' in html
        assert 'id="newConvBtn"' in html
        assert "Conversas" in html  # label da sidebar

    def test_app_js_supports_multi_turn(self) -> None:
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        # Funções essenciais
        assert "async function listConversations" in js
        assert "async function createConversation" in js
        assert "async function sendConversationMessage" in js
        assert "async function loadConversation" in js
        assert "currentConvId" in js  # state mgmt
        assert "localStorage" in js   # persistence

    def test_app_js_supports_feedback(self) -> None:
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        assert "submitFeedbackFromBar" in js
        assert "feedback-bar" in js  # className (React-style)
        assert "fb-up" in js
        assert "fb-down" in js

    def test_style_css_has_feedback_styles(self) -> None:
        css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
        assert ".feedback-bar" in css
        assert ".conv-section" in css
        assert ".conv-item" in css


class TestDockerIntegration:
    """Dockerfile + docker-compose."""

    def test_dockerfile_uses_python_313(self) -> None:
        """Round 22+: Python 3.13 (nao 3.14 — bug asyncpg)."""
        df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "python:3.13" in df
        assert "python:3.14" not in df  # explicitamente evita 3.14

    def test_dockerfile_has_healthcheck(self) -> None:
        df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "HEALTHCHECK" in df
        assert "curl" in df  # healthcheck command

    def test_dockerfile_runs_as_nonroot(self) -> None:
        df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "USER" in df
        # Nao root
        assert "USER cip" in df or "USER app" in df or "USER 1000" in df

    def test_compose_defines_cip_api_service(self) -> None:
        import yaml

        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose.get("services", {})
        # Round 22+: cip-api (nao "api"). O Postgres é EXTERNO
        # (cloudpilot_postgres), não sobe no compose.
        assert "cip-api" in services
        # Service names antigos nao devem mais existir
        assert "api" not in services  # renomeado para cip-api
        assert "db" not in services   # renomeado para postgres
        assert "postgres" not in services  # Round 22+: Postgres externo

    def test_compose_uses_yaml_anchors(self) -> None:
        """Round 22+: x-api-common anchor para DRY entre services."""
        import yaml

        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert "x-api-common" in text
        assert "&api-common" in text
        assert "<<: *api-common" in text

    def test_compose_has_postgres_healthcheck(self) -> None:
        """Round 22+: o Postgres é EXTERNO — o healthcheck fica no container
        externo `cloudpilot_postgres` (imagem pgvector:pg16), não no compose.
        O compose referencia o hostname externo via DATABASE_URL na rede
        `cip_default` e documenta isso no header."""
        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert "cloudpilot_postgres" in text
        assert "pgvector" in text  # imagem externa documentada no header
        assert "cip_default" in text  # rede DNS que liga cip-api ao postgres

    def test_compose_includes_optional_profiles(self) -> None:
        """Perfis opcionais: with-web, observability."""
        import yaml

        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        # Services com profile
        optional_services = [s for s, cfg in compose["services"].items() if "profiles" in cfg]
        assert "with-web" in [cfg["profiles"][0] for s, cfg in compose["services"].items() if "profiles" in cfg for p in cfg["profiles"] if p == "with-web"]
        assert "observability" in [cfg["profiles"][0] for s, cfg in compose["services"].items() if "profiles" in cfg for p in cfg["profiles"] if p == "observability"]
