"""Auditoria de sources.yaml: cobertura por cloud/categoria + validação HTTP dos links.

Uso:
    python scripts/audit_sources.py            # cobertura + validação HTTP
    python scripts/audit_sources.py --no-http  # apenas cobertura
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from pathlib import Path

import yaml

SOURCES = Path(__file__).resolve().parent.parent / "src/cip/ingestion/sources.yaml"

UA = "Mozilla/5.0 (compatible; CIP-LinkAudit/1.0)"


def load():
    return yaml.safe_load(SOURCES.read_text(encoding="utf-8"))


def collect_entries(data):
    """Retorna lista de (scope, cloud, service, category, url)."""
    rows = []
    for scope in ("mvp", "full"):
        for cloud, entries in data.get(scope, {}).items():
            for e in entries:
                for url in e["urls"]:
                    rows.append((scope, cloud, e.get("service"), e.get("category"), url))
    return rows


def coverage(data):
    print("=" * 70)
    print("COBERTURA POR CLOUD / CATEGORIA")
    print("=" * 70)
    for cloud in ("aws", "gcp", "azure"):
        services = defaultdict(set)  # category -> {service}
        urls = 0
        for scope in ("mvp", "full"):
            for e in data.get(scope, {}).get(cloud, []):
                services[e.get("category")].add(e.get("service"))
                urls += len(e["urls"])
        total_services = sum(len(s) for s in services.values())
        print(f"\n### {cloud.upper()}  ->  {total_services} serviços, {urls} URLs")
        for cat in sorted(services):
            svc = sorted(services[cat])
            print(f"  - {cat:<15} ({len(svc)}): {', '.join(svc)}")


def check_url(url: str):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return url, r.status, r.geturl()
    except urllib.error.HTTPError as ex:
        # Alguns servidores rejeitam HEAD; tentar GET
        if ex.code in (403, 405, 400):
            try:
                req2 = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
                with urllib.request.urlopen(req2, timeout=25) as r:
                    return url, r.status, r.geturl()
            except urllib.error.HTTPError as ex2:
                return url, ex2.code, None
            except Exception as ex2:  # noqa
                return url, f"ERR:{type(ex2).__name__}", None
        return url, ex.code, None
    except Exception as ex:  # noqa
        return url, f"ERR:{type(ex).__name__}", None


def validate(rows):
    print("\n" + "=" * 70)
    print("VALIDAÇÃO HTTP DOS LINKS")
    print("=" * 70)
    urls = sorted({r[4] for r in rows})
    print(f"Total de URLs únicas: {len(urls)}\n")
    results = {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for url, status, final in ex.map(check_url, urls):
            results[url] = (status, final)

    ok, redirect, broken = [], [], []
    for url in urls:
        status, final = results[url]
        if isinstance(status, int) and 200 <= status < 300:
            if final and final.rstrip("/") != url.rstrip("/"):
                redirect.append((url, final))
            else:
                ok.append(url)
        else:
            broken.append((url, status))

    print(f"OK (2xx, sem redirect relevante): {len(ok)}")
    print(f"Redirecionados (2xx, URL final difere): {len(redirect)}")
    print(f"Problemas (4xx/5xx/erro): {len(broken)}\n")

    if redirect:
        print("--- REDIRECIONAMENTOS ---")
        for url, final in redirect:
            print(f"  [->] {url}\n       => {final}")
        print()
    if broken:
        print("--- PROBLEMAS ---")
        # mapear url -> cloud/service
        meta = {r[4]: (r[1], r[2]) for r in rows}
        for url, status in broken:
            cloud, svc = meta.get(url, ("?", "?"))
            print(f"  [{status}] ({cloud}/{svc}) {url}")
    else:
        print("Nenhum link quebrado detectado.")

    return len(broken)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-http", action="store_true")
    args = ap.parse_args()
    data = load()
    coverage(data)
    if not args.no_http:
        broken = validate(collect_entries(data))
        # Código de saída não-zero permite uso como gate em CI.
        sys.exit(1 if broken else 0)


if __name__ == "__main__":
    main()
