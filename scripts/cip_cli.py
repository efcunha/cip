#!/usr/bin/env python3
"""CLI unificada para gerenciar o CIP (Cloud Intelligence Platform).

Subcomandos:
  status      — health check do sistema (DB, vector store, LLM, rate limit)
  ingest      — rodar ingestão de knowledge base
  eval        — rodar eval suite (gate de qualidade)
  preflight   — pre-flight check antes de deploy
  drift       — detectar drift na documentação
  audit       — visualizar audit log (últimas N entries)
  metrics     — exibir métricas Prometheus agregadas
  bench       — benchmark de performance (latência p95)

Uso:
  python scripts/cip_cli.py status
  python scripts/cip_cli.py ingest --scope mvp
  python scripts/cip_cli.py eval --offline --report-md
  python scripts/cip_cli.py preflight
  python scripts/cip_cli.py drift --scope mvp
  python scripts/cip_cli.py audit --tail 50 --tenant acme
  python scripts/cip_cli.py metrics --top 10
  python scripts/cip_cli.py bench --n 50
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def cmd_status(args: argparse.Namespace) -> int:
    """Mostra health do sistema."""
    print("=" * 70)
    print("CIP SYSTEM STATUS")
    print("=" * 70)

    try:
        import asyncio

        from src.cip.api.health import run_all_checks

        # run_all_checks() é async (checks de DB usam await direto).
        # Aqui estamos fora de um event loop — usar asyncio.run().
        health = asyncio.run(run_all_checks())
        for c in health.checks:
            marker = "[OK]" if c.healthy else "[!!]"
            print(f"  {marker:<5} {c.name:<20} ({c.latency_ms:.0f}ms) {c.message}")
        print()
        print(f"Overall: {'HEALTHY' if health.healthy else 'DEGRADED'}")
        return 0 if health.healthy else 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}")
        return 2


def cmd_ingest(args: argparse.Namespace) -> int:
    """Roda ingestão."""
    cmd = [
        sys.executable, "-m", "cip.ingestion.ingest",
        "--scope", args.scope,
    ]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.resume:
        cmd.append("--resume")
    print(f"[INFO] Rodando: {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


def cmd_eval(args: argparse.Namespace) -> int:
    """Roda eval suite."""
    cmd = [
        sys.executable, str(ROOT / "eval" / "run_eval.py"),
    ]
    if args.offline:
        cmd.append("--offline")
    if args.api:
        cmd.extend(["--api", args.api])
    if args.report_md:
        cmd.append("--report-md")
    if args.strict:
        cmd.append("--strict")
    print(f"[INFO] Rodando: {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


def cmd_preflight(args: argparse.Namespace) -> int:
    """Roda pre-flight check."""
    cmd = [sys.executable, str(ROOT / "scripts" / "preflight.py")]
    if args.skip_tests:
        cmd.append("--skip-tests")
    return subprocess.call(cmd, cwd=str(ROOT))


def cmd_drift(args: argparse.Namespace) -> int:
    """Detecta drift na documentação."""
    cmd = [
        sys.executable, str(ROOT / "scripts" / "monthly_reingest.py"),
        "--detect-only",
        "--scope", args.scope,
    ]
    return subprocess.call(cmd, cwd=str(ROOT))


def cmd_audit(args: argparse.Namespace) -> int:
    """Visualiza audit log."""
    from src.cip.observability import AuditLogger, get_audit_logger

    al = get_audit_logger()
    entries = al.tail(n=args.tail)

    if args.tenant:
        entries = [e for e in entries if e.get("tenant_id") == args.tenant]

    if not entries:
        print(f"[INFO] Nenhuma entrada encontrada em {al.log_path}")
        return 0

    print(f"=" * 70)
    print(f"AUDIT LOG — Últimas {len(entries)} entradas (path: {al.log_path})")
    print(f"=" * 70)
    print()
    for e in entries:
        ts = e.get("timestamp", "?")
        tenant = e.get("tenant_id", "anon")
        endpoint = e.get("endpoint", "?")
        status = e.get("status", "?")
        latency = e.get("latency_ms", "?")
        print(
            f"  {ts[:19]} | {tenant:<10} | {endpoint:<15} | "
            f"status={status} latency={latency}ms"
        )
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    """Exibe métricas Prometheus agregadas."""
    from src.cip.observability import get_metrics

    m = get_metrics()
    output = m.render()

    # Parse e resume
    lines = output.splitlines()
    counters: list[tuple[str, dict[str, str], float]] = []
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        if "{" in line:
            name_labels, value = line.rsplit(" ", 1)
            name_part, labels_part = name_labels.split("{", 1)
            name = name_part.strip()
            labels_str = labels_part.rstrip("}")
            labels = {}
            for kv in labels_str.split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    labels[k.strip()] = v.strip().strip('"')
            try:
                counters.append((name, labels, float(value)))
            except ValueError:
                continue

    if not counters:
        print("[INFO] Sem métricas registradas. Faça algumas requests primeiro.")
        return 0

    # Agrupar por nome de métrica
    by_name: dict[str, list[tuple[dict[str, str], float]]] = {}
    for name, labels, value in counters:
        by_name.setdefault(name, []).append((labels, value))

    print("=" * 70)
    print(f"METRICS — {len(counters)} séries")
    print("=" * 70)
    print()

    for name in sorted(by_name.keys()):
        entries = by_name[name]
        # Ordena por valor (top N)
        entries.sort(key=lambda x: -x[1])
        top = entries[:args.top]
        print(f"### {name} (top {len(top)})")
        for labels, value in top:
            label_str = ", ".join(f"{k}={v}" for k, v in sorted(labels.items()))
            print(f"  {value:>10} | {label_str}")
        total = sum(v for _, v in entries)
        print(f"  {'-' * 10}")
        print(f"  {total:>10} | TOTAL ({len(entries)} séries)")
        print()
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """Benchmark de performance."""
    import asyncio

    from src.cip.config import get_settings
    from src.cip.rag.engine import get_engine

    print("=" * 70)
    print(f"BENCHMARK — {args.n} queries")
    print("=" * 70)

    async def run() -> dict[str, Any]:
        eng = get_engine()
        # Warmup
        print("Warmup...")
        await eng.query("AWS Well-Architected", cloud="aws")

        queries = [
            ("Como otimizar custos no AWS?", "aws"),
            ("Boas práticas de FinOps no Azure", "azure"),
            ("Kubernetes security checklist", "gcp"),
            ("S3 bucket encryption", "aws"),
            ("Azure AD best practices", "azure"),
        ]

        latencies: list[float] = []
        print(f"\nRodando {args.n} queries...")
        for i in range(args.n):
            q, c = queries[i % len(queries)]
            t0 = time.perf_counter()
            try:
                await eng.query(q, cloud=c)
                latency_ms = (time.perf_counter() - t0) * 1000
                latencies.append(latency_ms)
                if (i + 1) % 10 == 0:
                    print(f"  {i + 1}/{args.n} queries done")
            except Exception as exc:  # noqa: BLE001
                print(f"  Query {i + 1} failed: {exc}")

        return {
            "n_queries": len(latencies),
            "mean_ms": statistics.mean(latencies) if latencies else 0,
            "median_ms": statistics.median(latencies) if latencies else 0,
            "p95_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
            "p99_ms": sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0,
            "max_ms": max(latencies) if latencies else 0,
            "min_ms": min(latencies) if latencies else 0,
        }

    stats = asyncio.run(run())

    print()
    print("=" * 70)
    print("RESULTADOS")
    print("=" * 70)
    print(f"  Queries executadas: {stats['n_queries']}")
    print(f"  Latência média:      {stats['mean_ms']:.0f}ms")
    print(f"  Latência mediana:    {stats['median_ms']:.0f}ms")
    print(f"  Latência p95:        {stats['p95_ms']:.0f}ms  (SLA: < 5000ms)")
    print(f"  Latência p99:        {stats['p99_ms']:.0f}ms")
    print(f"  Latência min:        {stats['min_ms']:.0f}ms")
    print(f"  Latência max:        {stats['max_ms']:.0f}ms")
    print()

    p95 = stats["p95_ms"]
    if p95 < 5000:
        print(f"[OK] p95 = {p95:.0f}ms < 5000ms SLA")
        return 0
    print(f"[FAIL] p95 = {p95:.0f}ms > 5000ms SLA")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CIP CLI — gerenciar Cloud Intelligence Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcomando")

    # status
    p_status = subparsers.add_parser("status", help="Health check do sistema")

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="Rodar ingestão")
    p_ingest.add_argument("--scope", choices=["mvp", "full"], default="full")
    p_ingest.add_argument("--dry-run", action="store_true")
    p_ingest.add_argument("--resume", action="store_true")

    # eval
    p_eval = subparsers.add_parser("eval", help="Rodar eval suite")
    p_eval.add_argument("--offline", action="store_true")
    p_eval.add_argument("--api", help="URL da API")
    p_eval.add_argument("--report-md", action="store_true")
    p_eval.add_argument("--strict", action="store_true")

    # preflight
    p_preflight = subparsers.add_parser("preflight", help="Pre-flight check")
    p_preflight.add_argument("--skip-tests", action="store_true")

    # drift
    p_drift = subparsers.add_parser("drift", help="Detectar drift na documentação")
    p_drift.add_argument("--scope", choices=["mvp", "full"], default="mvp")

    # audit
    p_audit = subparsers.add_parser("audit", help="Visualizar audit log")
    p_audit.add_argument("--tail", type=int, default=20, help="Últimas N entradas")
    p_audit.add_argument("--tenant", help="Filtrar por tenant")

    # metrics
    p_metrics = subparsers.add_parser("metrics", help="Exibir métricas Prometheus")
    p_metrics.add_argument("--top", type=int, default=10, help="Top N séries por métrica")

    # bench
    p_bench = subparsers.add_parser("bench", help="Benchmark de performance")
    p_bench.add_argument("--n", type=int, default=20, help="Número de queries")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    handlers = {
        "status": cmd_status,
        "ingest": cmd_ingest,
        "eval": cmd_eval,
        "preflight": cmd_preflight,
        "drift": cmd_drift,
        "audit": cmd_audit,
        "metrics": cmd_metrics,
        "bench": cmd_bench,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())