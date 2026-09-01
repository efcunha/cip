#!/usr/bin/env python3
"""Aplica migrations SQL do diretório db/migrations/ em ordem lexicográfica.

Cada arquivo é executado exatamente uma vez (controlado por tabela
``schema_migrations``). Use para evoluir o schema sem perder dados.

Implementação usa ``psycopg`` (driver Python já presente no container)
em vez do binário ``psql`` (que não é instalado na imagem runtime/base).
Isso torna o script portável para o estágio enxuto ``base`` e para o
estágio ``homolog``.

Uso:
    python scripts/apply_migrations.py
    python scripts/apply_migrations.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import psycopg
    from psycopg import ClientCursor
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    ClientCursor = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "db" / "migrations"


def list_migrations() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return files


def db_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql://cip:cip@localhost:5432/cip"
    )


def _sanitize_conn_error(exc: Exception) -> str:
    """Não vaza URL de conexão (pode conter senha) em logs/erros."""
    msg = str(exc)
    if "password=" in msg:
        msg = msg.split("password=", 1)[0].rstrip()
    return msg or type(exc).__name__


def _connect(url: str | None = None) -> "psycopg.Connection":
    if psycopg is None:  # pragma: no cover
        raise RuntimeError(
            "psycopg não está instalado. Rode `pip install psycopg[binary]`."
        )
    # autocommit=False: cada migration roda numa transação explícita,
    # então falha = rollback (schema íntegro). A tabela de controle é
    # commitada junto com a migration aplicada.
    try:
        return psycopg.connect(url or db_url(), autocommit=False)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"falha ao conectar no banco: {_sanitize_conn_error(exc)}"
        ) from exc


def ensure_tracking_table(conn: "psycopg.Connection") -> None:
    """Cria tabela de controle se ainda não existir."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    conn.commit()


def already_applied(conn: "psycopg.Connection", version: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version = %s", (version,)
    )
    return cur.fetchone() is not None


def apply_one(conn: "psycopg.Connection", path: Path, dry_run: bool = False) -> str:
    """Aplica uma migration. Retorna 'applied' | 'skipped' | 'dry-run'."""
    version = path.name
    print(f"  - {version} ... ", end="", flush=True)

    if dry_run:
        print("DRY-RUN")
        return "dry-run"

    if already_applied(conn, version):
        print("SKIPPED (already applied)")
        return "skipped"

    # Fecha a transação implícita aberta pelo SELECT de `already_applied`
    # (conn.execute com autocommit=False entra em INTRANS). Sem este rollback,
    # o `with conn.transaction()` seguinte NÃO inicia uma transação nova e o
    # `ClientCursor.execute(sql)` multi-statement roda numa transação "suja"
    # que é descartada no fim da conexão (Round 24 — ROOT CAUSE).
    conn.rollback()

    # Executa o arquivo SQL como parte de uma transação explícita.
    #
    # ROOT CAUSE (Round 24): `conn.execute(sql)` usa o EXTENDED protocol do
    # psycopg 3.3, que NÃO divide scripts multi-statement — statements após o
    # primeiro (incl. `CREATE FUNCTION ... $$ ... $$`) eram descartados
    # silenciosamente (statusmessage só do 1º), a transação ficava inconsistente
    # e NADA persistia (tabelas sumiam, schema_migrations vazia). A fix usa
    # `ClientCursor` (simple query protocol), que envia o script como uma única
    # query simple e o PostgreSQL executa todos os statements. A transação
    # garante rollback total em caso de erro no meio do arquivo.
    sql = path.read_text(encoding="utf-8")
    try:
        with conn.transaction():
            with ClientCursor(conn) as cur:
                cur.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations(version) VALUES (%s) "
                "ON CONFLICT DO NOTHING",
                (version,),
            )
    except Exception as exc:  # noqa: BLE001
        print("FAIL")
        print(f"  error: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise RuntimeError(f"migration failed: {version}") from exc

    print("OK")
    return "applied"


def run_migrations(database_url: str | None = None, dry_run: bool = False) -> int:
    """Aplica todas as migrations pendentes (idempotente).

    Retorna 0 em sucesso; levanta ``RuntimeError`` em falha de migration.
    Reusado pelo startup do ``cip-api`` (lifespan) para garantir que o schema
    está no nível correto ANTES de servir tráfego — fail-closed: se a migration
    falhar, o serviço não sobe falso-healthy.
    """
    files = list_migrations()
    if not files:
        print("[INFO] Nenhuma migration encontrada em db/migrations/")
        return 0

    print(f"Encontradas {len(files)} migration(s):")
    for f in files:
        print(f"  - {f.name}")

    if dry_run:
        print("\n[OK] Modo dry-run — nenhuma migration aplicada.")
        return 0

    print("\nConectando ao banco...")
    conn = _connect(database_url)
    print("\nCriando/validando tabela de controle...")
    ensure_tracking_table(conn)
    print("\nAplicando migrations:")
    for f in files:
        apply_one(conn, f)
    conn.close()

    print("\n[OK] Migrations processadas.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Aplica migrations SQL em ordem")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista migrations sem aplicar",
    )
    args = parser.parse_args()
    return run_migrations(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
