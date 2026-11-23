"""Extração de texto limpo de páginas de documentação.

Fonte única do texto usado pela ingestão E pela detecção de drift.

Por que este módulo existe
--------------------------
O leitor web genérico (SimpleWebPageReader com html_to_text=True) mantém a
casca da página: menus, rodapés, avisos de cookie e o bloco "Javascript is
disabled or is unavailable in your browser" das páginas AWS. O corpus
ingerido ficava com esse boilerplate em vez do conteúdo do pilar.

Pior: o doc_hash (base do delta e da detecção de drift) era calculado sobre
esse mesmo texto cru, então o drift comparava casca de navegação em vez de
conteúdo -- e a alteração de um menu disparava uma re-ingestão.

Como a ingestão e o drift precisam calcular o MESMO hash, as duas pontas
usam a MESMA função daqui: o hash gravado no banco e o hash calculado no
drift são comparáveis por construção.

Dependências: httpx e beautifulsoup4 (já são dependências do projeto).
"""

from __future__ import annotations

from typing import Any

from cip.logging import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_USER_AGENT = "CloudPilot-CIP-KB/1.0 (+https://cloudpilot.app.br)"

# Tags que carregam só casca de navegação (removidas antes da extração).
_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "form",
    "nav",
    "aside",
    "footer",
    "header",
)

# Roles ARIA que marcam não-conteúdo.
_STRIP_ROLES = {"navigation", "banner", "contentinfo", "search", "complementary"}

# Seletores do container de conteúdo, em ordem de preferência.
_CONTENT_SELECTORS = (
    "#main-content",
    "main",
    "article",
    "[role='main']",
    ".awsui-content",
    "#docs-body",
    ".markdown-body",
    "#content",
)

# Linhas de boilerplate conhecidas das páginas de documentação.
# Prefixo: a linha começa com o marcador (o texto real costuma ser maior).
_BOILERPLATE_PREFIXES = (
    "javascript is disabled",
    "did this page help you",
    "skip to main content",
)

# Exact: a linha inteira é o marcador.
_BOILERPLATE_EXACT = {
    "document conventions",
    "©",
    "all rights reserved",
}


def _is_boilerplate_line(line: str) -> bool:
    """True quando a linha é casca conhecida de documentação."""
    low = line.strip().lower()
    if not low:
        return True
    if low.startswith(_BOILERPLATE_PREFIXES):
        return True
    return low in _BOILERPLATE_EXACT


def _text_of(node: Any) -> str:
    """Texto do nó, uma linha por bloco, sem linhas vazias ou de boilerplate."""
    raw = node.get_text("\n")
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if _is_boilerplate_line(stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


def clean_html(html: str, *, min_content_chars: int = 500) -> str:
    """Extrai o texto de conteúdo de um HTML, sem a casca de navegação.

    Prefere o container de conteúdo (#main-content, main, article...) quando
    ele existe e tem tamanho suficiente; caso contrário usa o corpo da
    página. Devolve string vazia quando não sobra conteúdo aproveitável.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(list(_STRIP_TAGS)):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": True}):
        if str(tag.get("role", "")).strip().lower() in _STRIP_ROLES:
            tag.decompose()

    root: Any = None
    for selector in _CONTENT_SELECTORS:
        found = soup.select_one(selector)
        if found is None:
            continue
        text = _text_of(found)
        if len(text) >= min_content_chars:
            root = found
            break

    if root is None:
        root = soup.body or soup
    return _text_of(root)


def fetch_document_text(
    url: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    user_agent: str = DEFAULT_USER_AGENT,
) -> str | None:
    """Baixa a página e devolve o texto limpo.

    Devolve None quando a rede ou o parse falham -- quem chama decide o que
    fazer com uma página indisponível (a ingestão descarta o documento; o
    drift ignora a URL e mantém o baseline).
    """
    import httpx

    try:
        response = httpx.get(
            url,
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - rede/redirect podem falhar de várias formas
        log.warning("webtext_fetch_failed", url=url, error=str(exc))
        return None

    try:
        return clean_html(response.text)
    except Exception as exc:  # noqa: BLE001 - parse de HTML arbitrário
        log.warning("webtext_parse_failed", url=url, error=str(exc))
        return None
