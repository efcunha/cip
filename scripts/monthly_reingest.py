#!/usr/bin/env python3
"""Cron mensal de re-ingestão com drift detection.

Detecta mudanças em URLs monitoradas e re-ingerem apenas o que mudou.
Útil para manter o KB atualizado após mudanças em documentação oficial.

Uso:
    # Detectar drift (sem re-ingerir):
    python scripts/monthly_reingest.py --detect-only

    # Detectar + re-ingerir mudanças:
    python scripts/monthly_reingest.py

    # Cron (roda uma vez por mês via crontab / Task Scheduler):
    0 3 1 * *  cd /path/to/cip && python scripts/monthly_reingest.py --report-json /var/log/cip/drift.json

Saída:
    - Lista de URLs modificadas/removidas/novas
    - Estatísticas de drift (taxa de mudança, serviços afetados)
    - Exit code: 0=sem mudanças, 1=mudanças detectadas, 2=erro

Changelog exit codes para automação:
    0 = no drift detected (nothing to do)
    1 = drift detected (changes found, ingestion triggered)
    2 = error during execution
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

# Adicionar src ao path para importar cip.* 
SRC_PATH = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_PATH))

from cip.config import get_settings  # noqa: E402
from cip.logging import configure_logging, get_logger  # noqa: E402

log = get_logger(__name__)

SOURCES_FILE = SRC_PATH / "cip" / "ingestion" / "sources.yaml"
SOURCES_ADVANCED_FILE = SRC_PATH / "cip" / "ingestion" / "sources_advanced.yaml"
REPORT_FILE = Path(__file__).resolve().parent.parent / "ingest_drift_report.json"


@dataclass
class DriftEntry:
    """Mudança detectada em uma URL."""

    cloud: str
    service: str
    url: str
    status: str  # 'new' | 'modified' | 'removed'
    old_hash: str | None = None
    new_hash: str | None = None


@dataclass
class DriftReport:
    """Relatório consolidado de drift."""

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scope: str = "full"
    drift_detected: bool = False
    changes: list[DriftEntry] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


def load_sources(scope: str) -> list[dict[str, Any]]:
    """Carrega as entradas do escopo, com a MESMA visao do ingestor.

    Reusa 'cip.ingestion.ingest.load_sources' (que ja mergeia
    sources_advanced.yaml e as knowledge areas): o drift precisa monitorar
    exatamente as URLs que a ingestao processa. Com a lista local, que so
    lia sources.yaml, o drift via 20 das 174 URLs do escopo mvp -- e a
    mudanca nas outras 154 passava despercebida.
    """
    from cip.ingestion.ingest import load_sources as ingest_load_sources

    out: list[dict[str, Any]] = []
    for entries in ingest_load_sources(scope).values():
        out.extend(entries)
    return out


def known_catalog_urls() -> set[str]:
    """URLs conhecidas em qualquer escopo do catálogo (mvp, full e fontes avançadas).

    Usado para decidir se uma URL do banco foi REMOVIDA do catálogo. Sem isso,
    uma URL do escopo 'full' seria reportada como removida quando o drift roda
    no escopo 'mvp' -- e as fontes avançadas (sources_advanced.yaml) seriam
    reportadas como removidas sempre.
    """
    urls: set[str] = set()
    for path in (SOURCES_FILE, SOURCES_ADVANCED_FILE):
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        for scope_entries in data.values():
            entries_list: list[Any] = []
            if isinstance(scope_entries, dict):
                # escopo -> cloud -> [entradas]
                for entries in scope_entries.values():
                    entries_list.extend(entries or [])
            elif isinstance(scope_entries, list):
                # knowledge area (architecture, case-studies): [entradas]
                entries_list.extend(scope_entries)
            for entry in entries_list:
                if isinstance(entry, dict):
                    urls.update(entry.get("urls", []) or [])
    return urls


def fetch_url_hash(url: str, timeout: int = 30) -> str | None:
    """Baixa URL, extrai texto (mesmo pipeline do ingest) e retorna SHA256.

    Usa a MESMA função do ingest (cip.ingestion.webtext.fetch_document_text)
    para garantir que o hash seja comparável ao 'doc_hash' salvo no banco
    durante a ingestão (caso contrário, divergem por causa de tags/scripts/CSS
    que mudam sem alterar o conteúdo textual).
    """
    from cip.ingestion.webtext import fetch_document_text

    text = (fetch_document_text(url, timeout_s=timeout) or "").strip()
    if len(text) < 100:  # mesma heurística do ingest
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_baseline_hashes() -> dict[str, str]:
    """Recupera hashes já persistidos no banco (url -> doc_hash majoritário).

    Estratégia: para cada URL, escolhe o hash que aparece em mais chunks (moda).
    Isso evita falsos positivos quando uma página tem chunks duplicados com
    hashes próprios (ex: navegação, headers repetidos) que diferem do doc_hash
    principal.
    """
    s = get_settings()
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _query() -> dict[str, str]:
        engine = create_async_engine(
            s.database_url.replace("postgresql://", "postgresql+asyncpg://"),
            pool_pre_ping=True,
        )
        out: dict[str, str] = {}
        try:
            async with engine.connect() as conn:
                stmt = text(
                    "SELECT url, dh, n FROM ( "
                    "  SELECT metadata_ ->> 'url' AS url, "
                    "         metadata_ ->> 'doc_hash' AS dh, "
                    "         COUNT(*) AS n, "
                    "         ROW_NUMBER() OVER (PARTITION BY metadata_ ->> 'url' "
                    "                            ORDER BY COUNT(*) DESC) AS rn "
                    "  FROM data_cloud_docs "
                    "  WHERE metadata_ ->> 'doc_hash' IS NOT NULL "
                    "  GROUP BY url, dh "
                    ") sub WHERE rn = 1"
                )
                res = await conn.execute(stmt)
                for url, dh, n in res.all():
                    if url and dh:
                        out[url] = dh
        finally:
            await engine.dispose()
        return out

    return asyncio.run(_query())


def detect_drift(scope: str = "full") -> DriftReport:
    """Detecta mudanças comparando hashes remotos contra baseline no banco."""
    log.info("drift_detect_start", scope=scope)
    entries = load_sources(scope)
    baseline = get_baseline_hashes()
    monitored_urls: dict[str, tuple[str, str]] = {}  # url -> (cloud, service)

    for entry in entries:
        cloud_svc = entry.get("service", "?")
        # tenta extrair cloud do primeiro URL
        for url in entry.get("urls", []):
            if "aws.amazon.com" in url:
                cloud = "aws"
            elif "cloud.google.com" in url or "googleapis.com" in url:
                cloud = "gcp"
            elif "microsoft.com" in url or "azure.com" in url:
                cloud = "azure"
            else:
                cloud = "?"
            monitored_urls[url] = (cloud, cloud_svc)

    log.info("drift_baseline_loaded", monitored=len(monitored_urls), in_db=len(baseline))

    report = DriftReport(scope=scope)

    # URLs monitoradas que sumiram do banco (removidas) ou mudaram
    checked = 0
    for url, (cloud, svc) in monitored_urls.items():
        old_hash = baseline.get(url)
        # Para evitar travar: só checa online se houver baseline ou se for nova
        new_hash = fetch_url_hash(url)

        if old_hash is None and new_hash is not None:
            # URL nova, não estava no banco
            report.changes.append(DriftEntry(
                cloud=cloud, service=svc, url=url, status="new", new_hash=new_hash
            ))
        elif old_hash is not None and new_hash is None:
            # URL sumiu (404/timeout) - não reportamos como removed se for intermitente
            log.warning("url_unreachable", url=url)
        elif old_hash is not None and new_hash is not None and old_hash != new_hash:
            report.changes.append(DriftEntry(
                cloud=cloud, service=svc, url=url, status="modified",
                old_hash=old_hash, new_hash=new_hash
            ))

        checked += 1
        if checked % 25 == 0:
            log.info("drift_check_progress", checked=checked, drift=len(report.changes))

    # URLs no banco que não estão mais no catálogo (removidas de verdade).
    monitored_set = set(monitored_urls.keys()) | known_catalog_urls()
    for url in baseline:
        if url not in monitored_set:
            cloud, svc = "?", "?"
            report.changes.append(DriftEntry(
                cloud=cloud, service=svc, url=url, status="removed", old_hash=baseline[url]
            ))

    # Stats
    by_status: dict[str, int] = defaultdict(int)
    by_cloud: dict[str, int] = defaultdict(int)
    by_service: dict[str, int] = defaultdict(int)
    for c in report.changes:
        by_status[c.status] += 1
        by_cloud[c.cloud] += 1
        by_service[c.service] += 1

    report.stats = dict(by_status)
    report.summary = {
        "monitored_urls": len(monitored_urls),
        "baseline_urls": len(baseline),
        "by_cloud": dict(by_cloud),
        "by_service_top10": dict(
            sorted(by_service.items(), key=lambda x: -x[1])[:10]
        ),
    }
    report.drift_detected = len(report.changes) > 0

    log.info("drift_detect_complete",
             changes=len(report.changes),
             new=by_status["new"],
             modified=by_status["modified"],
             removed=by_status["removed"])
    return report


def save_drift_report(report: DriftReport, path: Path) -> None:
    """Função pública para salvar o relatório (usada por testes)."""
    save_report_(report, path)


def save_report_(report: DriftReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def trigger_reingestion(scope: str = "full") -> int:
    """Roda a ingestão normal do CIP (que tem delta detection built-in).

    O escopo precisa ser propagado: com 'full' hardcoded, uma execução
    --scope mvp expandia o corpus para TODA a documentação de serviços
    (centenas de URLs), muito além do corpus ingerido.
    """
    log.info("triggering_reingestion", scope=scope)
    result = subprocess.run(
        [sys.executable, "-m", "cip.ingestion.ingest", "--scope", scope],
        cwd=str(SRC_PATH.parent),
    )
    return result.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Detecção de drift + re-ingestão mensal")
    ap.add_argument("--scope", choices=["mvp", "full"], default="full")
    ap.add_argument("--detect-only", action="store_true",
                    help="Apenas detectar drift, sem re-ingerir")
    ap.add_argument("--report-json", type=Path, default=REPORT_FILE,
                    help="Arquivo de saída do relatório")
    args = ap.parse_args()

    configure_logging()
    report = detect_drift(args.scope)
    save_report_(report, args.report_json)

    print(f"\n=== DRIFT REPORT ===")
    print(f"Timestamp:   {report.timestamp}")
    print(f"Scope:       {report.scope}")
    print(f"Monitored:   {report.summary.get('monitored_urls', 0)} URLs")
    print(f"Baseline:    {report.summary.get('baseline_urls', 0)} URLs no banco")
    print(f"Changes:     {len(report.changes)}")
    print(f"  new:       {report.stats.get('new', 0)}")
    print(f"  modified:  {report.stats.get('modified', 0)}")
    print(f"  removed:   {report.stats.get('removed', 0)}")
    if report.summary.get("by_cloud"):
        print(f"\nBy cloud:")
        for c, n in sorted(report.summary["by_cloud"].items(), key=lambda x: -x[1]):
            print(f"  {c}: {n}")
    print(f"\nRelatório salvo em: {args.report_json}")

    if args.detect_only:
        return 1 if report.drift_detected else 0

    if report.drift_detected:
        print(f"\nDrift detectado. Iniciando re-ingestão...")
        rc = trigger_reingestion(args.scope)
        return rc if rc != 0 else 1

    print("\nSem drift. Nada a fazer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())