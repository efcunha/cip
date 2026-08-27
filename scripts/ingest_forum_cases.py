#!/usr/bin/env python3
"""Orquestra a atualização de case studies vindos de fóruns.

Fluxo:
  1. ``forum_fetcher.collect_forum_urls()`` busca em HackerNews/dev.to/Reddit
  2. ``forum_fetcher.append_to_sources_yaml()`` adiciona em sources_advanced.yaml
     (apenas URLs novas — dedup automático)
  3. ``cip.ingestion.ingest`` roda com --cloud=case-studies, --dry-run ou persistido

Uso:
    # Só buscar (não persiste)
    python scripts/ingest_forum_cases.py --fetch-only

    # Buscar + persistir YAML (mas NÃO ingere no DB ainda)
    python scripts/ingest_forum_cases.py --no-ingest

    # Buscar + persistir YAML + rodar ingestão no DB
    python scripts/ingest_forum_cases.py

    # Limpar URLs de fóruns antigas (>30 dias) antes de re-buscar
    python scripts/ingest_forum_cases.py --prune-old

Exit codes:
    0 = sucesso (mesmo com 0 URLs novas — só atualizou log)
    1 = erro de fetch / YAML
    2 = erro de ingestão (DB down, schema desatualizado)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cip.ingestion.forum_fetcher import (  # noqa: E402
    collect_forum_urls,
    append_to_sources_yaml,
)
from cip.logging import configure_logging, get_logger  # noqa: E402

configure_logging()
log = get_logger(__name__)


def step_fetch(args: argparse.Namespace) -> int:
    """Busca URLs em fóruns públicos."""
    sources = args.source if args.source else None
    log.info(
        "step_fetch",
        sources=sources or ["hackernews", "devto", "reddit"],
        min_score=args.min_score,
    )
    hits = collect_forum_urls(
        sources=sources,
        min_score=args.min_score,
        max_per_source=args.max_per_source,
    )
    if not hits:
        print("[INFO] Nenhuma URL relevante encontrada nos fóruns.")
        return 0

    print(f"[OK] Encontradas {len(hits)} URL(s) relevante(s).")
    for h in hits[: args.show_top]:
        print(f"  [{h.score:>3}] {h.source:<14}  {h.title[:60]:<60}  {h.url}")
    if len(hits) > args.show_top:
        print(f"  ... e mais {len(hits) - args.show_top}")

    if args.fetch_only:
        return 0

    added = append_to_sources_yaml(hits)
    print(f"\n[OK] {added} URL(s) nova(s) adicionada(s) a sources_advanced.yaml")
    return 0


def step_ingest() -> int:
    """Roda a ingestão focada em 'case-studies'."""
    log.info("step_ingest")
    cmd = [
        sys.executable,
        "-m",
        "cip.ingestion.ingest",
        "--scope",
        "full",
        "--cloud",
        "case-studies",
    ]
    print(f"\n[INGEST] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT), timeout=1800)
    if proc.returncode != 0:
        print(f"[FAIL] Ingestão retornou exit code {proc.returncode}")
        return 2
    return 0


def step_prune_old(max_age_days: int = 30) -> int:
    """Remove entries 'forum-*' do YAML com mais de N dias.

    Heurística: como o YAML não guarda timestamp, removemos as entries
    inteiras. Para preservar entries manuais, só tocamos source que começa
    com 'forum-'.
    """
    import yaml

    yaml_path = ROOT / "src" / "cip" / "ingestion" / "sources_advanced.yaml"
    if not yaml_path.exists():
        return 0
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    case_studies = data.get("case-studies", []) or []
    kept = []
    removed = 0
    for entry in case_studies:
        src = entry.get("source", "")
        if src.startswith("forum-"):
            removed += 1
        else:
            kept.append(entry)
    if removed > 0:
        data["case-studies"] = kept
        yaml_path.write_text(
            yaml.safe_dump(data, sort_keys=True, allow_unicode=True, width=1000),
            encoding="utf-8",
        )
    print(f"[PRUNE] {removed} entry(ies) de forum-* removida(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Busca + ingest de case studies de fóruns"
    )
    parser.add_argument(
        "--source", action="append",
        choices=["hackernews", "devto", "reddit"],
        help="Filtrar fonte (pode repetir). Default: todas.",
    )
    parser.add_argument(
        "--min-score", type=int, default=5,
        help="Score mínimo para HN/dev.to (default: 5)",
    )
    parser.add_argument(
        "--max-per-source", type=int, default=20,
        help="Máx URLs por fonte (default: 20)",
    )
    parser.add_argument(
        "--fetch-only", action="store_true",
        help="Apenas buscar, não persiste YAML nem ingere",
    )
    parser.add_argument(
        "--no-ingest", action="store_true",
        help="Não rodar ingestão após persistir YAML",
    )
    parser.add_argument(
        "--prune-old", action="store_true",
        help="Remove entries forum-* do YAML antes de buscar (limpa state)",
    )
    parser.add_argument(
        "--show-top", type=int, default=10,
        help="Quantos hits exibir no console (default: 10)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  CIP — INGEST DE CASE STUDIES (FÓRUNS PÚBLICOS)")
    print("=" * 70)

    if args.prune_old:
        step_prune_old()

    rc = step_fetch(args)
    if rc != 0:
        return rc

    if args.fetch_only or args.no_ingest:
        return 0

    return step_ingest()


if __name__ == "__main__":
    sys.exit(main())
