#!/usr/bin/env python3
"""Orquestra o setup do ambiente de homologação local.

Sequence:
1. Verifica pré-requisitos (podman, Python 3.11+, etc)
2. Sobe Postgres+pgvector via podman-compose
3. Aguarda DB ficar ready
4. Aplica schema
5. Ingeri knowledge base (MVP)
6. Roda pre-flight checks
7. Roda smoke tests
8. Reporta status final

Uso:
    # Setup completo (default)
    python scripts/setup_homolog.py

    # Setup + smoke test apenas (assume stack já rodando)
    python scripts/setup_homolog.py --skip-build

    # Skip ingestion (mais rápido, para CI)
    python scripts/setup_homolog.py --skip-ingest

    # Custom URL
    python scripts/setup_homolog.py --api-url http://homolog.cip.internal:8000

Exit codes:
    0 = Setup completo OK
    1 = Falha em algum passo
    2 = Pré-requisito faltando
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def run(cmd: list[str], check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    """Roda comando, loga, retorna CompletedProcess."""
    print(f"  $ {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 and check:
            print(f"  [ERROR] exit code {result.returncode}")
            if result.stdout:
                print(f"  stdout: {result.stdout[:500]}")
            if result.stderr:
                print(f"  stderr: {result.stderr[:500]}")
        return result
    except subprocess.TimeoutExpired:
        print(f"  [ERROR] timeout after {timeout}s")
        return subprocess.CompletedProcess(cmd, -1, "", "")


def check_prerequisite(name: str, cmd: list[str], min_version: str | None = None) -> bool:
    """Verifica que um pré-requisito está disponível."""
    print(f"  Checking {name}...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        print(f"  [FAIL] {name} not found")
        return False
    version = result.stdout.strip().split("\n")[0] if result.stdout else "unknown"
    print(f"  [OK] {name} ({version})")
    return True


def wait_for_db(host: str, port: int, timeout_s: int = 30) -> bool:
    """Aguarda DB ficar pronto (TCP connect)."""
    import socket

    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


# ─────────────────────────────────────────────────────────────────────────
# Steps
# ─────────────────────────────────────────────────────────────────────────


def step_check_prerequisites() -> bool:
    """Verifica pré-requisitos do sistema."""
    print("\n=== Step 1/7: Check prerequisites ===\n")
    ok = True
    ok &= check_prerequisite("podman", ["podman", "--version"])
    ok &= check_prerequisite("python3", ["python", "--version"])
    ok &= check_prerequisite("curl", ["curl", "--version"])
    return ok


def step_start_database() -> bool:
    """Sobe Postgres+pgvector via podman-compose."""
    print("\n=== Step 2/7: Start Postgres+pgvector ===\n")
    result = run(["podman", "compose", "up", "-d", "db"], timeout=60)
    if result.returncode != 0:
        return False
    print("  [OK] DB container started")
    return True


def step_wait_db_ready() -> bool:
    """Aguarda DB ficar pronto para receber conexões."""
    print("\n=== Step 3/7: Wait for DB ready ===\n")
    if not wait_for_db("127.0.0.1", 5432, timeout_s=30):
        print("  [FAIL] DB not ready after 30s")
        return False
    print("  [OK] DB ready on localhost:5432")
    return True


def step_apply_schema() -> bool:
    """Aplica db/schema.sql."""
    print("\n=== Step 4/7: Apply database schema ===\n")
    db_url = os.environ.get("DATABASE_URL", "postgresql://cip:cip@localhost:5432/cip")
    schema_file = ROOT / "db" / "schema.sql"
    if not schema_file.exists():
        print(f"  [FAIL] Schema not found: {schema_file}")
        return False
    # Usa psql via podman exec (se disponível) ou direto
    try:
        result = subprocess.run(
            ["psql", db_url, "-f", str(schema_file)],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        # Fallback: podman exec
        result = subprocess.run(
            ["podman", "exec", "-i", "cip-db", "psql", "-U", "cip", "-d", "cip", "-f", "/docker-entrypoint-initdb.d/01-schema.sql"],
            capture_output=True, text=True, timeout=30,
        )
    if result.returncode != 0:
        print(f"  [FAIL] Schema apply: {result.stderr[:200]}")
        return False
    print("  [OK] Schema applied")
    return True


def step_ingest() -> bool:
    """Roda ingestão MVP."""
    print("\n=== Step 5/7: Ingest knowledge base (MVP) ===\n")
    # Verifica se já tem dados
    try:
        import subprocess as sp
        result = sp.run(
            ["podman", "exec", "cip-db", "psql", "-U", "cip", "-d", "cip", "-c", "SELECT count(*) FROM data_cloud_docs"],
            capture_output=True, text=True, timeout=5,
        )
        if "200" in result.stdout or "100" in result.stdout or "300" in result.stdout:
            print(f"  [SKIP] Already have chunks in DB")
            return True
    except Exception:
        pass

    result = run(
        [sys.executable, "-m", "cip.ingestion.ingest", "--scope", "mvp"],
        timeout=600,
    )
    if result.returncode != 0:
        return False
    print("  [OK] Knowledge base ingested")
    return True


def step_preflight() -> bool:
    """Roda pre-flight checks."""
    print("\n=== Step 6/7: Pre-flight checks ===\n")
    result = run(
        [sys.executable, "scripts/preflight.py", "--skip-tests"],
        timeout=60,
    )
    return result.returncode == 0


def step_smoke_test(api_url: str) -> bool:
    """Roda smoke tests contra a API."""
    print("\n=== Step 7/7: Smoke tests ===\n")
    result = run(
        [sys.executable, "scripts/smoke_test.py", "--url", api_url],
        timeout=120,
    )
    return result.returncode == 0


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    import os

    parser = argparse.ArgumentParser(
        description="Setup completo do ambiente de homologação local (podman)"
    )
    parser.add_argument(
        "--api-url", default="http://localhost:8000",
        help="URL da API para smoke test (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--skip-build", action="store_true",
        help="Pula etapas de DB (assume stack já rodando)",
    )
    parser.add_argument(
        "--skip-ingest", action="store_true",
        help="Pula ingestion (assume KB já populada)",
    )
    parser.add_argument(
        "--skip-tests", action="store_true",
        help="Pula smoke tests no final",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  CIP — SETUP HOMOLOGAÇÃO LOCAL")
    print("=" * 70)

    start = time.monotonic()

    # Steps
    if not step_check_prerequisites():
        print("\n[FAIL] Pré-requisitos faltando. Instale podman e tente novamente.")
        return 2

    if not args.skip_build:
        if not step_start_database():
            return 1
        if not step_wait_db_ready():
            return 1
        if not step_apply_schema():
            return 1

    if not args.skip_ingest:
        if not step_ingest():
            return 1

    if not step_preflight():
        print("\n[WARN] Pre-flight reportou warnings. Continuando...")

    if not args.skip_tests:
        if not step_smoke_test(args.api_url):
            print("\n[FAIL] Smoke tests falharam. Verifique logs acima.")
            return 1

    elapsed = time.monotonic() - start
    print()
    print("=" * 70)
    print(f"  SETUP COMPLETO em {elapsed:.1f}s")
    print("=" * 70)
    print()
    print("  Próximos passos:")
    print(f"    1. Acesse a API: {args.api_url}/docs")
    print(f"    2. Web UI: make web  (abre em :8080)")
    print(f"    3. Demo: make demo  (6 queries showcase)")
    print(f"    4. Logs: podman logs -f cip-api")
    print()
    print("  Para produção (Railway + Bedrock), veja docs/18-production-runbook.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())