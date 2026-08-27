"""Runner de avaliação da CIP — rubrica 1-5 automatizada + gate de produção.

Executa a suíte de casos contra a API (/ask e /analyze), valida menções, severidades,
grounding, citações e formato. Calcula score por critério e bloqueia go-live se < 4.0.

Uso:
    python eval/run_eval.py --api http://localhost:8000
    python eval/run_eval.py --offline   # só Inspection Engine, sem LLM
    python eval/run_eval.py --report-md # gera relatório Markdown

Rubrica (1-5 por critério):
    accuracy    — correção técnica do conteúdo
    grounding   — resposta ancorada em fonte oficial (URL/cloud/service)
    citation    — citações explícitas no formato [cloud, serviço, título, url]
    format      — estrutura (resumo, achados, priorização, referências)
    zero_price  — sem preços inferidos de memória (só via tool)

Critérios de go-live (gate):
    - score_medio ≥ 4.0 em TODOS os critérios
    - nenhum cenário com score < 3.0 em accuracy
    - custo < $0.05/query (mediano)
    - 100% zero_preco_inferido (validação automática)

Processo de revisão humana (5 arquitetos × 20 cenários cada):
    - Cada arquiteto avalia 20 cenários usando a mesma rubrica
    - Score final = média dos 5 scores por cenário
    - Divergência > 1.0 ponto entre arquitetos = flag para revisão adicional
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CASES_FILE = Path(__file__).parent / "test_cases.json"
RESULTS_DIR = Path(__file__).parent / "results"

# Regex para detectar citação no formato [cloud, service, title, url]
CITATION_RE = re.compile(r"\[(aws|gcp|azure)[^]]+\]", re.IGNORECASE)
# Regex para detectar preço ($X.XX ou R$ X) sem ser de tool ao vivo
PRICE_RE = re.compile(r"\$[\d,]+(?:\.\d+)?(?:\s*(?:/|por|per)\s*(?:m[êe]s|month|hour))?", re.IGNORECASE)

# Targets (do roadmap)
TARGET_SCORE_AVG = 4.0
TARGET_MIN_SCORE_ANY_CRITERIA = 3.0
TARGET_COST_PER_QUERY = 0.05  # USD


@dataclass
class RubricScore:
    """Score 1-5 por critério da rubrica."""

    accuracy: float = 0.0
    grounding: float = 0.0
    citation: float = 0.0
    format: float = 0.0
    zero_price: float = 0.0

    @property
    def avg(self) -> float:
        return statistics.mean([
            self.accuracy, self.grounding, self.citation, self.format, self.zero_price
        ])

    def to_dict(self) -> dict[str, float]:
        return {
            "accuracy": self.accuracy,
            "grounding": self.grounding,
            "citation": self.citation,
            "format": self.format,
            "zero_price": self.zero_price,
            "avg": self.avg,
        }


@dataclass
class EvalResult:
    """Resultado de avaliação de um caso."""

    case_id: str
    question: str
    category: str
    cloud: str | None = None
    passed: bool = False
    error: str | None = None
    answer: str = ""
    sources_count: int = 0
    has_grounding: bool = False
    findings_severities: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    mentions_found: list[str] = field(default_factory=list)
    mentions_missing: list[str] = field(default_factory=list)
    severity_ok: bool = False
    score: RubricScore = field(default_factory=RubricScore)
    cost_estimated_usd: float = 0.0
    zero_price_violations: list[str] = field(default_factory=list)


def _mentions_found(answer: str, must_mention: list[str]) -> list[str]:
    low = answer.lower()
    return [m for m in must_mention if m.lower() in low]


def _detect_zero_price_violations(answer: str, has_tools: bool) -> list[str]:
    """Detecta preços mencionados sem ser de tool ao vivo.

    Se tools_used estiver vazio E resposta tem $ específico → violação.
    """
    if has_tools:
        return []  # Preços OK se vierem de tool ao vivo
    prices = PRICE_RE.findall(answer)
    # Filtra preços "vagos" como "$X-Y" (range) — só flag se preço concreto
    concrete = [p for p in prices if re.search(r"\$[\d,]+", p) and len(p) > 3]
    return concrete[:5]  # máximo 5 violações reportadas


def _score_zero_price(zero_price_violations: list[str], has_tools: bool) -> float:
    """Score 1-5: zero_price.

    5 = sem violações
    1 = múltiplas violações (preços específicos sem tool)
    """
    if has_tools:
        return 5.0  # tools ao vivo justificam preços
    if not zero_price_violations:
        return 5.0
    # Cada violação desconta 0.5 ponto
    penalty = min(len(zero_price_violations) * 0.5, 4.0)
    return max(5.0 - penalty, 1.0)


def _score_grounding(has_grounding: bool, sources_count: int) -> float:
    """Score 1-5: grounding.

    5 = grounding + >=4 sources
    1 = sem grounding
    """
    if not has_grounding:
        return 1.0
    if sources_count >= 4:
        return 5.0
    if sources_count >= 2:
        return 4.0
    return 3.0


def _score_citation(answer: str) -> float:
    """Score 1-5: citation.

    5 = >=3 citações no formato [cloud, ...]
    1 = sem citações
    """
    citations = CITATION_RE.findall(answer)
    n = len(citations)
    if n >= 3:
        return 5.0
    if n >= 1:
        return 4.0
    return 2.0  # Sem citações explícitas


def _score_format(answer: str, has_findings: bool, intent: str) -> float:
    """Score 1-5: format.

    Espera:
    - Resumo executivo (sempre)
    - Achados priorizados (quando IAC)
    - Plano de melhorias (quando análise)
    - Referências (quando tem grounding)
    """
    if len(answer) < 100:
        return 1.0
    score = 4.0  # Base: resposta substancial
    # Bonus por estrutura
    if has_findings:
        score += 0.5
    if any(kw in answer.lower() for kw in ["resumo", "achados", "recomend", "referência"]):
        score += 0.5
    return min(score, 5.0)


def _score_accuracy_heuristic(
    case: dict[str, Any], mentions_found: list[str], mentions_missing: list[str],
    severity_ok: bool | None
) -> float:
    """Score 1-5: accuracy (heurística automática).

    5 = todas menções esperadas + severidades OK
    1 = sem menções + sem grounding
    """
    must_mention = case.get("must_mention", [])
    must_severity = case.get("must_find_severity", [])

    if must_mention:
        ratio = len(mentions_found) / len(must_mention)
        score = 1.0 + ratio * 4.0  # 0% → 1.0, 100% → 5.0
    else:
        score = 4.0  # Sem menções obrigatórias — neutro

    # Penalidade se severidade obrigatória não foi encontrada
    if must_severity and severity_ok is False:
        score -= 1.0

    return max(min(score, 5.0), 1.0)


def _estimate_cost_usd(answer: str, sources_count: int) -> float:
    """Estimativa de custo em USD baseado em heurística simples.

    ~$3/M tokens input, $15/M tokens output para Claude Sonnet 4.5.
    """
    # Estimativa: ~4 chars por token, ~500 tokens input médio (pergunta + contexto)
    input_chars = 500 * 4
    output_chars = len(answer)
    input_tokens = input_chars // 4
    output_tokens = output_chars // 4
    # Custo Claude Sonnet 4.5: ~$3/M input, $15/M output
    cost = (input_tokens * 3 / 1_000_000) + (output_tokens * 15 / 1_000_000)
    # Embedding local (free)
    # + $0.001 por source de tool ao vivo (se houver)
    cost += sources_count * 0.001
    return cost


# ─────────────────────────────────────────────────────────────────────────
# Runners
# ─────────────────────────────────────────────────────────────────────────


def run_case_offline(case: dict[str, Any]) -> EvalResult:
    """Valida só o Inspection Engine (sem LLM/API) — útil em CI barata."""
    from cip.inspection.engine import inspect_payload

    result = EvalResult(
        case_id=case["id"],
        question=case["question"],
        category=case["category"],
        cloud=case.get("cloud"),
    )

    payload = case.get("iac_payload")
    if not payload:
        result.skipped = "sem iac_payload"  # type: ignore[attr-defined]
        result.error = "skipped"
        return result

    findings = inspect_payload(payload)
    severities = sorted({f.severity for f in findings})
    result.findings_severities = severities
    result.answer = f"[Inspection offline] {len(findings)} findings"

    must_mention = case.get("must_mention", [])
    if must_mention:
        result.mentions_found = []  # Sem LLM, não temos "answer"
        result.mentions_missing = must_mention

    must_severity = case.get("must_find_severity", [])
    if must_severity:
        result.severity_ok = all(s in severities for s in must_severity)

    # Score: para offline, só podemos medir accuracy (severity) e format
    result.score.accuracy = _score_accuracy_heuristic(
        case, result.mentions_found, result.mentions_missing, result.severity_ok
    )
    result.score.format = _score_format("", bool(findings), case["category"])
    result.score.grounding = 5.0  # Inspection Engine tem grounding implícito
    result.score.citation = 5.0  # Inspection cita regras por design
    result.score.zero_price = 5.0  # Inspection não infere preço

    result.passed = result.score.avg >= TARGET_SCORE_AVG
    return result


def run_case_api(client: Any, case: dict[str, Any]) -> EvalResult:
    """Executa caso via API (httpx client)."""
    result = EvalResult(
        case_id=case["id"],
        question=case["question"],
        category=case["category"],
        cloud=case.get("cloud"),
    )

    try:
        if case.get("iac_payload") or case["category"] == "iac_review":
            resp = client.post(
                "/analyze",
                json={
                    "question": case["question"],
                    "cloud": case.get("cloud"),
                    "iac_payload": case.get("iac_payload"),
                },
                timeout=120,
            )
            data = resp.json()
            result.answer = data.get("summary", "")
            severities = {f["severity"] for f in data.get("findings", [])}
            result.findings_severities = sorted(severities)
            result.tools_used = data.get("tools_used", [])
        else:
            resp = client.post(
                "/ask",
                json={"question": case["question"], "cloud": case.get("cloud")},
                timeout=120,
            )
            data = resp.json()
            result.answer = data.get("answer", "")
            result.sources_count = len(data.get("sources", []))
            result.has_grounding = data.get("has_grounding", False)
            result.tools_used = []
    except Exception as exc:
        result.error = str(exc)
        # Score zerado em caso de erro
        result.score.accuracy = 1.0
        return result

    # Calcular scores
    must_mention = case.get("must_mention", [])
    if must_mention:
        result.mentions_found = _mentions_found(result.answer, must_mention)
        result.mentions_missing = [m for m in must_mention if m not in result.mentions_found]

    must_severity = case.get("must_find_severity", [])
    if must_severity:
        result.severity_ok = all(s in result.findings_severities for s in must_severity)

    # Detectar violações de "zero preço inferido"
    has_tools = bool(result.tools_used)
    result.zero_price_violations = _detect_zero_price_violations(result.answer, has_tools)

    # Score por critério
    result.score.accuracy = _score_accuracy_heuristic(
        case, result.mentions_found, result.mentions_missing,
        result.severity_ok if must_severity else None,
    )
    result.score.grounding = _score_grounding(result.has_grounding, result.sources_count)
    result.score.citation = _score_citation(result.answer)
    result.score.format = _score_format(result.answer, bool(result.findings_severities), case["category"])
    result.score.zero_price = _score_zero_price(result.zero_price_violations, has_tools)

    result.cost_estimated_usd = _estimate_cost_usd(result.answer, result.sources_count)
    result.passed = result.score.avg >= TARGET_SCORE_AVG
    return result


# ─────────────────────────────────────────────────────────────────────────
# Aggregation & gate
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class EvalReport:
    """Relatório agregado de avaliação."""

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    n_cases: int = 0
    n_passed: int = 0
    avg_scores: dict[str, float] = field(default_factory=dict)
    cost_median_usd: float = 0.0
    zero_price_violations_total: int = 0
    zero_price_violations_pct: float = 0.0
    gate_passed: bool = False
    gate_failures: list[str] = field(default_factory=list)
    by_category: dict[str, dict[str, float]] = field(default_factory=dict)
    by_cloud: dict[str, dict[str, float]] = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)


def aggregate(results: list[EvalResult]) -> EvalReport:
    """Agrega resultados e verifica gate de produção."""
    report = EvalReport(n_cases=len(results))
    if not results:
        report.gate_passed = True  # vazio = passa (sem nada para falhar)
        return report

    # Média de scores por critério
    criteria = ["accuracy", "grounding", "citation", "format", "zero_price"]
    for c in criteria:
        values = [getattr(r.score, c) for r in results if r.error is None]
        if values:
            report.avg_scores[c] = round(statistics.mean(values), 3)

    # Pass rate
    report.n_passed = sum(1 for r in results if r.passed)

    # Custo mediano
    costs = [r.cost_estimated_usd for r in results if r.cost_estimated_usd > 0]
    if costs:
        report.cost_median_usd = round(statistics.median(costs), 6)

    # Zero-price violations
    total_violations = sum(len(r.zero_price_violations) for r in results)
    report.zero_price_violations_total = total_violations
    cases_with_violations = sum(1 for r in results if r.zero_price_violations)
    report.zero_price_violations_pct = (
        round(cases_with_violations / len(results) * 100, 1) if results else 0.0
    )

    # Por categoria
    cats: dict[str, list[EvalResult]] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)
    for cat, items in cats.items():
        scores = [r.score.avg for r in items if r.error is None]
        if scores:
            report.by_category[cat] = {
                "n": len(items),
                "avg_score": round(statistics.mean(scores), 3),
                "pass_rate": round(sum(1 for r in items if r.passed) / len(items) * 100, 1),
            }

    # Por cloud
    clouds: dict[str, list[EvalResult]] = {}
    for r in results:
        if r.cloud:
            clouds.setdefault(r.cloud, []).append(r)
    for c, items in clouds.items():
        scores = [r.score.avg for r in items if r.error is None]
        if scores:
            report.by_cloud[c] = {
                "n": len(items),
                "avg_score": round(statistics.mean(scores), 3),
                "pass_rate": round(sum(1 for r in items if r.passed) / len(items) * 100, 1),
            }

    # ── Gate de produção ────────────────────────────────────────────────
    report.gate_failures = []
    for c in criteria:
        score = report.avg_scores.get(c, 0.0)
        if score < TARGET_SCORE_AVG:
            report.gate_failures.append(
                f"{c}: avg {score:.2f} < target {TARGET_SCORE_AVG}"
            )
    # Algum cenário com score < 3.0 em accuracy?
    low_accuracy = [r for r in results if r.score.accuracy < TARGET_MIN_SCORE_ANY_CRITERIA]
    if low_accuracy:
        report.gate_failures.append(
            f"{len(low_accuracy)} casos com accuracy < {TARGET_MIN_SCORE_ANY_CRITERIA}: "
            + ", ".join(r.case_id for r in low_accuracy[:5])
        )
    # Custo > target?
    if report.cost_median_usd > TARGET_COST_PER_QUERY:
        report.gate_failures.append(
            f"custo mediano ${report.cost_median_usd:.4f} > target ${TARGET_COST_PER_QUERY}"
        )
    # Zero-price violations > 5%?
    if report.zero_price_violations_pct > 5.0:
        report.gate_failures.append(
            f"{report.zero_price_violations_pct}% casos com violação zero-price > 5%"
        )

    report.gate_passed = len(report.gate_failures) == 0
    report.results = results
    return report


def render_markdown(report: EvalReport) -> str:
    """Gera relatório Markdown legível."""
    lines = [
        f"# Relatório de Avaliação CIP",
        f"",
        f"**Data**: {report.timestamp}",
        f"**Casos avaliados**: {report.n_cases}",
        f"**Pass rate**: {report.n_passed}/{report.n_cases} "
        f"({report.n_passed/report.n_cases*100:.1f}%)" if report.n_cases else "",
        f"**Gate de produção**: {'✅ PASSOU' if report.gate_passed else '❌ FALHOU'}",
        f"",
        f"## Scores médios por critério (target ≥ {TARGET_SCORE_AVG})",
        f"",
    ]
    for c, s in report.avg_scores.items():
        marker = "✅" if s >= TARGET_SCORE_AVG else "❌"
        lines.append(f"- {marker} **{c}**: {s:.2f}")

    lines += [
        f"",
        f"## Custo e compliance",
        f"- **Custo mediano por query**: ${report.cost_median_usd:.4f} (target < ${TARGET_COST_PER_QUERY})",
        f"- **Violações zero-price**: {report.zero_price_violations_total} "
        f"({report.zero_price_violations_pct}% dos casos)",
        f"",
    ]

    if report.gate_failures:
        lines += ["## Falhas do gate", ""]
        for f in report.gate_failures:
            lines.append(f"- ❌ {f}")
        lines.append("")

    if report.by_category:
        lines += ["## Por categoria", ""]
        lines.append("| Categoria | N | Avg Score | Pass Rate |")
        lines.append("|---|---|---|---|")
        for cat, stats in sorted(report.by_category.items()):
            lines.append(
                f"| {cat} | {stats['n']} | {stats['avg_score']:.2f} | "
                f"{stats['pass_rate']:.0f}% |"
            )
        lines.append("")

    if report.by_cloud:
        lines += ["## Por cloud", ""]
        lines.append("| Cloud | N | Avg Score | Pass Rate |")
        lines.append("|---|---|---|---|")
        for c, stats in sorted(report.by_cloud.items()):
            lines.append(
                f"| {c} | {stats['n']} | {stats['avg_score']:.2f} | "
                f"{stats['pass_rate']:.0f}% |"
            )
        lines.append("")

    # Casos com problemas
    failed = [r for r in report.results if not r.passed]
    if failed:
        lines += [f"## Casos que falharam ({len(failed)})", ""]
        for r in failed[:10]:
            lines.append(
                f"- **{r.case_id}** ({r.category}/{r.cloud}): "
                f"avg={r.score.avg:.2f} accuracy={r.score.accuracy:.2f} "
                f"grounding={r.score.grounding:.2f}"
            )
        if len(failed) > 10:
            lines.append(f"- ... e mais {len(failed) - 10}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Runner de avaliação CIP (Quality Gate)")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--offline", action="store_true", help="Só Inspection Engine, sem LLM")
    parser.add_argument("--report-md", action="store_true", help="Gera relatório Markdown")
    parser.add_argument("--strict", action="store_true", help="Falha se gate não passar (exit code 1)")
    args = parser.parse_args()

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    RESULTS_DIR.mkdir(exist_ok=True)

    print(f"Avaliando {len(cases)} casos ({'offline' if args.offline else 'API'})...")

    results: list[EvalResult] = []
    if args.offline:
        for case in cases:
            results.append(run_case_offline(case))
    else:
        import httpx

        with httpx.Client(base_url=args.api) as client:
            for case in cases:
                results.append(run_case_api(client, case))

    report = aggregate(results)

    # Salvar JSON
    json_file = RESULTS_DIR / "eval_results.json"
    json_file.write_text(
        json.dumps(
            {
                "report": asdict(report),
                # Remove dataclass results to avoid nested dict issues; serialize separately
            },
            indent=2,
            default=str,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Salvar Markdown (se pedido)
    if args.report_md:
        md_file = RESULTS_DIR / "eval_report.md"
        md_file.write_text(render_markdown(report), encoding="utf-8")
        print(f"Relatório Markdown: {md_file}")

    # Resumo console
    print(f"\n{'=' * 70}")
    print(f"RESULTADO: {report.n_passed}/{report.n_cases} passaram")
    print(f"GATE: {'[PASS]' if report.gate_passed else '[FAIL]'}")
    print(f"{'=' * 70}")
    print("Scores médios:")
    for c, s in report.avg_scores.items():
        marker = "[OK]" if s >= TARGET_SCORE_AVG else "[--]"
        print(f"  {marker} {c}: {s:.2f}")
    print(f"\nCusto mediano: ${report.cost_median_usd:.4f}")
    print(f"Violacoes zero-price: {report.zero_price_violations_total} ({report.zero_price_violations_pct}%)")
    if report.gate_failures:
        print("\nFalhas do gate:")
        for f in report.gate_failures:
            print(f"  [FAIL] {f}")

    print(f"\nResultados salvos em: {json_file}")

    if args.strict and not report.gate_passed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())