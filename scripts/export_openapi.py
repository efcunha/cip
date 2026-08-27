#!/usr/bin/env python3
"""Export OpenAPI 3.0 spec do FastAPI para arquivo JSON.

Uso:
    python scripts/export_openapi.py --output docs/openapi.json
    python scripts/export_openapi.py --output docs/openapi.yaml  # YAML via pyyaml

Spec pode ser importado em:
- Postman / Insomnia (test manual da API)
- openapi-generator-cli (gerar SDK em TS/Java/Go/etc.)
- Swagger UI (documentação interativa)
- terraform-provider-openapi (IaC)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def export_openapi(output_path: Path, fmt: str = "json") -> int:
    """Exporta OpenAPI spec do FastAPI app."""
    from src.cip.api.app import app

    spec = app.openapi()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "yaml":
        try:
            import yaml
        except ImportError:
            print("[ERROR] PyYAML não instalado. Use --format json ou pip install pyyaml.")
            return 1
        with output_path.open("w", encoding="utf-8") as f:
            yaml.dump(spec, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    else:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2, ensure_ascii=False)

    n_paths = len(spec.get("paths", {}))
    n_schemas = len(spec.get("components", {}).get("schemas", {}))
    print(f"[OK] OpenAPI spec exportado para: {output_path}")
    print(f"     {n_paths} endpoints, {n_schemas} schemas, OpenAPI {spec.get('openapi', '3.x')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Export OpenAPI spec do CIP")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs" / "openapi.json",
        help="Arquivo de saída (default: docs/openapi.json)",
    )
    parser.add_argument(
        "--format", choices=["json", "yaml"], default="json",
        help="Formato (default: json)",
    )
    args = parser.parse_args()
    return export_openapi(args.output, args.format)


if __name__ == "__main__":
    sys.exit(main())