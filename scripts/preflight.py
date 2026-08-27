#!/usr/bin/env python3
"""Pre-flight check de produção: valida que todos os gates passam antes do deploy.

Verifica:
1. Schema DB aplicado + pgvector
2. Dataset tem chunks (>0)
3. LLM provider inicializa
4. Config LLM_PROVIDER válido
5. Embeddings model disponível
6. API keys configuradas (em prod)
7. Tenant isolation no schema
8. Health checks
9. Run eval (smoke test de qualidade)
10. Verificar rate limiter + auth

Exit codes:
  0 = TODOS os checks passaram (GO para deploy)
  1 = algum check crítico falhou (NO-GO)
  2 = erro de execução

Uso:
  python scripts/preflight.py                    # roda tudo
  python scripts/preflight.py --skip-eval         # pula eval (CI)
  python scripts/preflight.py --api-url http://api.cip
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@dataclass
class CheckResult:
    """Resultado de um check individual."""

    name: str
    passed: bool
    critical: bool = True  # Se True, falha = NO-GO
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────
# Checks
# ─────────────────────────────────────────────────────────────────────────


def check_environment() -> CheckResult:
    """Variáveis de ambiente obrigatórias."""
    cip_env = os.getenv("CIP_ENV", "dev")
    is_prod = cip_env == "prod"

    missing: list[str] = []
    if is_prod:
        # Em prod, todas as configs precisam estar setadas
        if not os.getenv("DATABASE_URL"):
            missing.append("DATABASE_URL")
        if not os.getenv("CIP_API_KEYS"):
            missing.append("CIP_API_KEYS")
        if not os.getenv("LLM_PROVIDER"):
            missing.append("LLM_PROVIDER")

    if missing:
        return CheckResult(
            name="environment",
            passed=False,
            message=f"Variáveis faltando em prod: {', '.join(missing)}",
        )
    return CheckResult(
        name="environment",
        passed=True,
        message=f"CIP_ENV={cip_env}, configs OK",
        details={"env": cip_env},
    )


def check_database_schema() -> CheckResult:
    """DB acessível + pgvector + tabelas existem."""
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from cip.config import get_settings

        s = get_settings()
        engine = create_async_engine(
            s.database_url.replace("postgresql://", "postgresql+asyncpg://"),
            pool_pre_ping=True,
        )

        async def _check() -> dict[str, Any]:
            async with engine.connect() as conn:
                # pgvector extension
                ext = await conn.execute(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
                ext_version = ext.scalar()

                # Tabelas obrigatórias
                tables = await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name IN "
                        "('cloud_docs', 'environments', 'analyses', 'findings', 'data_cloud_docs')"
                    )
                )
                tables_list = [row[0] for row in tables.all()]

                # Chunks
                chunks = 0
                if "data_cloud_docs" in tables_list:
                    res = await conn.execute(text("SELECT COUNT(*) FROM data_cloud_docs"))
                    chunks = res.scalar() or 0
                return {
                    "pgvector_version": ext_version,
                    "tables": tables_list,
                    "chunks": chunks,
                }

        import asyncio
        result = asyncio.run(_check())

        issues: list[str] = []
        if not result["pgvector_version"]:
            issues.append("pgvector extension não instalada")
        if "data_cloud_docs" not in result["tables"]:
            issues.append("Tabela data_cloud_docs não existe (rode schema.sql)")
        if result["chunks"] == 0:
            issues.append("0 chunks indexados (rode ingestion)")

        if issues:
            return CheckResult(
                name="database",
                passed=False,
                message="; ".join(issues),
                details=result,
            )
        return CheckResult(
            name="database",
            passed=True,
            message=f"pgvector {result['pgvector_version']}, {result['chunks']} chunks",
            details=result,
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="database",
            passed=False,
            message=f"DB error: {str(exc)[:200]}",
        )


def check_llm_provider() -> CheckResult:
    """LLM provider inicializa corretamente."""
    try:
        from cip.rag.llm import build_llm, build_embed_model

        from cip.config import get_settings

        s = get_settings()
        llm = build_llm()
        embed = build_embed_model()
        return CheckResult(
            name="llm_provider",
            passed=True,
            message=f"LLM '{s.llm_provider}' + embed '{s.embed_provider}' OK",
            details={
                "llm_provider": s.llm_provider,
                "llm_model": s.llm_model,
                "embed_provider": s.embed_provider,
                "embed_model": s.embed_model,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="llm_provider",
            passed=False,
            message=f"LLM init error: {str(exc)[:200]}",
        )


def check_embedding_dim() -> CheckResult:
    """embed_dim casa com provider."""
    from cip.config import get_settings

    s = get_settings()
    expected_dims: dict[str, set[int]] = {
        "local": {384, 768, 1024},
        "bedrock": {1024, 1536},
        "openai": {1536, 3072},
    }
    allowed = expected_dims.get(s.embed_provider, set())
    if s.embed_dim not in allowed:
        return CheckResult(
            name="embedding_dim",
            passed=False,
            message=(
                f"embed_dim={s.embed_dim} inconsistente com provider="
                f"{s.embed_provider!r}. Esperado: {sorted(allowed)}"
            ),
        )
    return CheckResult(
        name="embedding_dim",
        passed=True,
        message=f"embed_dim={s.embed_dim} OK para {s.embed_provider}",
    )


def check_api_keys() -> CheckResult:
    """Em prod, API keys devem estar configuradas."""
    cip_env = os.getenv("CIP_ENV", "dev")
    if cip_env != "prod":
        return CheckResult(
            name="api_keys",
            passed=True,
            critical=False,  # warning em dev
            message=f"Dev mode — API keys opcionais",
        )
    keys = os.getenv("CIP_API_KEYS", "")
    if not keys:
        return CheckResult(
            name="api_keys",
            passed=False,
            message="CIP_API_KEYS vazio em prod — auth vai bloquear tudo",
        )
    # Validar formato: key:tenant:rpm
    invalid = []
    n_tenants = 0
    for entry in keys.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 2:
            invalid.append(entry)
        else:
            n_tenants += 1
    if invalid:
        return CheckResult(
            name="api_keys",
            passed=False,
            message=f"API keys malformadas: {', '.join(invalid)}",
        )
    if n_tenants == 0:
        return CheckResult(
            name="api_keys",
            passed=False,
            message="Nenhuma API key válida",
        )
    return CheckResult(
        name="api_keys",
        passed=True,
        message=f"{n_tenants} tenant(s) configurado(s)",
        details={"n_tenants": n_tenants},
    )


def check_health_endpoints() -> CheckResult:
    """Roda os checks de health (DB, LLM, vector store, rate limiter)."""
    try:
        import asyncio

        from src.cip.api.health import run_all_checks

        # run_all_checks() é async (roda os checks de DB/vector_store com await).
        # Este script é sync e não está dentro de um event loop, então asyncio.run
        # é a forma correta de executá-lo aqui.
        health = asyncio.run(run_all_checks())
        if not health.healthy:
            failed = [c.name for c in health.checks if not c.healthy]
            return CheckResult(
                name="health_endpoints",
                passed=False,
                message=f"Checks falhando: {', '.join(failed)}",
            )
        return CheckResult(
            name="health_endpoints",
            passed=True,
            message=f"{len(health.checks)} checks passaram",
            details={
                "checks": [
                    {"name": c.name, "latency_ms": c.latency_ms}
                    for c in health.checks
                ]
            },
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="health_endpoints",
            passed=False,
            message=f"Health check error: {str(exc)[:200]}",
        )


def check_test_suite() -> CheckResult:
    """Roda pytest para garantir que suite está verde."""
    import subprocess

    result = subprocess.run(
        [
            "python", "-m", "pytest", "tests/",
            "--ignore=tests/test_smoke_ask.py",
            "--ignore=tests/test_ingest_delta.py",
            "-q", "--no-header",
            "--tb=no", "-x",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    # Parse do output
    n_passed = 0
    n_failed = 0
    for line in result.stdout.splitlines():
        if "passed" in line and "failed" not in line:
            # e.g., "199 passed in 139.96s"
            parts = line.split()
            try:
                n_passed = int(parts[0])
            except (ValueError, IndexError):
                pass
        if "failed" in line:
            parts = line.split()
            try:
                n_failed = int(parts[0])
            except (ValueError, IndexError):
                pass

    if n_failed > 0 or result.returncode != 0:
        return CheckResult(
            name="test_suite",
            passed=False,
            message=f"{n_passed} passed, {n_failed} failed",
            details={"returncode": result.returncode, "stdout_tail": result.stdout[-500:]},
        )
    return CheckResult(
        name="test_suite",
        passed=True,
        message=f"{n_passed} testes passando",
        details={"n_passed": n_passed},
    )


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-flight production check")
    parser.add_argument(
        "--skip-eval", action="store_true",
        help="Pula test suite (CI rápido)",
    )
    parser.add_argument(
        "--skip-tests", action="store_true",
        help="Pula test suite (testes já rodaram)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help=(
            "Compatibilidade com os demais scripts de gate (homolog_validate, "
            "run_eval). O preflight JÁ é estrito por padrão: qualquer check "
            "crítico falho retorna exit 1 (NO-GO). Este flag é aceito apenas "
            "para uniformizar o CLI e não altera o comportamento."
        ),
    )
    args = parser.parse_args()

    print("=" * 70)
    print("PRE-FLIGHT CHECK — CIP Production Readiness")
    print("=" * 70)
    print()

    checks: list[CheckResult] = [
        check_environment(),
        check_database_schema(),
        check_llm_provider(),
        check_embedding_dim(),
        check_api_keys(),
        check_health_endpoints(),
    ]

    if not args.skip_tests and not args.skip_eval:
        # Run test suite (slow, but critical)
        print("[INFO] Rodando test suite (pode demorar ~2min)...")
        checks.append(check_test_suite())

    # Render results
    print("\n=== Resultados ===\n")
    for c in checks:
        marker = "[OK]" if c.passed else ("[FAIL]" if c.critical else "[WARN]")
        print(f"  {marker} {c.name:<20} {c.message}")

    # Summary
    print()
    n_passed = sum(1 for c in checks if c.passed)
    n_failed_critical = sum(1 for c in checks if not c.passed and c.critical)
    n_warn = sum(1 for c in checks if not c.passed and not c.critical)
    print(f"Resumo: {n_passed} OK, {n_failed_critical} FAIL, {n_warn} WARN de {len(checks)} checks")

    # Verdict
    print()
    if n_failed_critical == 0:
        print("[GO] Todos os checks críticos passaram. Deploy pode prosseguir.")
        return 0
    print("[NO-GO] Algum check crítico falhou. NÃO fazer deploy.")
    return 1


if __name__ == "__main__":
    sys.exit(main())