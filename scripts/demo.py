#!/usr/bin/env python3
"""Demo end-to-end do CIP — showcase das capacidades.

Roda uma sequência de queries demonstrando:
1. Knowledge (RAG puro)
2. Comparação multi-cloud
3. Inspection Engine (Terraform)
4. Inspection Engine (Kubernetes)
5. FinOps specialist
6. ReAct mode (raciocínio adaptativo)

Uso:
    # Com stub LLM (modo dev, sem credenciais):
    python scripts/demo.py

    # Com mock cloud (recomendado em dev):
    python scripts/demo.py --mock-clouds

    # Com LLM real (Bedrock) + clouds reais:
    CIP_USE_MOCK_CLOUDS=false python scripts/demo.py --llm-real
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────
# Demo queries
# ─────────────────────────────────────────────────────────────────────────

DEMO_QUERIES = [
    {
        "title": "1. KNOWLEDGE — Well-Architected Framework",
        "question": "Quais são os 6 pilares do AWS Well-Architected Framework?",
        "cloud": "aws",
    },
    {
        "title": "2. COMPARISON — Multi-cloud serverless",
        "question": "Compare AWS Lambda vs Azure Functions vs GCP Cloud Functions.",
        "cloud": None,
    },
    {
        "title": "3. INSPECTION (Terraform) — Recursos inseguros",
        "question": "Revise este Terraform e liste problemas de segurança e custo.",
        "cloud": "aws",
        "iac": """\
resource "aws_s3_bucket" "data" {
  bucket = "critical-data"
}

resource "aws_security_group" "web" {
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "web" {
  ami = "ami-12345"
  instance_type = "m5.xlarge"
}

resource "aws_db_instance" "primary" {
  engine = "postgres"
  instance_class = "db.t3.medium"
  allocated_storage = 100
  tags = { Environment = "prod" }
}
""",
    },
    {
        "title": "4. INSPECTION (Kubernetes) — Security issues",
        "question": "Revise este manifesto Kubernetes e encontre problemas de segurança.",
        "cloud": "gcp",
        "iac": """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: production
spec:
  template:
    spec:
      hostNetwork: true
      containers:
        - name: api
          image: myrepo/api:latest
          securityContext:
            privileged: true
          resources:
            limits:
              cpu: 500m
              memory: 512Mi
        - name: worker
          image: myrepo/worker:latest
""",
    },
    {
        "title": "5. FINOPS specialist — Savings Plans",
        "question": "Como economizar custos de EC2 com Savings Plans?",
        "cloud": "aws",
    },
    {
        "title": "6. SECURITY specialist — IAM best practices",
        "question": "Quais as melhores práticas de IAM na AWS?",
        "cloud": "aws",
    },
]


def _print_banner(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def _print_truncated(text: str, max_chars: int = 400) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... ({len(text) - max_chars} chars truncated)"


async def run_demo(args: argparse.Namespace) -> int:
    """Roda demo end-to-end."""
    print("=" * 78)
    print("  CIP — Cloud Intelligence Platform DEMO")
    print("=" * 78)
    print()
    print(f"LLM_PROVIDER:       {os.getenv('LLM_PROVIDER', 'stub')}")
    print(f"EMBED_PROVIDER:     {os.getenv('EMBED_PROVIDER', 'local')}")
    print(f"CIP_USE_MOCK_CLOUDS: {os.getenv('CIP_USE_MOCK_CLOUDS', 'false')}")
    print(f"ReAct mode:          {args.react or os.getenv('CIP_REACT_MODE', 'false')}")
    print()

    # Reseta singletons (importante se rodando múltiplas vezes)
    from src.cip.agents import orchestrator as orch_mod
    from src.cip.rag import engine as rag_mod
    orch_mod._orchestrator = None
    rag_mod._engine = None

    # Configurar modo mock se pedido
    if args.mock_clouds:
        os.environ["CIP_USE_MOCK_CLOUDS"] = "true"
        print("[INFO] CIP_USE_MOCK_CLOUDS=true (tools usarão mock server)")
        print()

    from src.cip.agents.orchestrator import get_orchestrator

    orch = get_orchestrator()

    for q in DEMO_QUERIES:
        _print_banner(q["title"])
        print(f"P: {q['question']}")
        if q.get("cloud"):
            print(f"Cloud: {q['cloud']}")
        if q.get("iac"):
            preview_len = 200
            iac_preview = q["iac"][:preview_len]
            if len(q["iac"]) > preview_len:
                iac_preview += "..."
            print(f"IaC: {iac_preview}")
        print()

        t0 = time.perf_counter()
        try:
            result = await orch.handle(
                question=q["question"],
                cloud=q.get("cloud"),
                iac_payload=q.get("iac"),
                react_mode=args.react,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {exc}")
            continue
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        # Sumário da resposta
        print(f">>> Resposta ({elapsed_ms}ms, plan={result.plan.intent.value if result.plan else '?'}):")
        print(_print_truncated(result.summary, 500))
        print()

        # Findings (se houver)
        if result.findings:
            print(f">>> Findings ({len(result.findings)}):")
            for f in result.prioritized_findings()[:3]:
                impact = f"${f.financial_impact_usd:.0f}" if f.financial_impact_usd else "n/a"
                print(f"  [{f.severity:>8}] {f.domain:<13} {impact:>8}  {f.title}")
            print()

        # Sources (se houver)
        if result.sources:
            print(f">>> Sources ({len(result.sources)}):")
            for s in result.sources[:3]:
                if isinstance(s, dict):
                    cloud = s.get("cloud") or "?"
                    title = s.get("title") or s.get("url") or "?"
                    print(f"  - [{cloud}] {title[:80]}")
                elif hasattr(s, "__dict__"):
                    cloud = s.__dict__.get("cloud") or "?"
                    title = s.__dict__.get("title") or s.__dict__.get("url") or "?"
                    print(f"  - [{cloud}] {title[:80]}")
                else:
                    print(f"  - {str(s)[:80]}")
            print()

    _print_banner("DEMO CONCLUÍDO")
    print(f"Total: {len(DEMO_QUERIES)} queries demonstradas")
    print()
    print("Para usar o CIP em produção:")
    print("  1. Configure credenciais AWS/Azure/GCP (.env)")
    print("  2. Configure Bedrock (LLM_PROVIDER=bedrock)")
    print("  3. Rode: python -m cip.api.app")
    print("  4. Acesse: http://localhost:8000/docs")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CIP end-to-end demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--react", action="store_true",
        help="Usa ReAct/function-calling mode",
    )
    parser.add_argument(
        "--mock-clouds", action="store_true",
        help="Configura CIP_USE_MOCK_CLOUDS=true (precisa mock server rodando)",
    )
    args = parser.parse_args()
    return asyncio.run(run_demo(args))


if __name__ == "__main__":
    sys.exit(main())