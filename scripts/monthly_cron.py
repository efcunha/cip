#!/usr/bin/env python3
"""Wrapper cron-friendly para re-ingestão mensal com drift detection.

Este script é projetado para ser invocado mensalmente via:
  - crontab (Linux/Mac)
  - Task Scheduler (Windows)
  - GitHub Actions schedule
  - Railway Cron / Heroku Scheduler

Comportamento:
1. Roda drift detection (`scripts/monthly_reingest.py --detect-only`)
2. Se drift > 0: executa re-ingestão completa (`scripts/monthly_reingest.py`)
3. Salva relatório em `ingest_drift_report.json` (auto-archivado por data)
4. Exit codes compatíveis com CI:
   - 0 = OK (sem drift ou re-ingestão bem-sucedida)
   - 1 = drift detectado mas re-ingestão OK (informativo)
   - 2 = erro de execução

Logs estruturados (structlog) em stdout + stderr (capturável por journald/cw).

Uso direto:
    python scripts/monthly_cron.py
    python scripts/monthly_cron.py --scope mvp  # só MVP
    python scripts/monthly_cron.py --dry-run    # só detectar, sem re-ingerir
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "monthly_reingest.py"
REPORTS_DIR = ROOT / "ingest_drift_reports"


def _archive_previous_report() -> Path | None:
    """Move relatório anterior para arquivo datado (histórico)."""
    src = ROOT / "ingest_drift_report.json"
    if not src.exists():
        return None
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m")
    dst = REPORTS_DIR / f"drift_report_{timestamp}_{src.stat().st_size}b.json"
    if not dst.exists():  # não sobrescrever meses anteriores
        shutil.copy2(src, dst)
    return dst


def _run_script(args: list[str]) -> tuple[int, str, str]:
    """Roda monthly_reingest.py com args, retorna (rc, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return result.returncode, result.stdout, result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cron mensal de re-ingestão com drift detection (Fase 6)"
    )
    parser.add_argument(
        "--scope", choices=["mvp", "full"], default="full",
        help="Escopo de ingestão (mvp = só frameworks, full = completo)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Apenas detectar drift, sem re-ingerir",
    )
    args = parser.parse_args()

    print(f"[{datetime.now(timezone.utc).isoformat()}] Cron mensal iniciando (scope={args.scope})")

    # Arquiva relatório anterior antes de gerar novo
    archived = _archive_previous_report()
    if archived:
        print(f"Relatório anterior arquivado em: {archived}")

    # 1. Drift detection
    print("\n=== Step 1: Drift detection ===")
    rc, stdout, stderr = _run_script(["--detect-only", "--scope", args.scope])
    print(stdout)
    if stderr:
        print(f"[stderr] {stderr}", file=sys.stderr)

    if rc == 2:
        print(f"[ERROR] Drift detection falhou (rc={rc})")
        return 2

    # Lê relatório JSON gerado
    report_path = ROOT / "ingest_drift_report.json"
    if not report_path.exists():
        print("[ERROR] Relatório não foi gerado")
        return 2

    import json

    report = json.loads(report_path.read_text(encoding="utf-8"))
    drift_detected = report.get("drift_detected", False)
    n_changes = len(report.get("changes", []))

    print(f"\n=== Resultado: drift_detected={drift_detected}, changes={n_changes} ===")

    if not drift_detected or args.dry_run:
        print(f"[OK] Sem drift{'(dry-run)' if args.dry_run else ''} - nada a fazer.")
        return 0 if not drift_detected else 1

    # 2. Re-ingestão
    print(f"\n=== Step 2: Re-ingest (drift detectado) ===")
    rc, stdout, stderr = _run_script(["--scope", args.scope])
    print(stdout)
    if stderr:
        print(f"[stderr] {stderr}", file=sys.stderr)

    if rc != 0:
        print(f"[ERROR] Re-ingestão falhou (rc={rc})")
        return 2

    print(f"\n[OK] Cron mensal concluído com sucesso (drift {n_changes} URLs)")
    return 1  # drift detectado + re-ingest OK (info)


if __name__ == "__main__":
    sys.exit(main())