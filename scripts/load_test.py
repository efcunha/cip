#!/usr/bin/env python3
"""Load test do CIP API para validar SLA de latência.

Roda N requests concorrentes contra o endpoint /ask e mede:
- Latência p50, p95, p99
- Throughput (req/s)
- Error rate
- Latência por status code

Valida SLAs:
- p95 < 5000ms (MVP)
- error rate < 5%
- throughput > 1 req/s

Uso:
    # Iniciar mock server + API
    python scripts/mock_cloud_server.py &
    python -m cip.api.app &

    # Rodar load test
    python scripts/load_test.py --url http://127.0.0.1:8000 --n 100 --concurrency 10

    # Output JSON para CI
    python scripts/load_test.py --url $API --n 200 --concurrency 20 --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx


@dataclass
class LoadTestResult:
    """Resultado agregado do load test."""

    n_requests: int
    n_successful: int = 0
    n_failed: int = 0
    duration_s: float = 0.0
    throughput_rps: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)
    status_codes: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        return self.n_failed / self.n_requests if self.n_requests else 0.0

    @property
    def p50(self) -> float:
        return self._percentile(50)

    @property
    def p95(self) -> float:
        return self._percentile(95)

    @property
    def p99(self) -> float:
        return self._percentile(99)

    def _percentile(self, p: int) -> float:
        if not self.latencies_ms:
            return 0.0
        return sorted(self.latencies_ms)[int(len(self.latencies_ms) * p / 100)]


# ─────────────────────────────────────────────────────────────────────────
# Queries (variação para simular uso real)
# ─────────────────────────────────────────────────────────────────────────

QUERIES: list[dict[str, str]] = [
    {"question": "Como otimizar custos de EC2?", "cloud": "aws"},
    {"question": "O que é AWS Well-Architected?", "cloud": "aws"},
    {"question": "Como funciona o Azure Advisor?", "cloud": "azure"},
    {"question": "Boas práticas de FinOps no GCP", "cloud": "gcp"},
    {"question": "Como configurar Savings Plans?", "cloud": "aws"},
    {"question": "Kubernetes security checklist", "cloud": "gcp"},
    {"question": "Azure AD best practices", "cloud": "azure"},
    {"question": "S3 bucket encryption", "cloud": "aws"},
]


async def _make_request(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, str],
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, float, str | None]:
    """Faz uma request e retorna (status, latency_ms, error)."""
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{url}/ask",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        return resp.status_code, latency_ms, None
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t0) * 1000
        return 0, latency_ms, str(exc)[:200]


async def _run_load(
    url: str,
    n: int,
    concurrency: int,
    api_key: str | None,
    tenant_id: str | None,
    timeout: float,
) -> LoadTestResult:
    """Roda load test."""
    result = LoadTestResult(n_requests=n)
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    if tenant_id:
        headers["X-Tenant-Id"] = tenant_id

    async with httpx.AsyncClient() as client:
        # Warmup
        for _ in range(min(3, n)):
            await _make_request(client, url, QUERIES[0], headers, timeout)

        t0 = time.perf_counter()
        sem = asyncio.Semaphore(concurrency)

        async def task(i: int) -> None:
            async with sem:
                payload = QUERIES[i % len(QUERIES)]
                status, latency_ms, error = await _make_request(
                    client, url, payload, headers, timeout
                )
                result.latencies_ms.append(latency_ms)
                result.status_codes[status] = result.status_codes.get(status, 0) + 1
                if 200 <= status < 400:
                    result.n_successful += 1
                else:
                    result.n_failed += 1
                    if error:
                        if len(result.errors) < 5:  # sample errors
                            result.errors.append(error)

        await asyncio.gather(*[task(i) for i in range(n)])
        result.duration_s = time.perf_counter() - t0

    result.throughput_rps = n / result.duration_s if result.duration_s > 0 else 0
    return result


def print_report(result: LoadTestResult, sla_p95_ms: int) -> int:
    """Imprime relatório legível. Retorna exit code."""
    print("=" * 70)
    print("LOAD TEST RESULTS")
    print("=" * 70)
    print(f"  Total requests:     {result.n_requests}")
    print(f"  Successful (2xx):    {result.n_successful}")
    print(f"  Failed:             {result.n_failed}")
    print(f"  Error rate:         {result.error_rate:.2%}")
    print(f"  Duration:           {result.duration_s:.2f}s")
    print(f"  Throughput:         {result.throughput_rps:.1f} req/s")
    print()
    print(f"  Latency p50:        {result.p50:.0f}ms")
    print(f"  Latency p95:        {result.p95:.0f}ms  (SLA: < {sla_p95_ms}ms)")
    print(f"  Latency p99:        {result.p99:.0f}ms")
    if result.latencies_ms:
        print(f"  Latency min:        {min(result.latencies_ms):.0f}ms")
        print(f"  Latency max:        {max(result.latencies_ms):.0f}ms")
    print()
    print(f"  Status codes:       {dict(sorted(result.status_codes.items()))}")

    if result.errors:
        print()
        print(f"  Sample errors (first 5):")
        for e in result.errors[:5]:
            print(f"    - {e}")

    # Verifica SLAs
    print()
    print("=" * 70)
    print("SLA CHECK")
    print("=" * 70)
    pass_sla = True
    if result.p95 < sla_p95_ms:
        print(f"  [OK]   p95 = {result.p95:.0f}ms < {sla_p95_ms}ms")
    else:
        print(f"  [FAIL] p95 = {result.p95:.0f}ms > {sla_p95_ms}ms")
        pass_sla = False
    if result.error_rate < 0.05:
        print(f"  [OK]   error rate = {result.error_rate:.2%} < 5%")
    else:
        print(f"  [FAIL] error rate = {result.error_rate:.2%} >= 5%")
        pass_sla = False
    if result.throughput_rps > 1.0:
        print(f"  [OK]   throughput = {result.throughput_rps:.1f} req/s > 1 req/s")
    else:
        print(f"  [WARN] throughput = {result.throughput_rps:.1f} req/s (low)")

    return 0 if pass_sla else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test CIP API")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="API URL")
    parser.add_argument("--n", type=int, default=100, help="Total requests")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent requests")
    parser.add_argument("--api-key", help="X-API-Key header (se auth habilitada)")
    parser.add_argument("--tenant-id", help="X-Tenant-Id header")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout (s)")
    parser.add_argument("--sla-p95-ms", type=int, default=5000, help="SLA para p95")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    result = asyncio.run(
        _run_load(
            url=args.url,
            n=args.n,
            concurrency=args.concurrency,
            api_key=args.api_key,
            tenant_id=args.tenant_id,
            timeout=args.timeout,
        )
    )

    if args.json:
        # Remove latencies list do JSON (pode ser enorme)
        out = asdict(result)
        out["latencies_ms"] = out["latencies_ms"][:100] + (["...truncated..."] if len(result.latencies_ms) > 100 else [])
        out["latencies_count"] = len(result.latencies_ms)
        out["p50_ms"] = result.p50
        out["p95_ms"] = result.p95
        out["p99_ms"] = result.p99
        out["error_rate"] = result.error_rate
        out["sla_passed"] = result.p95 < args.sla_p95_ms and result.error_rate < 0.05
        print(json.dumps(out, indent=2, default=str))
        return 0 if out["sla_passed"] else 1

    return print_report(result, args.sla_p95_ms)


if __name__ == "__main__":
    sys.exit(main())