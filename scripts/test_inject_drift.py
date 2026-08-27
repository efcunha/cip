"""Helper para teste: injeta um doc_hash falso em uma URL para simular drift.

Uso:
    python scripts/test_inject_drift.py
    # Rola de volta: UPDATE data_cloud_docs SET metadata_ = metadata_ - 'doc_hash' WHERE ...
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

FAKE_HASH = "INJECTED_FAKE_HASH_FOR_DRIFT_TEST_1234567890ABCDEF"


async def main() -> None:
    engine = create_async_engine("postgresql+asyncpg://cip:cip@localhost:5432/cip")
    try:
        async with engine.begin() as conn:
            # Seleciona um chunk de AWS Well-Architected
            result = await conn.execute(
                text(
                    "SELECT id, metadata_ ->> 'url' FROM data_cloud_docs "
                    "WHERE metadata_ ->> 'cloud' = 'aws' "
                    "AND metadata_ ->> 'doc_hash' IS NOT NULL "
                    "LIMIT 1"
                )
            )
            row = result.first()
            if not row:
                print("Nenhum registro AWS encontrado")
                return
            target_id, target_url = row
            # Atualiza o doc_hash usando psycopg direto para evitar problemas de tipo
            from psycopg import sql as psql

            await conn.execute(
                text("SELECT 1")  # dummy para manter a transação aberta
            )
            raw_conn = await conn.get_raw_connection()
            # pgvector/asyncpg: psycopg conn
            async with raw_conn.driver_connection.cursor() as cur:
                await cur.execute(
                    "UPDATE data_cloud_docs SET metadata_ = "
                    "jsonb_set(metadata_, '{doc_hash}', to_jsonb(%s::text)) "
                    "WHERE id = %s",
                    (FAKE_HASH, target_id),
                )
            print(f"Hash fake injetado em id={target_id} url={target_url[:80]}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())