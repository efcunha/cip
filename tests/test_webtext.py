"""Testes da extração de texto limpo (cip.ingestion.webtext).

Valida:
- clean_html remove a casca de navegação (nav/header/footer/script) e as
  linhas de boilerplate conhecidas das páginas de documentação;
- clean_html prefere o container de conteúdo quando ele existe;
- fetch_document_text devolve None quando a rede falha.

Uso:
    pytest tests/test_webtext.py -v
"""

from __future__ import annotations

import httpx
import pytest

from cip.ingestion.webtext import clean_html, fetch_document_text

_CONTENT = "conteudo real do pilar " * 40  # acima do minimo de 500 chars


def _html(body: str) -> str:
    return (
        "<html><head><title>Doc</title></head><body>"
        "<nav>Menu Docs Pricing</nav>"
        "<header>AWS header</header>"
        + body
        + "<footer>copyright 2026</footer>"
        "<script>var tracking = 1;</script>"
        "</body></html>"
    )


def test_clean_html_remove_navegacao_e_boilerplate():
    html = _html(
        "<div id='main-content'><h1>Well-Architected</h1><p>" + _CONTENT + "</p>"
        "<p>Javascript is disabled or is unavailable in your browser.</p>"
        "<p>Did this page help you?</p></div>"
    )
    text = clean_html(html)
    assert "Well-Architected" in text
    assert "conteudo real do pilar" in text
    assert "Menu Docs Pricing" not in text
    assert "AWS header" not in text
    assert "Javascript is disabled" not in text
    assert "Did this page help you" not in text
    assert "tracking" not in text
    assert "copyright 2026" not in text


def test_clean_html_prefere_container_de_conteudo():
    html = _html(
        "<main><p>" + _CONTENT + "</p></main>"
        "<div class='outro'><p>fora do container</p></div>"
    )
    text = clean_html(html)
    assert "conteudo real do pilar" in text
    assert "fora do container" not in text


def test_clean_html_sem_container_usa_o_corpo():
    html = _html("<p>" + _CONTENT + "</p>")
    text = clean_html(html)
    assert "conteudo real do pilar" in text


def test_fetch_document_text_devolve_none_em_falha_de_rede(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "get", boom)
    assert fetch_document_text("https://exemplo.invalid/pagina") is None


def test_fetch_document_text_usa_o_texto_limpo(monkeypatch):
    class _Response:
        text = _html("<div id='main-content'><p>" + _CONTENT + "</p></div>")

        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Response())
    text = fetch_document_text("https://exemplo.invalid/pagina")
    assert text is not None
    assert "conteudo real do pilar" in text
    assert "Menu Docs Pricing" not in text
