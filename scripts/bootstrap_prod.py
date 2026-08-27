#!/usr/bin/env python3
"""Bootstrap idempotente do CIP (deploy self-contained / open-source).

Executado pelo serviço efêmero `cip-init` do ``docker-compose.prod.yml``.

Sequência idempotente (pode rodar N vezes sem efeitos colaterais):
  1. wait-for-db: aguardar o Postgres (`cip_postgres`) aceitar conexões.
  2. Aplicar ``db/schema.sql`` (via psycopg, já que a imagem `base` NÃO tem o
     binário ``psql``). CREATE EXTENSION/CREATE TABLE usam IF NOT EXISTS.
  3. Aplicar ``db/migrations/*.sql`` via ``scripts/apply_migrations.py``
     (tabela de controle ``schema_migrations`` impede re-aplicação).
  4. Ingerir a KB (`python -m cip.ingestion.ingest --scope mvp`). O ingest já é
     idempotente: dedupe por ``content_hash`` + delta por ``doc_hash`` fazem
     re-subidas não duplicarem chunks.

Exit code: 0 = bootstrap completo (schema + migrations + ingest OK).
          1 = falha em qualquer passo (o compose NÃO sobe o cip-api).

Uso:
    python scripts/bootstrap_prod.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = ROOT / "db" / "schema.sql"

DB_PORT = int(os.environ.get("DB_PORT", "5432"))


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql://cip:cip@cip_postgres:5432/cip"
    )


def _wait_for_db(timeout_s: int = 120) -> bool:
    """Aguarda o Postgres aceitar TCP no host/porta configurados."""
    import socket

    host = os.environ.get("DB_HOST", "cip_postgres")
    port = DB_PORT
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"[bootstrap] DB reachable at {host}:{port}", flush=True)
                return True
        except OSError as exc:  # noqa: BLE001 - retry esperado durante warm-up
            last_err = exc
            time.sleep(2)
    print(f"[bootstrap] ERROR: DB not reachable after {timeout_s}s: {last_err}",
          file=sys.stderr)
    return False


def _apply_schema() -> bool:
    """Aplica db/schema.sql via psycopg (autocommit; statements IF NOT EXISTS)."""
    import psycopg
    from psycopg import ClientCursor

    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    print(f"[bootstrap] applying schema {SCHEMA_FILE.name} ({len(sql)} bytes)", flush=True)
    # autocommit=True porque schema.sql tem CREATE EXTENSION (não roda em tx).
    # ClientCursor (simple query) garante execução multi-statement fiel —
    # mesmo padrão da fix no scripts/apply_migrations.py (Round 24).
    with psycopg.connect(_db_url(), autocommit=True) as conn:
        with ClientCursor(conn) as cur:
            cur.execute(sql)
    print("[bootstrap] schema OK", flush=True)
    return True


def _apply_migrations() -> bool:
    """Aplica db/migrations/*.sql via scripts/apply_migrations.py (idempotente)."""
    script = ROOT / "scripts" / "apply_migrations.py"
    env = os.environ.copy()
    env["DATABASE_URL"] = _db_url()
    print("[bootstrap] applying migrations (scripts/apply_migrations.py)", flush=True)
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        env=env,
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"[bootstrap] ERROR: migrations failed (exit {result.returncode})",
              file=sys.stderr)
        return False
    print("[bootstrap] migrations OK", flush=True)
    return True


def _ingest() -> bool:
    """Ingere a KB (--scope mvp). Idempotente por dedupe de content_hash."""
    env = os.environ.copy()
    env["DATABASE_URL"] = _db_url()
    print("[bootstrap] ingesting KB (python -m cip.ingestion.ingest --scope mvp)",
          flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "cip.ingestion.ingest", "--scope", "mvp"],
        cwd=str(ROOT),
        env=env,
        capture_output=False,
    )
    if result.returncode != 0:
        print(f"[bootstrap] ERROR: ingest failed (exit {result.returncode})",
              file=sys.stderr)
        return False
    print("[bootstrap] ingest OK", flush=True)
    return True


def main() -> int:
    print("=" * 70, flush=True)
    print("  CIP — BOOTSTRAP (schema + migrations + ingest)", flush=True)
    print(f"  DATABASE_URL = {_db_url().split('@')[-1] if '@' in _db_url() else _db_url()}",
          flush=True)
    print("=" * 70, flush=True)

    if not _wait_for_db():
        return 1
    if not _apply_schema():
        return 1
    if not _apply_migrations():
        return 1
    if not _ingest():
        return 1

    print("=" * 70, flush=True)
    print("  BOOTSTRAP COMPLETO — schema + migrations + ingest OK", flush=True)
    print("=" * 70, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
