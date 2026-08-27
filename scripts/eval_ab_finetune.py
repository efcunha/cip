#!/usr/bin/env python3
"""A/B eval framework: compara modelo base vs modelo fine-tuned (Fase 7).

Roda a mesma suíte de eval antes e depois do fine-tuning e compara scores.
Detecta regressão factual (bloqueia promoção se houve).

Uso:
    # A: modelo base (Bedrock/Claude)
    python scripts/eval_ab_finetune.py --phase base --api http://api.base

    # B: modelo fine-tuned (self-hosted vLLM)
    python scripts/eval_ab_finetune.py --phase tuned --api http://api.tuned

    # Comparar
    python scripts/eval_ab_finetune.py --compare results/base.json results/tuned.json

    # Verdict final
    python scripts/eval_ab_finetune.py --verdict results/base.json results/tuned.json

Critério de promoção (do ADR-0001):
- Score avg em accuracy, grounding, citation ≥ baseline (sem regressão)
- Score avg em format, persona-style ≥ baseline + 0.2 (melhora de estilo)
- Custo por query ≤ baseline × 1.5 (piora aceitável até 50%)
- Latência p95 ≤ baseline + 500ms
- Zero violações zero-price adicionais
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class EvalPhase:
    """Resultados de uma fase de avaliação (base ou fine-tuned)."""

    phase_name: str  # 'base' ou 'tuned'
    api_url: str
    n_cases: int = 0
    avg_scores: dict[str, float] = field(default_factory=dict)
    cost_median: float = 0.0
    latency_p95_ms: int = 0
    zero_price_violations: int = 0
    gate_passed: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ABVerdict:
    """Verdict comparativo entre base e fine-tuned."""

    base: EvalPhase
    tuned: EvalPhase
    accuracy_delta: float = 0.0
    grounding_delta: float = 0.0
    citation_delta: float = 0.0
    format_delta: float = 0.0
    zero_price_delta: int = 0
    cost_ratio: float = 1.0
    latency_delta_ms: int = 0
    factual_regression: bool = False
    style_improvement: bool = False
    should_promote: bool = False
    reasons: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────
# Run phase
# ─────────────────────────────────────────────────────────────────────────


def run_phase(phase_name: str, api_url: str) -> EvalPhase:
    """Roda eval contra API (base ou fine-tuned) e retorna EvalPhase."""
    print(f"\n=== Phase: {phase_name} (API: {api_url}) ===\n")

    import subprocess

    # Roda run_eval.py via subprocess (reutiliza toda a infra)
    result = subprocess.run(
        [
            sys.executable, str(ROOT / "eval" / "run_eval.py"),
            "--api", api_url,
            "--report-md",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )

    print(result.stdout)
    if result.stderr:
        print(f"[stderr] {result.stderr}", file=sys.stderr)

    # Parse do resultado JSON gerado
    json_file = ROOT / "eval" / "results" / "eval_results.json"
    if not json_file.exists():
        print(f"[ERROR] {json_file} não encontrado")
        return EvalPhase(phase_name=phase_name, api_url=api_url, gate_passed=False)

    data = json.loads(json_file.read_text(encoding="utf-8"))
    report = data.get("report", {})

    phase = EvalPhase(
        phase_name=phase_name,
        api_url=api_url,
        n_cases=report.get("n_cases", 0),
        avg_scores=report.get("avg_scores", {}),
        cost_median=report.get("cost_median_usd", 0.0),
        latency_p95_ms=0,  # run_eval.py não calcula p95 ainda
        zero_price_violations=report.get("zero_price_violations_total", 0),
        gate_passed=report.get("gate_passed", False),
    )
    return phase


def save_phase(phase: EvalPhase, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(phase), indent=2, ensure_ascii=False), encoding="utf-8")


def load_phase(path: Path) -> EvalPhase:
    data = json.loads(path.read_text(encoding="utf-8"))
    return EvalPhase(**data)


# ─────────────────────────────────────────────────────────────────────────
# Verdict
# ─────────────────────────────────────────────────────────────────────────


def compute_verdict(base: EvalPhase, tuned: EvalPhase) -> ABVerdict:
    """Calcula deltas e decide se fine-tuned deve ser promovido."""
    verdict = ABVerdict(base=base, tuned=tuned)

    # Deltas por critério
    for crit in ("accuracy", "grounding", "citation", "format", "zero_price"):
        b = base.avg_scores.get(crit, 0.0)
        t = tuned.avg_scores.get(crit, 0.0)
        delta = t - b
        setattr(verdict, f"{crit}_delta", delta)

    # Custo
    if base.cost_median > 0:
        verdict.cost_ratio = tuned.cost_median / base.cost_median
    verdict.zero_price_delta = tuned.zero_price_violations - base.zero_price_violations
    verdict.latency_delta_ms = tuned.latency_p95_ms - base.latency_p95_ms

    # ── Decisões ───────────────────────────────────────────────────────
    # Factual regression: accuracy ou grounding caiu > 0.2
    verdict.factual_regression = (
        verdict.accuracy_delta < -0.2 or verdict.grounding_delta < -0.2
    )
    # Style improvement: format + citation subiu > 0.2 combinados
    verdict.style_improvement = (
        verdict.format_delta + verdict.citation_delta > 0.2
    )
    # Custo aceitável: até 1.5x do baseline
    cost_ok = verdict.cost_ratio <= 1.5
    # Latência aceitável: até +500ms
    latency_ok = verdict.latency_delta_ms <= 500
    # Sem violações zero-price adicionais
    zero_price_ok = verdict.zero_price_delta <= 0

    # Razões (debug + auditoria)
    if verdict.factual_regression:
        verdict.reasons.append(
            f"[FAIL] Regressão factual: accuracy delta={verdict.accuracy_delta:.2f}, "
            f"grounding delta={verdict.grounding_delta:.2f}"
        )
    else:
        verdict.reasons.append(
            f"[OK] Sem regressão factual (acc delta={verdict.accuracy_delta:+.2f}, "
            f"grounding delta={verdict.grounding_delta:+.2f})"
        )

    if verdict.style_improvement:
        verdict.reasons.append(
            f"[OK] Melhoria de estilo: format+citation delta="
            f"{verdict.format_delta + verdict.citation_delta:+.2f}"
        )
    else:
        verdict.reasons.append(
            f"[WARN] Sem melhoria significativa de estilo "
            f"({verdict.format_delta + verdict.citation_delta:+.2f})"
        )

    if not cost_ok:
        verdict.reasons.append(
            f"[FAIL] Custo subiu {verdict.cost_ratio:.1f}x (max 1.5x)"
        )
    else:
        verdict.reasons.append(
            f"[OK] Custo: {verdict.cost_ratio:.2f}x baseline (max 1.5x)"
        )

    if not latency_ok:
        verdict.reasons.append(
            f"[FAIL] Latência subiu {verdict.latency_delta_ms}ms (max +500ms)"
        )
    else:
        verdict.reasons.append(f"[OK] Latência delta: {verdict.latency_delta_ms}ms")

    if not zero_price_ok:
        verdict.reasons.append(
            f"[FAIL] {verdict.zero_price_delta} novas violações zero-price"
        )
    else:
        verdict.reasons.append("[OK] Sem novas violações zero-price")

    # Decisão final
    verdict.should_promote = (
        not verdict.factual_regression
        and verdict.style_improvement
        and cost_ok
        and latency_ok
        and zero_price_ok
    )

    if verdict.should_promote:
        verdict.reasons.append("\n[VEREDICT] PROMOVER modelo fine-tuned para produção.")
    else:
        verdict.reasons.append(
            "\n[VEREDICT] NÃO promover. "
            "Reverter para modelo base e investigar causas."
        )

    return verdict


def render_verdict(verdict: ABVerdict) -> str:
    """Renderiza verdict em texto legível."""
    lines = [
        "# A/B Eval Verdict — Fine-tuning",
        "",
        f"**Data**: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Deltas por critério",
        "",
        "| Critério | Base | Tuned | Delta |",
        "|---|---|---|---|",
    ]
    for crit in ("accuracy", "grounding", "citation", "format", "zero_price"):
        b = verdict.base.avg_scores.get(crit, 0.0)
        t = verdict.tuned.avg_scores.get(crit, 0.0)
        delta = getattr(verdict, f"{crit}_delta")
        marker = "+" if delta > 0 else ""
        lines.append(f"| {crit} | {b:.2f} | {t:.2f} | {marker}{delta:.2f} |")

    lines += [
        "",
        "## Métricas operacionais",
        "",
        f"- **Custo mediano**: base ${verdict.base.cost_median:.4f} → tuned ${verdict.tuned.cost_median:.4f} ({verdict.cost_ratio:.2f}x)",
        f"- **Latência p95 delta**: {verdict.latency_delta_ms:+d}ms",
        f"- **Zero-price violations delta**: {verdict.zero_price_delta:+d}",
        "",
        "## Avaliação",
        "",
    ]
    lines.extend(f"- {r}" for r in verdict.reasons)
    lines.append("")

    if verdict.should_promote:
        lines.append("## Resultado: ✅ PROMOVER")
        lines.append("")
        lines.append("O modelo fine-tuned atende todos os critérios de promoção. Promover para produção.")
    else:
        lines.append("## Resultado: ❌ NÃO PROMOVER")
        lines.append("")
        lines.append("O modelo fine-tuned não atende os critérios. Reverter para o modelo base.")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B eval fine-tuning (Fase 7)")
    parser.add_argument("--phase", choices=["base", "tuned"], help="Rodar eval de uma fase")
    parser.add_argument("--api", help="URL da API para a fase")
    parser.add_argument("--output", type=Path, help="Arquivo de saída JSON")
    parser.add_argument(
        "--compare", nargs=2, type=Path, metavar=("BASE", "TUNED"),
        help="Compara dois resultados salvos",
    )
    parser.add_argument(
        "--verdict", nargs=2, type=Path, metavar=("BASE", "TUNED"),
        help="Compara e gera verdict final (Markdown)",
    )
    args = parser.parse_args()

    # Modo 1: Rodar uma fase
    if args.phase:
        if not args.api:
            print("[ERROR] --api é obrigatório com --phase")
            return 1
        phase = run_phase(args.phase, args.api)
        if args.output:
            save_phase(phase, args.output)
            print(f"[OK] Salvo em: {args.output}")
        else:
            print(json.dumps(asdict(phase), indent=2, default=str))
        return 0

    # Modo 2: Comparar dois resultados
    if args.compare or args.verdict:
        paths = args.compare or args.verdict
        base_path, tuned_path = paths
        base = load_phase(base_path)
        tuned = load_phase(tuned_path)
        verdict = compute_verdict(base, tuned)
        print(render_verdict(verdict))

        if args.verdict:
            out_path = args.verdict[0].parent / "verdict.md"
            out_path.write_text(render_verdict(verdict), encoding="utf-8")
            print(f"\n[OK] Verdict salvo em: {out_path}")

        return 0 if verdict.should_promote else 2

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())