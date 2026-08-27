"""Descoberta em massa de páginas de documentação (ingestão exaustiva).

Expande cada entrada curada do ``sources.yaml`` para o conjunto COMPLETO de
páginas daquele serviço, usando as fontes oficiais de cada provedor:

  * AWS   -> ``<guia>/llms.txt`` (índice para LLMs) → páginas ``.md`` limpas.
  * GCP   -> sitemaps oficiais (``docs.cloud.google.com/sitemap.xml``) filtrados
             pelo prefixo de produto (ex.: ``/compute/docs``).
  * Azure -> índice de sitemap (``learn.microsoft.com/_sitemaps/sitemapindex.xml``)
             filtrado por ``/en-us/azure/<serviço>/``.

O design reaproveita o catálogo curado: a categoria/serviço/metadados já
definidos no ``sources.yaml`` são preservados, e cada entrada é "explodida"
para todas as suas páginas. Assim obtemos cobertura ~100% da documentação dos
serviços priorizados, sem recatalogar nada à mão.

Uso (preview, não persiste):
    python -m cip.ingestion.discovery --cloud aws --scope full --limit 20
    python -m cip.ingestion.discovery --cloud gcp --scope full
    python -m cip.ingestion.discovery --cloud azure --scope full --json out.json

ATENÇÃO: respeite robots.txt e os termos de uso de cada provedor. Os caminhos
de documentação usados aqui são públicos e permitidos para leitura.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Iterable

import yaml

from cip.logging import get_logger

log = get_logger(__name__)

SOURCES_FILE = Path(__file__).parent / "sources.yaml"
CACHE_DIR = Path(__file__).parent / ".discovery_cache"
UA = "Mozilla/5.0 (compatible; CIP-Discovery/1.0; +https://github.com/efcunha/cip)"

GCP_SITEMAP_INDEX = "https://docs.cloud.google.com/sitemap.xml"
AZURE_SITEMAP_INDEX = "https://learn.microsoft.com/_sitemaps/sitemapindex.xml"

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\((https://docs\.aws\.amazon\.com/[^)]+\.md)\)")

# Padrões de RUÍDO: páginas que não agregam a recomendações de arquitetura e só
# inflam o corpus (e o custo de embeddings). O caso mais grave é o GCP, cujos
# sitemaps incluem centenas de milhares de referências de SDK (Java/Node/PHP/…)
# e da CLI gcloud. Também cortamos históricos de versão e release notes.
DEFAULT_EXCLUDE_PATTERNS = [
    r"/reference(/|$)",                                   # API/SDK reference (GCP)
    r"/rpc(/|$)",
    r"/(java|nodejs|python|php|dotnet|go|ruby|cpp)/docs/reference",
    r"/sdk/gcloud/reference",                             # gcloud CLI reference
    r"/APIReference/",                                    # AWS API reference
    r"/CommandLineReference/",
    r"/aws-cli/",
    r"DocumentHistory",                                   # AWS histórico de doc
    r"/release-notes",                                    # release notes / changelogs
    r"/relnotes",
    r"/dotnet/api/",                                      # Azure .NET API ref
    r"/cli/azure/",                                       # Azure CLI ref
    r"/powershell/",                                      # Azure PowerShell ref
    r"/rest/api/",                                        # REST API ref
    r"\?",                                                # querystring: locale (?hl=) e versão (?view=) — canônica é sem query
    r"/samples(/|$)",                                     # amostras de código (baixo valor p/ arquitetura)
    r"/libraries(/|$)",                                   # client libraries
]
_EXCLUDE_RE = re.compile("|".join(DEFAULT_EXCLUDE_PATTERNS), re.IGNORECASE)


def is_noise(url: str) -> bool:
    """True se a URL é ruído (referência de SDK/CLI/API, release notes, etc.)."""
    return bool(_EXCLUDE_RE.search(url))


# ─────────────────────────── HTTP helpers ───────────────────────────
def _fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
    return raw


def _fetch_text(url: str, timeout: int = 60) -> str:
    return _fetch(url, timeout).decode("utf-8", errors="replace")


def _cached(name: str, loader) -> str:
    """Cacheia downloads pesados (sitemaps) em .discovery_cache/."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    data = loader()
    path.write_text(data, encoding="utf-8")
    return data


# ─────────────────────────── sitemap parsing ───────────────────────────
def _locs(xml: str) -> list[str]:
    return _LOC_RE.findall(xml)


def _load_sitemap_urls(
    index_url: str,
    sub_filter=None,
    cache_prefix: str = "",
    keep_url=None,
    workers: int = 16,
) -> list[str]:
    """Baixa um índice de sitemap e todas as sub-sitemaps, retornando as <loc>.

    sub_filter: predicado (sub_url) -> bool para pular sub-sitemaps irrelevantes.
    keep_url: predicado (url) -> bool aplicado durante o parse para descartar
      URLs fora do escopo cedo (evita reter milhões de links em memória).
    Downloads das sub-sitemaps são paralelizados.
    """
    import concurrent.futures as cf

    index_xml = _cached(f"{cache_prefix}index.xml", lambda: _fetch_text(index_url))
    subs = _locs(index_xml)
    if sub_filter:
        subs = [s for s in subs if sub_filter(s)]

    def load_one(item):
        i, sub = item
        safe = re.sub(r"[^a-zA-Z0-9]+", "_", sub)[-80:]
        try:
            xml = _cached(f"{cache_prefix}{i}_{safe}.xml", lambda: _fetch_text(sub))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            log.warning("sitemap_sub_failed", sub=sub, error=str(exc))
            return []
        locs = _locs(xml)
        return [u for u in locs if keep_url(u)] if keep_url else locs

    urls: list[str] = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for chunk in ex.map(load_one, list(enumerate(subs))):
            urls.extend(chunk)
    return urls


# ─────────────────────────── derivação de alvos ───────────────────────────
def _aws_guide_base(url: str) -> str | None:
    """`.../AWSEC2/latest/UserGuide/concepts.html` -> `.../AWSEC2/latest/UserGuide`."""
    m = re.match(r"(https://docs\.aws\.amazon\.com/.+?)/[^/]+\.(?:html|md)$", url)
    if m:
        return m.group(1)
    return url.rstrip("/")


def _gcp_prefix(url: str) -> str | None:
    """`https://docs.cloud.google.com/compute/docs/instances` -> `/compute/docs`."""
    m = re.match(r"https://docs\.cloud\.google\.com(/[^/]+/docs)(?:/|$)", url)
    if m:
        return m.group(1)
    # fallback: primeiro segmento
    m = re.match(r"https://docs\.cloud\.google\.com(/[^/]+)", url)
    return m.group(1) if m else None


def _azure_prefix(url: str) -> str | None:
    """`.../en-us/azure/virtual-machines/overview` -> `/en-us/azure/virtual-machines`.

    O Entra tem estrutura própria (/en-us/entra/<área>/...), então usamos o
    prefixo amplo `/en-us/entra`.
    """
    if "/en-us/entra/" in url:
        return "/en-us/entra"
    m = re.match(r"https://learn\.microsoft\.com(/en-us/azure/[^/]+)", url)
    return m.group(1) if m else None


# ─────────────────────────── expansão por cloud ───────────────────────────
def expand_aws(entries: list[dict[str, Any]], cap: int | None = None) -> dict[str, list[str]]:
    """Para cada guia AWS, lê o llms.txt e devolve todas as páginas .md."""
    out: dict[str, list[str]] = {}
    seen_bases: dict[str, list[str]] = {}
    for e in entries:
        pages: list[str] = []
        bases_done = set()
        for url in e["urls"]:
            base = _aws_guide_base(url)
            if not base or base in bases_done:
                continue
            bases_done.add(base)
            if base in seen_bases:
                pages.extend(seen_bases[base])
                continue
            try:
                txt = _fetch_text(f"{base}/llms.txt", timeout=45)
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                log.warning("aws_llms_failed", base=base, error=str(exc))
                # fallback: mantém as URLs originais (troca .html por .md)
                fallback = [re.sub(r"\.html$", ".md", u) for u in e["urls"]]
                seen_bases[base] = fallback
                pages.extend(fallback)
                continue
            md = [u for u in _MD_LINK_RE.findall(txt) if not is_noise(u)]
            seen_bases[base] = md
            pages.extend(md)
        # dedupe preservando ordem
        uniq = list(dict.fromkeys(pages))
        if cap:
            uniq = uniq[:cap]
        out[e["service"]] = uniq
    return out


def _expand_from_sitemap(
    entries: list[dict[str, Any]],
    all_urls: list[str],
    prefix_fn,
    cap: int | None = None,
) -> dict[str, list[str]]:
    # index por prefixo -> urls (uma passada só)
    by_prefix: dict[str, list[str]] = {}
    prefixes_wanted = {}
    for e in entries:
        for url in e["urls"]:
            p = prefix_fn(url)
            if p:
                prefixes_wanted.setdefault(p, e["service"])
    # ordenar prefixos por tamanho desc para casar o mais específico
    ordered = sorted(prefixes_wanted, key=len, reverse=True)
    for u in all_urls:
        path = re.sub(r"^https?://[^/]+", "", u)
        for p in ordered:
            if path == p or path.startswith(p + "/"):
                by_prefix.setdefault(p, []).append(u)
                break
    out: dict[str, list[str]] = {}
    for p, svc in prefixes_wanted.items():
        urls = list(dict.fromkeys(by_prefix.get(p, [])))
        if cap:
            urls = urls[:cap]
        out.setdefault(svc, [])
        out[svc].extend(urls)
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def _wanted_prefixes(entries: list[dict[str, Any]], prefix_fn) -> set[str]:
    out = set()
    for e in entries:
        for url in e["urls"]:
            p = prefix_fn(url)
            if p:
                out.add(p)
    return out


def _make_keep(prefixes: set[str]):
    def keep(u: str) -> bool:
        if is_noise(u):
            return False
        path = re.sub(r"^https?://[^/]+", "", u)
        return any(path == p or path.startswith(p + "/") for p in prefixes)

    return keep


def expand_gcp(entries: list[dict[str, Any]], cap: int | None = None) -> dict[str, list[str]]:
    prefixes = _wanted_prefixes(entries, _gcp_prefix)
    all_urls = _load_sitemap_urls(
        GCP_SITEMAP_INDEX, cache_prefix="gcp_", keep_url=_make_keep(prefixes)
    )
    return _expand_from_sitemap(entries, all_urls, _gcp_prefix, cap)


def expand_azure(entries: list[dict[str, Any]], cap: int | None = None) -> dict[str, list[str]]:
    prefixes = _wanted_prefixes(entries, _azure_prefix)
    # Toda a doc /en-us/azure/<serviço>/ vive nas sub-sitemaps azure_en-us_N.xml;
    # o Microsoft Entra fica em entra_en-us_N.xml. Ignoramos os demais produtos
    # e todos os outros idiomas.
    keep_products = {"azure", "entra"}

    def keep_sub(sub: str) -> bool:
        name = sub.rsplit("/", 1)[-1]
        if "_en-us_" not in name:
            return False
        product = name.split("_en-us_")[0]
        return product in keep_products

    all_urls = _load_sitemap_urls(
        AZURE_SITEMAP_INDEX, sub_filter=keep_sub, cache_prefix="azure_",
        keep_url=_make_keep(prefixes),
    )
    return _expand_from_sitemap(entries, all_urls, _azure_prefix, cap)


EXPANDERS = {"aws": expand_aws, "gcp": expand_gcp, "azure": expand_azure}


# ─────────────────────────── API pública ───────────────────────────
def load_scope(scope: str) -> dict[str, list[dict[str, Any]]]:
    data = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8"))
    result = {c: list(v) for c, v in data.get(scope, {}).items()}
    if scope == "full":
        for cloud, entries in data.get("mvp", {}).items():
            result.setdefault(cloud, [])
            result[cloud] = entries + result[cloud]
    return result


def expand_cloud(cloud: str, scope: str, cap: int | None = None) -> dict[str, list[str]]:
    """Retorna {service: [urls expandidas]} para um provedor."""
    entries = load_scope(scope).get(cloud, [])
    if not entries:
        return {}
    return EXPANDERS[cloud](entries, cap)


def build_expanded_entries(cloud: str, scope: str, cap: int | None = None) -> list[dict[str, Any]]:
    """Devolve entradas no formato do sources.yaml, mas com URLs expandidas."""
    entries = load_scope(scope).get(cloud, [])
    expanded = EXPANDERS[cloud](entries, cap)
    out = []
    for e in entries:
        urls = expanded.get(e["service"])
        if not urls:
            continue
        ne = dict(e)
        ne["urls"] = urls
        ne["expanded"] = True
        out.append(ne)
    return out


# ─────────────────────────── CLI ───────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Descoberta em massa de docs (ingestão exaustiva)")
    ap.add_argument("--cloud", choices=["aws", "gcp", "azure"], required=True)
    ap.add_argument("--scope", choices=["mvp", "full"], default="full")
    ap.add_argument("--limit", type=int, default=None, help="Cap de páginas por serviço")
    ap.add_argument("--json", dest="json_out", default=None, help="Grava o resultado em JSON")
    args = ap.parse_args()

    result = expand_cloud(args.cloud, args.scope, args.limit)
    total = sum(len(v) for v in result.values())
    print(f"=== {args.cloud.upper()} / scope={args.scope} ===")
    print(f"Serviços expandidos: {len(result)}  |  Total de páginas: {total}\n")
    for svc in sorted(result, key=lambda s: -len(result[s])):
        print(f"  {svc:<28} {len(result[svc]):>5} páginas")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nJSON gravado em {args.json_out}")


if __name__ == "__main__":
    main()
