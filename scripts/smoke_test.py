#!/usr/bin/env python3
"""Smoke test end-to-end do CIP.

Roda contra uma stack CIP já em execução (URL configurável) e valida
todos os endpoints + fluxos críticos.

Uso:
    # Contra API local (make up)
    python scripts/smoke_test.py --url http://localhost:8000

    # Contra homolog
    python scripts/smoke_test.py --url https://homolog.cip.internal

    # Com API key
    python scripts/smoke_test.py --url http://localhost:8000 --api-key xxx

    # Verbose
    python scripts/smoke_test.py --url http://localhost:8000 --verbose

Exit codes:
    0 = TODOS os testes passaram
    1 = algum teste falhou
    2 = erro de conexão (API não está rodando)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any

import httpx


# ─────────────────────────────────────────────────────────────────────────
# Testes individuais
# ─────────────────────────────────────────────────────────────────────────


async def test_health(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """GET /health — deve retornar status ok."""
    resp = await client.get(f"{url}/health", timeout=5.0)
    resp.raise_for_status()
    data = resp.json()
    assert data.get("status") == "ok", f"Status não é 'ok': {data}"
    return data


async def test_health_live(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """GET /health/live — k8s liveness probe."""
    resp = await client.get(f"{url}/health/live", timeout=5.0)
    resp.raise_for_status()
    data = resp.json()
    assert data.get("status") == "alive", f"Liveness não é 'alive': {data}"
    return data


async def test_health_ready(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """GET /health/ready — k8s readiness probe (DB, vector, etc)."""
    resp = await client.get(f"{url}/health/ready", timeout=10.0)
    if resp.status_code == 503:
        raise AssertionError(
            f"Readiness failed (503): {resp.json()} — DB/LLM/vector store podem estar down"
        )
    resp.raise_for_status()
    data = resp.json()
    return data


async def test_metrics(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """GET /metrics — formato Prometheus."""
    resp = await client.get(f"{url}/metrics", timeout=5.0)
    resp.raise_for_status()
    text = resp.text
    # Procura por métricas-chave
    assert "cip_requests_total" in text or "cip_" in text, "Métricas CIP não encontradas"
    return {"lines": len(text.splitlines()), "has_cip_metrics": "cip_" in text}


async def test_ask_simple(client: httpx.AsyncClient, url: str, headers: dict) -> dict[str, Any]:
    """POST /ask — pergunta básica sobre AWS."""
    payload = {
        "question": "Quais são os 6 pilares do AWS Well-Architected?",
        "cloud": "aws",
    }
    resp = await client.post(f"{url}/ask", json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    assert "answer" in data, "Campo 'answer' ausente"
    assert data.get("has_grounding") is True, "Resposta sem grounding"
    assert len(data.get("sources", [])) > 0, "Sem sources"
    return {
        "answer_length": len(data["answer"]),
        "n_sources": len(data["sources"]),
        "grounding": data["has_grounding"],
    }


async def test_ask_with_grounding(client: httpx.AsyncClient, url: str, headers: dict) -> dict[str, Any]:
    """POST /ask — verifica que cita fontes oficiais."""
    payload = {
        "question": "O que é o AWS Lambda?",
        "cloud": "aws",
    }
    resp = await client.post(f"{url}/ask", json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    # Verifica que há pelo menos uma source com URL
    sources = data.get("sources", [])
    has_url = any(s.get("url") for s in sources)
    assert has_url, "Nenhuma source tem URL"
    return {"n_sources": len(sources), "has_url": has_url}


async def test_analyze_iac(client: httpx.AsyncClient, url: str, headers: dict) -> dict[str, Any]:
    """POST /analyze — Terraform inseguro."""
    payload = {
        "question": "Revise este Terraform",
        "cloud": "aws",
        "iac_payload": '''\
resource "aws_s3_bucket" "data" {
  bucket = "data"
}
resource "aws_security_group" "web" {
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
''',
    }
    resp = await client.post(f"{url}/analyze", json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    findings = data.get("findings", [])
    assert len(findings) > 0, "Inspection Engine não detectou findings"
    # Espera pelo menos 1 critical (SG aberto) ou 1 high (S3 sem encryption)
    severities = {f.get("severity") for f in findings}
    assert "critical" in severities or "high" in severities, \
        f"Esperava severity high/critical, achou {severities}"
    return {
        "n_findings": len(findings),
        "severities": list(severities),
        "intent": data.get("intent"),
    }


async def test_streaming_ask(client: httpx.AsyncClient, url: str, headers: dict) -> dict[str, Any]:
    """POST /ask/stream — Server-Sent Events."""
    payload = {
        "question": "Resposta curta",
        "cloud": "aws",
    }
    events: list[dict[str, Any]] = []
    chunk_count = 0
    has_done = False

    async with client.stream(
        "POST", f"{url}/ask/stream", json=payload, headers=headers, timeout=30.0
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
                events.append({"type": event_type})
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
                if events and events[-1]["type"] == "chunk":
                    chunk_count += 1
                if events and events[-1]["type"] == "done":
                    has_done = True
                    try:
                        events[-1]["data"] = json.loads(data)
                    except json.JSONDecodeError:
                        pass

    assert chunk_count > 0, "Nenhum chunk recebido"
    assert has_done, "Evento 'done' ausente"
    assert any(e["type"] == "chunk" for e in events), "Sem evento 'chunk'"
    return {"n_chunks": chunk_count, "has_done": has_done}


# ─────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────


TESTS = [
    ("Health (público)", test_health, "simple"),
    ("Liveness probe", test_health_live, "simple"),
    ("Readiness probe", test_health_ready, "simple"),
    ("Métricas Prometheus", test_metrics, "simple"),
    ("Ask: AWS Well-Architected", test_ask_simple, "auth"),
    ("Ask: grounding com URL", test_ask_with_grounding, "auth"),
    ("Analyze: Terraform inseguro", test_analyze_iac, "auth"),
    ("Streaming (SSE)", test_streaming_ask, "auth"),
]


async def run_all(args: argparse.Namespace) -> int:
    """Roda todos os smoke tests."""
    url = args.url.rstrip("/")
    headers: dict[str, str] = {}
    if args.api_key:
        headers["X-API-Key"] = args.api_key
    if args.tenant_id:
        headers["X-Tenant-Id"] = args.tenant_id

    print("=" * 70)
    print(f"  CIP SMOKE TEST — {url}")
    print("=" * 70)
    print()

    passed = 0
    failed = 0
    skipped = 0
    start = time.perf_counter()

    async with httpx.AsyncClient() as client:
        for name, test_fn, required in TESTS:
            if required == "auth" and not args.api_key:
                # Sem API key: pula os que precisam
                print(f"  [SKIP] {name} (precisa --api-key)")
                skipped += 1
                continue
            t0 = time.perf_counter()
            try:
                if required == "auth":
                    result = await test_fn(client, url, headers)
                else:
                    result = await test_fn(client, url)
                latency = (time.perf_counter() - t0) * 1000
                if args.verbose:
                    print(f"  [PASS] {name:<40} ({latency:>6.0f}ms)  {result}")
                else:
                    print(f"  [PASS] {name:<40} ({latency:>6.0f}ms)")
                passed += 1
            except httpx.ConnectError as exc:
                print(f"  [FAIL] {name:<40} CONNECTION ERROR: {exc}")
                print(f"         Verifique se a API está rodando em {url}")
                failed += 1
                # Se primeira conexão falhou, não adianta continuar
                if passed == 0 and failed == 1:
                    print("\n[ABORT] API não está acessível. Inicie com: make up")
                    return 2
            except AssertionError as exc:
                print(f"  [FAIL] {name:<40} {exc}")
                failed += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  [FAIL] {name:<40} ERROR: {exc}")
                failed += 1

    total_ms = (time.perf_counter() - start) * 1000
    print()
    print("=" * 70)
    print(f"  RESULT: {passed} passed | {failed} failed | {skipped} skipped | {total_ms:.0f}ms total")
    print("=" * 70)

    if failed == 0:
        print("\n[OK] TODOS os smoke tests passaram!")
        return 0
    print(f"\n[FAIL] {failed} teste(s) falharam")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test end-to-end do CIP (validação rápida de homologação)"
    )
    parser.add_argument(
        "--url", default="http://localhost:8000",
        help="URL base da API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key", help="X-API-Key header (se auth habilitada)",
    )
    parser.add_argument(
        "--tenant-id", default="default",
        help="X-Tenant-Id header (default: default)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Mostra detalhes de cada teste",
    )
    args = parser.parse_args()

    return asyncio.run(run_all(args))


if __name__ == "__main__":
    sys.exit(main())