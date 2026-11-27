"""Lista (read-only) linhas de banner de aposentadoria/fim de suporte em chunks.

Entrada: JSON Lines em stdin ou arquivo, cada linha com ``text`` e opcional ``url``
(ex.: export de ``SELECT text, metadata_->>'url' AS url FROM data_cloud_docs``).
Nada é escrito; só imprime ``url<TAB>linha`` e um resumo.

Uso:
    python scripts/detect_banners.py chunks.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from cip.ingestion.webtext import find_notice_banners


def main(argv: list[str]) -> int:
    stream = open(argv[1], encoding="utf-8") if len(argv) > 1 else sys.stdin  # noqa: SIM115
    per_url: Counter[str] = Counter()
    total = 0
    for raw in stream:
        raw = raw.strip()
        if not raw:
            continue
        row = json.loads(raw)
        url = str(row.get("url") or "?")
        hits = find_notice_banners(str(row.get("text") or ""))
        for hit in hits:
            print(f"{url}\t{hit}")
        per_url[url] += len(hits)
        total += 1
    flagged = sum(1 for n in per_url.values() if n)
    print(f"# chunks={total} urls_com_banner={flagged}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
