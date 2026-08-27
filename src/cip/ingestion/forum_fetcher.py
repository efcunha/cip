"""Fetcher de URLs de postmortems / case studies em fontes públicas.

Substitui/atualiza a parte estática de ``case-studies`` em
``sources_advanced.yaml``: ao invés de só referenciar blogs manualmente
curados, este módulo **busca ativamente** novos links em fontes com APIs
abertas (sem precisar de auth):

  * HackerNews Algolia Search API   — busca full-text em posts
  * dev.to API                     — artigos taggeados como postmortem
  * Reddit RSS público             — r/aws, r/azure, r/googlecloud, r/devops
  * GitHub blog RSS                — engineering blog oficial

Cada fonte retorna ``ForumHit`` (url, title, source, published_at, score).
``collect_forum_urls()`` agrega, deduplica por URL e filtra por qualidade
mínima (score > 0). Saída é uma lista de URLs que ``ingest_forum_cases.py``
adiciona à KB.

Filtros de relevância — termos que precisam aparecer no título OU url:
  * postmortem, post-mortem, incident, outage, lessons learned, case study,
    retrospective, after-action, RCA, root cause

E pelo menos uma das clouds OU arquiteturas: aws, gcp, azure, eks, aks,
gke, lambda, kubernetes, terraform, microservices, saga, cqrs, kafka…

Compliance:
  - Apenas APIs públicas (sem auth)
  - Respeita rate limits (max ~30 req/min por fonte)
  - Respeita robots.txt (RSS feeds públicos são sempre permitidos)
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import quote_plus

import httpx

from cip.logging import get_logger

log = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────

USER_AGENT = "CIP-CloudIntelligencePlatform/0.3 (forum-fetcher; +https://github.com/cip)"
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MIN_SCORE = 5  # HN points; dev.to reactions; Reddit upvotes
DEFAULT_MAX_PER_SOURCE = 20

# Termos de relevância (case studies / postmortems)
RELEVANCE_TERMS = [
    "postmortem", "post-mortem", "incident", "outage", "lessons learned",
    "case study", "case-study", "retrospective", "after-action",
    "rca", "root cause", "downtime", "postmortems", "post mortem",
]

# Termos de cloud/arquitetura (devem aparecer junto)
CLOUD_TERMS = [
    "aws", "azure", "gcp", "google cloud", "eks", "aks", "gke",
    "kubernetes", "lambda", "terraform", "cloudformation",
    "microservices", "microsserviços", "saga", "cqrs", "kafka",
    "event-driven", "circuit breaker", "observability", "sre",
]

# Fontes
SOURCES = {
    "hackernews": "https://hn.algolia.com/api/v1/search",
    "devto": "https://dev.to/api/articles",
    # Reddit RSS públicos (sem auth)
    "reddit-aws": "https://www.reddit.com/r/aws/top/.rss?t=week",
    "reddit-azure": "https://www.reddit.com/r/azure/top/.rss?t=week",
    "reddit-googlecloud": "https://www.reddit.com/r/googlecloud/top/.rss?t=week",
    "reddit-devops": "https://www.reddit.com/r/devops/top/.rss?t=week",
}


# ─────────────────────────────────────────────────────────────────────────
# Dataclass
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class ForumHit:
    """Um hit relevante retornado por uma fonte."""

    url: str
    title: str
    source: str  # 'hackernews' | 'devto' | 'reddit-aws' | ...
    score: int = 0
    published_at: str | None = None
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────
# Filtros
# ─────────────────────────────────────────────────────────────────────────


def _is_relevant(text: str, url: str) -> tuple[bool, list[str]]:
    """Decide se (text, url) é case-study/postmortem de cloud/arquitetura."""
    blob = (text + " " + url).lower()
    rel = [t for t in RELEVANCE_TERMS if t in blob]
    cloud = [t for t in CLOUD_TERMS if t in blob]
    return bool(rel and cloud), rel + cloud


# ─────────────────────────────────────────────────────────────────────────
# Fetcher — HackerNews (Algolia)
# ─────────────────────────────────────────────────────────────────────────


def fetch_hackernews(
    client: httpx.Client,
    max_results: int = DEFAULT_MAX_PER_SOURCE,
) -> list[ForumHit]:
    """Busca postmortems/incidents no HackerNews via Algolia."""
    hits: list[ForumHit] = []
    # Combina queries — Algolia aceita OR via `query` mas filtra client-side
    queries = ["postmortem cloud", "aws outage", "kubernetes incident", "lessons learned aws"]
    for q in queries:
        try:
            resp = client.get(
                SOURCES["hackernews"],
                params={"query": q, "tags": "story", "hitsPerPage": 30},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("hn_fetch_failed", q=q, error=str(exc))
            continue

        for h in data.get("hits", []):
            url = h.get("url") or h.get("story_text") or ""
            title = h.get("title") or ""
            ok, matched = _is_relevant(f"{title} {h.get('story_text', '')}", url)
            if not ok:
                continue
            hits.append(
                ForumHit(
                    url=url,
                    title=title,
                    source="hackernews",
                    score=int(h.get("points") or 0),
                    published_at=h.get("created_at"),
                    matched_terms=matched,
                )
            )
        time.sleep(0.5)  # rate limit gentil

    # Dedup por URL + rank por score
    seen: dict[str, ForumHit] = {}
    for h in hits:
        if h.url and h.url not in seen:
            seen[h.url] = h
    return sorted(seen.values(), key=lambda x: -x.score)[:max_results]


# ─────────────────────────────────────────────────────────────────────────
# Fetcher — dev.to
# ─────────────────────────────────────────────────────────────────────────


def fetch_devto(
    client: httpx.Client,
    max_results: int = DEFAULT_MAX_PER_SOURCE,
) -> list[ForumHit]:
    """Busca artigos taggeados como postmortem/incident/outage no dev.to."""
    hits: list[ForumHit] = []
    tags = ["postmortem", "incident", "aws", "kubernetes", "sre"]
    for tag in tags:
        try:
            resp = client.get(
                SOURCES["devto"],
                params={"tag": tag, "top": 7},  # top 7 days
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("devto_fetch_failed", tag=tag, error=str(exc))
            continue

        for article in data:
            url = article.get("url") or article.get("canonical_url") or ""
            title = article.get("title", "")
            desc = article.get("description", "")
            ok, matched = _is_relevant(f"{title} {desc}", url)
            if not ok:
                continue
            hits.append(
                ForumHit(
                    url=url,
                    title=title,
                    source="devto",
                    score=int(article.get("public_reactions_count") or 0),
                    published_at=article.get("published_at"),
                    matched_terms=matched,
                )
            )
        time.sleep(0.5)

    seen: dict[str, ForumHit] = {}
    for h in hits:
        if h.url and h.url not in seen:
            seen[h.url] = h
    return sorted(seen.values(), key=lambda x: -x.score)[:max_results]


# ─────────────────────────────────────────────────────────────────────────
# Fetcher — Reddit RSS
# ─────────────────────────────────────────────────────────────────────────

_REDDIT_NS = {"atom": "http://www.w3.org/2005/Atom"}


def fetch_reddit_rss(
    client: httpx.Client,
    subreddit: str,
    max_results: int = DEFAULT_MAX_PER_SOURCE,
) -> list[ForumHit]:
    """Coleta top posts da semana de um subreddit (RSS público)."""
    key = f"reddit-{subreddit}"
    if key not in SOURCES:
        raise ValueError(f"Subreddit não configurado: {subreddit}")
    try:
        resp = client.get(SOURCES[key])
        resp.raise_for_status()
        xml = resp.text
    except Exception as exc:  # noqa: BLE001
        log.warning("reddit_fetch_failed", subreddit=subreddit, error=str(exc))
        return []

    hits: list[ForumHit] = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        log.warning("reddit_xml_parse_failed", subreddit=subreddit, error=str(exc))
        return []

    for entry in root.findall("atom:entry", _REDDIT_NS):
        title_el = entry.find("atom:title", _REDDIT_NS)
        link_el = entry.find("atom:link", _REDDIT_NS)
        updated_el = entry.find("atom:updated", _REDDIT_NS)
        title = title_el.text if title_el is not None else ""
        url = link_el.attrib.get("href", "") if link_el is not None else ""
        ok, matched = _is_relevant(title, url)
        if not ok:
            continue
        hits.append(
            ForumHit(
                url=url,
                title=title,
                source=key,
                score=0,  # RSS não traz upvotes direto
                published_at=updated_el.text if updated_el is not None else None,
                matched_terms=matched,
            )
        )

    return hits[:max_results]


def fetch_all_reddit(
    client: httpx.Client,
    max_per_sub: int = 15,
) -> list[ForumHit]:
    """Busca em todos os subreddits configurados."""
    out: list[ForumHit] = []
    for sub in ("aws", "azure", "googlecloud", "devops"):
        out.extend(fetch_reddit_rss(client, sub, max_results=max_per_sub))
    # Dedup
    seen: dict[str, ForumHit] = {}
    for h in out:
        if h.url and h.url not in seen:
            seen[h.url] = h
    return sorted(seen.values(), key=lambda x: -(x.score))[: 4 * max_per_sub]


# ─────────────────────────────────────────────────────────────────────────
# Aggregator
# ─────────────────────────────────────────────────────────────────────────


def collect_forum_urls(
    sources: Iterable[str] | None = None,
    min_score: int = DEFAULT_MIN_SCORE,
    max_per_source: int = DEFAULT_MAX_PER_SOURCE,
) -> list[ForumHit]:
    """Busca URLs de case studies / postmortems em todas (ou algumas) fontes.

    Args:
        sources: subset de ``{"hackernews", "devto", "reddit"}``; None = todos.
        min_score: filtro mínimo (HN points, dev.to reactions).
        max_per_source: limite de URLs por fonte.

    Returns:
        Lista deduplicada de ``ForumHit`` ordenada por score desc.
    """
    enabled = set(sources) if sources else {"hackernews", "devto", "reddit"}
    headers = {"User-Agent": USER_AGENT}
    out: list[ForumHit] = []
    with httpx.Client(timeout=DEFAULT_TIMEOUT_S, headers=headers) as client:
        if "hackernews" in enabled:
            out.extend(
                h for h in fetch_hackernews(client, max_results=max_per_source)
                if h.score >= min_score
            )
        if "devto" in enabled:
            out.extend(
                h for h in fetch_devto(client, max_results=max_per_source)
                if h.score >= min_score
            )
        if "reddit" in enabled:
            # Reddit RSS não tem score confiável; usa todos os hits
            out.extend(fetch_all_reddit(client, max_per_sub=max_per_source // 2))

    # Dedup final por URL
    seen: dict[str, ForumHit] = {}
    for h in out:
        if h.url and h.url not in seen:
            seen[h.url] = h
    return sorted(seen.values(), key=lambda x: -x.score)


# ─────────────────────────────────────────────────────────────────────────
# Persistência — atualiza sources_advanced.yaml
# ─────────────────────────────────────────────────────────────────────────


def append_to_sources_yaml(hits: list[ForumHit], yaml_path: Path | None = None) -> int:
    """Adiciona hits novos (deduplicados por URL) ao sources_advanced.yaml.

    Agrupa por ``source`` em entries de ``case-studies`` para preservar
    a estrutura que o ``load_sources()`` já sabe ler.

    Returns: número de URLs efetivamente adicionadas.
    """
    if yaml_path is None:
        yaml_path = (
            Path(__file__).parent / "sources_advanced.yaml"
        )

    if not hits:
        return 0

    # Carrega YAML existente
    import yaml

    if yaml_path.exists():
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    else:
        data = {}

    # URLs já presentes
    existing: set[str] = set()
    for entry in data.get("case-studies", []) or []:
        existing.update(entry.get("urls", []) or [])

    # Agrupa hits por source
    grouped: dict[str, list[ForumHit]] = {}
    for h in hits:
        if h.url in existing:
            continue
        grouped.setdefault(h.source, []).append(h)

    if not grouped:
        return 0

    # Adiciona novas entries
    if "case-studies" not in data or not isinstance(data["case-studies"], list):
        data["case-studies"] = []

    added = 0
    for source_name, group in grouped.items():
        # Dedup dentro do grupo também
        urls = list(dict.fromkeys(h.url for h in group if h.url))
        if not urls:
            continue
        # Caption = "postmortem" para HN/dev.to/reddit (fallback)
        data["case-studies"].append({
            "source": f"forum-{source_name}",
            "service": "postmortems",
            "category": "case-studies",
            "doc_type": "postmortem",
            "urls": urls,
        })
        added += len(urls)

    # Persiste (ordenado por chave p/ diffs estáveis)
    yaml_path.write_text(
        yaml.safe_dump(data, sort_keys=True, allow_unicode=True, width=1000),
        encoding="utf-8",
    )
    log.info("forum_urls_appended", added=added, path=str(yaml_path))
    return added


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    """Standalone CLI: ``python -m cip.ingestion.forum_fetcher [--write-yaml]``."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Busca URLs de postmortems em fóruns públicos"
    )
    parser.add_argument(
        "--source", action="append",
        choices=["hackernews", "devto", "reddit"],
        help="Filtrar fonte (pode repetir). Default: todas.",
    )
    parser.add_argument(
        "--min-score", type=int, default=DEFAULT_MIN_SCORE,
        help=f"Score mínimo (default: {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument(
        "--max-per-source", type=int, default=DEFAULT_MAX_PER_SOURCE,
        help=f"Máx URLs por fonte (default: {DEFAULT_MAX_PER_SOURCE})",
    )
    parser.add_argument(
        "--write-yaml", action="store_true",
        help="Persistir hits em sources_advanced.yaml (>0 novos)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emitir JSON no stdout",
    )
    args = parser.parse_args()

    log.info(
        "forum_fetch_start",
        sources=args.source or ["hackernews", "devto", "reddit"],
        min_score=args.min_score,
    )
    hits = collect_forum_urls(
        sources=args.source,
        min_score=args.min_score,
        max_per_source=args.max_per_source,
    )

    if args.json:
        print(json.dumps([h.to_dict() for h in hits], indent=2, ensure_ascii=False))
    else:
        print(f"Found {len(hits)} forum URLs:")
        for h in hits[:10]:
            print(f"  [{h.score:>3}] {h.source:<14}  {h.title[:60]:<60}  {h.url}")
        if len(hits) > 10:
            print(f"  ... e mais {len(hits) - 10}")

    if args.write_yaml:
        added = append_to_sources_yaml(hits)
        print(f"\n[OK] {added} URL(s) adicionada(s) a sources_advanced.yaml")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
