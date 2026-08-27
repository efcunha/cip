#!/usr/bin/env python3
"""Serve a Web UI do CIP localmente.

Combina API + Web UI em um único processo para demo local.
Não requer deploy externo — só Python stdlib.

Uso:
    # 1. Em um terminal, subir a API:
    make up

    # 2. Em outro terminal, servir a web UI:
    python scripts/serve_web.py

    # 3. Abrir http://localhost:8080 no browser

Ou servir em outra porta:
    python scripts/serve_web.py --port 8080 --api-url http://localhost:8000

Requisitos: API rodando separadamente em :8000 (ou outra porta).
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"


class Handler(http.server.SimpleHTTPRequestHandler):
    """Handler que serve arquivos de web/."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self) -> None:
        # Permite CORS para desenvolvimento
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        # Silencia logs do stdout (mantém limpo)
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve a Web UI do CIP localmente (sem deploy)"
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Porta do servidor web (default: 8080)",
    )
    parser.add_argument(
        "--api-url", default="http://localhost:8000",
        help="URL da API backend (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Não abrir browser automaticamente",
    )
    args = parser.parse_args()

    # Verifica que web/ existe
    if not WEB_DIR.exists():
        print(f"[ERROR] {WEB_DIR} não encontrado")
        return 1
    if not (WEB_DIR / "index.html").exists():
        print(f"[ERROR] {WEB_DIR}/index.html não encontrado")
        return 1

    # Cria servidor
    with socketserver.TCPServer(("", args.port), Handler) as httpd:
        url = f"http://localhost:{args.port}"
        print("=" * 70)
        print(f"  CIP Web UI rodando em {url}")
        print("=" * 70)
        print()
        print(f"  API backend esperado em: {args.api_url}")
        print(f"  (pode ser alterado na própria UI)")
        print()
        print("  Press Ctrl+C to stop.")
        print()

        if not args.no_browser:
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[OK] Server stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())