"""Testes para a Web UI do CIP (Round 17).

Valida:
- Estrutura de web/ (index.html, style.css, app.js)
- HTML tem seções obrigatórias (sidebar, main, form, etc.)
- JavaScript tem funções críticas (chamadas API, streaming)
- CSS tem estilos essenciais
- Script serve_web.py existe e tem help

Uso:
    pytest tests/test_web_ui.py -v
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"


# ─────────────────────────────────────────────────────────────────────────
# Estrutura
# ─────────────────────────────────────────────────────────────────────────


class TestWebUIStructure:
    """Estrutura básica de web/."""

    def test_web_dir_exists(self) -> None:
        assert WEB_DIR.exists()
        assert WEB_DIR.is_dir()

    def test_index_html_exists(self) -> None:
        index = WEB_DIR / "index.html"
        assert index.exists()
        assert index.stat().st_size > 1000

    def test_style_css_exists(self) -> None:
        css = WEB_DIR / "style.css"
        assert css.exists()
        assert css.stat().st_size > 1000

    def test_app_js_exists(self) -> None:
        js = WEB_DIR / "app.js"
        assert js.exists()
        assert js.stat().st_size > 1000


# ─────────────────────────────────────────────────────────────────────────
# HTML structure
# ─────────────────────────────────────────────────────────────────────────


class TestHTMLStructure:
    """HTML tem seções obrigatórias."""

    def test_html5_doctype(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")

    def test_has_portuguese_lang(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'lang="pt-BR"' in content

    def test_has_charset_utf8(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'charset="UTF-8"' in content

    def test_has_viewport_meta(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert "viewport" in content

    def test_has_title(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert "<title>CIP" in content

    def test_has_sidebar(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'class="sidebar"' in content

    def test_has_main_chat_area(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'class="main"' in content
        assert 'id="messages"' in content

    def test_has_chat_form(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'id="chatForm"' in content
        assert 'id="questionInput"' in content
        assert 'id="sendBtn"' in content

    def test_has_config_inputs(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'id="apiUrl"' in content
        assert 'id="apiKey"' in content
        assert 'id="tenantId"' in content
        assert 'id="cloudSelect"' in content
        assert 'id="reactMode"' in content
        assert 'id="streamMode"' in content

    def test_has_status_bar(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'id="statusDot"' in content
        assert 'id="statusText"' in content

    def test_has_example_buttons(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'class="example"' in content
        # Pelo menos 4 exemplos
        n_examples = content.count('class="example"')
        assert n_examples >= 4

    def test_loads_style_css(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'href="style.css"' in content

    def test_loads_app_js(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert 'src="app.js"' in content

    def test_has_welcome_message(self) -> None:
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        assert "Bem-vindo" in content
        assert "AWS" in content
        assert "GCP" in content
        assert "Azure" in content


# ─────────────────────────────────────────────────────────────────────────
# JavaScript structure
# ─────────────────────────────────────────────────────────────────────────


class TestJavaScriptStructure:
    """JavaScript tem funções críticas."""

    def test_js_has_api_client_functions(self) -> None:
        content = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        # Funções de chamada API
        assert "async function callHealth" in content
        assert "async function callAsk" in content
        assert "async function callAskStream" in content
        # Round 22+: /analyze/stream foi consolidado no chat multi-turn
        # (POST /chat/conversations/{id}/messages) em vez de um endpoint
        # single-turn separado. Verifica as funções de conversa equivalentes.
        assert "async function sendConversationMessage" in content
        assert "async function createConversation" in content
        assert "async function listConversations" in content

    def test_js_has_streaming_support(self) -> None:
        content = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        # SSE parsing (renomeado parseSSE no Round 22+)
        assert "parseSSE" in content
        assert "event:" in content
        assert "data:" in content
        # Event types
        assert '"chunk"' in content or "'chunk'" in content
        assert '"done"' in content or "'done'" in content

    def test_js_has_ui_functions(self) -> None:
        content = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        # Funções de UI (renomeadas no Round 22+: appendMessage/appendAssistantMessage)
        assert "function setStatus" in content
        assert "function appendMessage" in content
        assert "function appendStreamingAssistant" in content
        assert "async function sendMessage" in content
        assert "function formatAnswer" in content

    def test_js_handles_markdown(self) -> None:
        content = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        # Markdown rendering: bold (** → <strong>) e inline code (` → <code>)
        # implementados em formatAnswer(); fenced code blocks (```) foram
        # removidos em favor de inline <code> no Round 22+.
        assert "**" in content   # bold
        assert "`" in content    # inline code
        assert "<strong>" in content
        assert "<code>" in content

    def test_js_has_event_listeners(self) -> None:
        content = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        # Listeners para form, Enter, Clear, Health
        assert "addEventListener" in content
        assert "keydown" in content  # Enter

    def test_js_initializes_health_check(self) -> None:
        content = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        # Initial health check on load
        assert "callHealth()" in content

    def test_js_no_obvious_syntax_errors(self) -> None:
        """Verifica que o JS não tem erros de sintaxe óbvios."""
        content = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        # Verificações simples
        assert content.count("{") == content.count("}")  # braces balanceadas
        assert content.count("(") == content.count(")")  # parens balanceadas
        assert content.count("[") == content.count("]")  # brackets balanceadas

    def test_js_handles_findings(self) -> None:
        """JS renderiza metadados da resposta (grounding, latência, feedback).

        Round 22+: o conceito de "findings" (severity/impact/recommendation)
        migrou para o Inspection Engine (backend) e para as classes CSS
        (.finding em style.css). O app.js agora renderiza a metadata da
        resposta do assistente via badges (sources/grounding/latency) e a barra
        de feedback. Valida o equivalente funcional no lado cliente.
        """
        content = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        # Metadata renderizada no cliente (grounding + latência)
        assert "has_grounding" in content
        assert "sources_count" in content
        assert "latency_ms" in content
        # Barra de feedback por mensagem do assistente
        assert "feedback" in content.lower()
        # Classes CSS de findings ainda são renderizadas via style.css
        css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
        assert ".finding" in css


# ─────────────────────────────────────────────────────────────────────────
# CSS structure
# ─────────────────────────────────────────────────────────────────────────


class TestCSSStructure:
    """CSS tem estilos essenciais."""

    def test_css_has_dark_theme_variables(self) -> None:
        content = (WEB_DIR / "style.css").read_text(encoding="utf-8")
        # CSS variables para dark theme
        assert "--bg:" in content
        assert "--text:" in content
        assert "--accent:" in content

    def test_css_has_responsive_layout(self) -> None:
        content = (WEB_DIR / "style.css").read_text(encoding="utf-8")
        # Grid layout
        assert "display: grid" in content
        # Grid template columns (sidebar + main)
        assert "grid-template-columns" in content

    def test_css_has_message_styles(self) -> None:
        content = (WEB_DIR / "style.css").read_text(encoding="utf-8")
        # User e assistant message styles
        assert ".message.user" in content
        assert ".message.assistant" in content or ".message {" in content

    def test_css_has_typing_indicator(self) -> None:
        content = (WEB_DIR / "style.css").read_text(encoding="utf-8")
        # Animation para typing indicator
        assert "@keyframes" in content
        assert "typing" in content.lower()

    def test_css_has_scrollbar_styles(self) -> None:
        content = (WEB_DIR / "style.css").read_text(encoding="utf-8")
        assert "::-webkit-scrollbar" in content


# ─────────────────────────────────────────────────────────────────────────
# serve_web.py
# ─────────────────────────────────────────────────────────────────────────


class TestServeWebScript:
    """Script serve_web.py."""

    def test_script_exists(self) -> None:
        script = ROOT / "scripts" / "serve_web.py"
        assert script.exists()
        assert script.stat().st_size > 1000

    def test_script_has_help(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "serve_web.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Web UI" in result.stdout or "web" in result.stdout.lower()

    def test_script_supports_custom_port(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "serve_web.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "--port" in result.stdout
        assert "--api-url" in result.stdout

    def test_script_uses_stdlib_only(self) -> None:
        """Não deve importar deps externas."""
        content = (ROOT / "scripts" / "serve_web.py").read_text(encoding="utf-8")
        # Stdlib only
        assert "import http.server" in content
        assert "import socketserver" in content
        # Não deve ter FastAPI/starlette/uvicorn
        assert "fastapi" not in content.lower()
        assert "uvicorn" not in content.lower()


# ─────────────────────────────────────────────────────────────────────────
# Makefile integration
# ─────────────────────────────────────────────────────────────────────────


class TestMakefileIntegration:
    """Makefile deve ter target para web UI."""

    def test_makefile_has_web_target(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        # Tem target para web (pode ser web, web-ui, webui)
        assert re.search(r"^web[:-]", makefile, re.MULTILINE) is not None

    def test_makefile_web_target_runs_serve_web(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        # Procura pelo target web e verifica se chama serve_web.py
        web_section = re.search(
            r"^web:.*?(?=^\w+:|\Z)", makefile, re.MULTILINE | re.DOTALL
        )
        if web_section:
            assert "serve_web" in web_section.group()