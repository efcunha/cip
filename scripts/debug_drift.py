"""Debug: ver o que baseline retorna."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine("postgresql+asyncpg://cip:cip@localhost:5432/cip")
    async with engine.connect() as conn:
        # 1. Distinct hash por URL (sem GROUP BY)
        print("=== TODOS OS HASHES POR URL (sem agrupar) ===")
        res = await conn.execute(text(
            "SELECT metadata_ ->> 'url' AS url, COUNT(*) as n_chunks, "
            "COUNT(DISTINCT metadata_ ->> 'doc_hash') as n_distinct_hashes, "
            "MIN(metadata_ ->> 'doc_hash') as first_hash "
            "FROM data_cloud_docs WHERE metadata_ ->> 'doc_hash' IS NOT NULL "
            "GROUP BY url ORDER BY n_distinct_hashes DESC LIMIT 10"
        ))
        for row in res.all():
            print(f"  {row[0][:60]:<60} n={row[1]} distinct={row[2]} hash={row[3][:20]}...")

        print("\n=== PARA A URL INJETADA ===")
        res = await conn.execute(text(
            "SELECT id, metadata_ ->> 'doc_hash' AS dh "
            "FROM data_cloud_docs "
            "WHERE metadata_ ->> 'url' LIKE '%framework/welcome%' "
            "ORDER BY id LIMIT 5"
        ))
        for row in res.all():
            print(f"  id={row[0]} hash={row[1][:30]}...")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())