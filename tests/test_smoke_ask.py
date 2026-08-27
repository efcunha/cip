"""Smoke test end-to-end da Fase 1A: 20 perguntas com citação e latência.

Critérios de aceite (do roadmap):
- 20 perguntas respondidas com fonte citada (grounding)
- Latência p95 < 5s
- Zero resposta sem grounding (has_grounding=True em todas)

Mix: AWS=10, GCP=5, Azure=5 (cobre as 3 clouds).
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass

from cip.logging import configure_logging
from cip.rag.engine import get_engine

configure_logging()


@dataclass
class Case:
    cloud: str
    question: str
    expected_min_sources: int = 1


CASES: list[Case] = [
    # AWS (10)
    Case("aws", "Quais são os pilares do AWS Well-Architected Framework?"),
    Case("aws", "Como otimizar custos de instâncias EC2?"),
    Case("aws", "O que é o pilar de Confiabilidade (Reliability Pillar)?"),
    Case("aws", "Como funciona o pilar de Segurança da AWS?"),
    Case("aws", "Quais são as melhores práticas para o pilar de Excelência Operacional?"),
    Case("aws", "O que considerar no pilar de Eficiência de Performance?"),
    Case("aws", "Como o pilar de Sustentabilidade orienta decisões de arquitetura?"),
    Case("aws", "Como usar Savings Plans para reduzir custo de EC2?"),
    Case("aws", "Quais métricas e SLIs são recomendados para workloads resilientes?"),
    Case("aws", "Boas práticas de disaster recovery na AWS"),
    # GCP (5)
    Case("gcp", "Quais são as dimensões do Google Cloud Architecture Framework?"),
    Case("gcp", "Como otimizar custos no Google Cloud?"),
    Case("gcp", "Boas práticas de segurança no GCP"),
    Case("gcp", "Como garantir confiabilidade em sistemas no GCP?"),
    Case("gcp", "Excelência operacional no Google Cloud: princípios"),
    # Azure (5)
    Case("azure", "Quais são os pilares do Azure Well-Architected Framework?"),
    Case("azure", "Como otimizar custos no Azure?"),
    Case("azure", "Boas práticas de segurança no Azure"),
    Case("azure", "Como alcançar alta disponibilidade no Azure?"),
    Case("azure", "Sustentabilidade no Azure: como aplicar?"),
]


async def run() -> None:
    eng = get_engine()
    print(f"{'#':>3} {'CLOUD':<6} {'HIT':<5} {'SRC':>3} {'LAT(ms)':>8}  QUESTION")
    print("-" * 100)

    latencies: list[int] = []
    hits = 0
    total_sources = 0
    failed: list[tuple[int, str]] = []

    for i, case in enumerate(CASES, 1):
        t0 = time.perf_counter()
        result = await eng.query(case.question, cloud=case.cloud)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        latencies.append(latency_ms)

        hit = result.has_grounding
        n_src = len(result.sources)
        if hit:
            hits += 1
            total_sources += n_src
        else:
            failed.append((i, case.question))

        marker = "[OK]" if hit else "[--]"
        q_short = case.question[:60] + ("…" if len(case.question) > 60 else "")
        print(f"{i:>3} {case.cloud:<6} {marker:<5} {n_src:>3} {latency_ms:>8}  {q_short}")

    print("-" * 100)
    print("\n=== RESUMO ===")
    print(f"Total: {len(CASES)} perguntas")
    print(f"Grounded: {hits}/{len(CASES)} ({hits/len(CASES)*100:.1f}%)")
    print(f"Fontes totais recuperadas: {total_sources}")
    print(f"Latência média: {statistics.mean(latencies):.0f}ms")
    print(f"Latência p50: {statistics.median(latencies):.0f}ms")
    p95_idx = int(len(latencies) * 0.95)
    print(f"Latência p95: {sorted(latencies)[p95_idx]:.0f}ms")
    print(f"Latência max: {max(latencies):.0f}ms")

    if failed:
        print(f"\n[!] PERGUNTAS SEM GROUNDING ({len(failed)}):")
        for i, q in failed:
            print(f"  {i}. {q}")

    # Critérios de aceite
    print("\n=== CRITERIOS DE ACEITE FASE 1A ===")
    p95 = sorted(latencies)[p95_idx]
    print(f"[{'OK' if hits == len(CASES) else 'NO'}] 100% grounding: {hits}/{len(CASES)}")
    print(f"[{'OK' if p95 < 5000 else 'NO'}] Latencia p95 < 5s: {p95}ms")
    print(f"[{'OK' if hits == len(CASES) else 'NO'}] Zero resposta sem grounding")


if __name__ == "__main__":
    asyncio.run(run())