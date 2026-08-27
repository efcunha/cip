"""Testes para o runner de avaliação (eval/run_eval.py).

Valida:
- Rubrica 1-5 funciona corretamente
- Gate de produção bloqueia < 4.0
- Score accuracy heurístico baseado em menções
- Score zero_price detecta violações
- Modo offline valida Inspection Engine
- Aggregação + relatório funcionam

Uso:
    pytest tests/test_eval_runner.py -v
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from eval.run_eval import (
    CITATION_RE,
    PRICE_RE,
    TARGET_SCORE_AVG,
    _detect_zero_price_violations,
    _estimate_cost_usd,
    _score_accuracy_heuristic,
    _score_citation,
    _score_format,
    _score_grounding,
    _score_zero_price,
    aggregate,
    render_markdown,
    run_case_offline,
)


# ─────────────────────────────────────────────────────────────────────────
# Heurística de scoring
# ─────────────────────────────────────────────────────────────────────────


class TestScoreAccuracy:
    """Score accuracy: baseado em menções encontradas."""

    def test_full_match_5(self) -> None:
        case = {"must_mention": ["aws", "s3", "encryption"]}
        found = ["aws", "s3", "encryption"]
        missing = []
        score = _score_accuracy_heuristic(case, found, missing, None)
        assert score == 5.0

    def test_partial_match(self) -> None:
        case = {"must_mention": ["aws", "s3", "encryption"]}
        found = ["aws"]
        missing = ["s3", "encryption"]
        score = _score_accuracy_heuristic(case, found, missing, None)
        # 1/3 → 1.0 + (1/3 * 4) = 2.33
        assert 2.0 <= score <= 2.5

    def test_no_match(self) -> None:
        case = {"must_mention": ["aws", "s3"]}
        found = []
        missing = ["aws", "s3"]
        score = _score_accuracy_heuristic(case, found, missing, None)
        assert score == 1.0

    def test_no_must_mention_neutral_4(self) -> None:
        case = {"must_mention": []}
        score = _score_accuracy_heuristic(case, [], [], None)
        assert score == 4.0

    def test_severity_miss_penalty(self) -> None:
        case = {"must_mention": ["aws"], "must_find_severity": ["critical"]}
        score_full = _score_accuracy_heuristic(case, ["aws"], [], True)
        score_miss = _score_accuracy_heuristic(case, ["aws"], [], False)
        assert score_miss < score_full
        assert score_miss >= 1.0


class TestScoreGrounding:
    """Score grounding: tem grounding + número de sources."""

    def test_no_grounding_is_1(self) -> None:
        assert _score_grounding(False, 0) == 1.0

    def test_grounding_no_sources(self) -> None:
        # has_grounding True mas 0 sources (raro, mas possível)
        assert _score_grounding(True, 0) == 3.0

    def test_grounding_2_sources(self) -> None:
        assert _score_grounding(True, 2) == 4.0

    def test_grounding_4_sources(self) -> None:
        assert _score_grounding(True, 4) == 5.0


class TestScoreCitation:
    """Score citation: detecção de [cloud, service, ...]."""

    def test_no_citations(self) -> None:
        answer = "AWS S3 é bom para guardar arquivos."
        assert _score_citation(answer) == 2.0

    def test_one_citation(self) -> None:
        answer = "Conforme [aws, s3, Well-Architected: Storage]."
        assert _score_citation(answer) == 4.0

    def test_three_citations(self) -> None:
        answer = "Ver [aws, ec2, Compute] e [aws, s3, Storage] e [aws, rds, Database]."
        assert _score_citation(answer) == 5.0

    def test_citation_with_url(self) -> None:
        answer = "Veja [aws, lambda, Guia Lambda, https://docs.aws.amazon.com/lambda]."
        assert _score_citation(answer) == 4.0


class TestScoreFormat:
    """Score format: estrutura da resposta."""

    def test_short_answer_is_1(self) -> None:
        assert _score_format("Resposta curta", False, "knowledge") == 1.0

    def test_long_answer_base_4(self) -> None:
        answer = "x" * 200
        score = _score_format(answer, False, "knowledge")
        assert score == 4.0

    def test_with_findings_bonus(self) -> None:
        answer = "x" * 200
        score = _score_format(answer, True, "iac_review")
        assert score == 4.5

    def test_with_structured_keywords_bonus(self) -> None:
        answer = "x" * 200 + " Resumo Achados Recomendação Referências"
        score = _score_format(answer, True, "iac_review")
        assert score == 5.0


class TestScoreZeroPrice:
    """Score zero_price: detecção de violações de preço."""

    def test_no_violations_is_5(self) -> None:
        assert _score_zero_price([], has_tools=False) == 5.0

    def test_with_tools_is_5(self) -> None:
        # tools ao vivo justificam preços
        assert _score_zero_price(["$1000"], has_tools=True) == 5.0

    def test_one_violation(self) -> None:
        score = _score_zero_price(["$100/mês"], has_tools=False)
        assert score == 4.5

    def test_multiple_violations(self) -> None:
        score = _score_zero_price(["$100", "$200", "$300"], has_tools=False)
        # 3 violations × 0.5 penalty = 1.5 → 5 - 1.5 = 3.5
        assert score == 3.5

    def test_max_penalty_capped_at_1(self) -> None:
        # 10 violations → cap em 4.0 penalty → score 1.0
        score = _score_zero_price(["$100"] * 10, has_tools=False)
        assert score == 1.0


class TestDetectZeroPriceViolations:
    """Detecção de preços concretos."""

    def test_no_prices(self) -> None:
        assert _detect_zero_price_violations(
            "AWS S3 é bom para arquivos.", has_tools=False
        ) == []

    def test_specific_price_no_tool(self) -> None:
        violations = _detect_zero_price_violations(
            "EC2 custa $0.10/hora neste caso.", has_tools=False
        )
        assert len(violations) > 0
        assert "$0.10" in violations[0]

    def test_specific_price_with_tool_ok(self) -> None:
        violations = _detect_zero_price_violations(
            "EC2 custa $0.10/hora (dados ao vivo).", has_tools=True
        )
        assert violations == []

    def test_vague_range_ignored(self) -> None:
        # Ranges sem preço específico ($X a $Y) são menos problemáticos
        violations = _detect_zero_price_violations(
            "Custo varia de baixo a alto.", has_tools=False
        )
        assert violations == []


class TestCostEstimation:
    """Estimativa de custo USD."""

    def test_zero_answer_is_zero(self) -> None:
        # Resposta vazia tem custo mínimo (embedding fixed cost)
        cost = _estimate_cost_usd("", 0)
        assert cost < 0.005  # bem próximo de zero

    def test_short_answer_low_cost(self) -> None:
        cost = _estimate_cost_usd("Resposta curta", 0)
        assert cost < 0.01

    def test_long_answer_with_sources(self) -> None:
        # 4000 chars = 1000 tokens output, 0 sources = $0.015
        answer = "x" * 4000
        cost = _estimate_cost_usd(answer, 0)
        assert 0.01 < cost < 0.05

    def test_target_cost_under_5cents(self) -> None:
        """Custo típico deve estar bem abaixo do target de $0.05."""
        answer = "x" * 2000  # ~500 tokens
        cost = _estimate_cost_usd(answer, 2)
        assert cost < 0.05


# ─────────────────────────────────────────────────────────────────────────
# Aggregation & gate
# ─────────────────────────────────────────────────────────────────────────


class TestAggregate:
    """Aggregação de múltiplos EvalResults."""

    def test_empty_results(self) -> None:
        from eval.run_eval import EvalResult, RubricScore

        report = aggregate([])
        assert report.n_cases == 0
        assert report.gate_passed is True  # vazio = passa

    def test_all_pass(self) -> None:
        from eval.run_eval import EvalResult, RubricScore

        # 3 casos com scores >= 4.0
        results = []
        for i in range(3):
            r = EvalResult(
                case_id=f"test-{i}",
                question="q",
                category="knowledge",
                cloud="aws",
                answer="Resposta com [aws, s3] citação.",
                sources_count=4,
                has_grounding=True,
                score=RubricScore(
                    accuracy=4.5, grounding=5.0, citation=5.0, format=4.5, zero_price=5.0
                ),
                passed=True,
            )
            results.append(r)

        report = aggregate(results)
        assert report.n_cases == 3
        assert report.n_passed == 3
        assert report.gate_passed is True
        assert len(report.gate_failures) == 0

    def test_low_accuracy_fails_gate(self) -> None:
        from eval.run_eval import EvalResult, RubricScore

        r = EvalResult(
            case_id="low-acc",
            question="q",
            category="knowledge",
            cloud="aws",
            answer="Resposta.",
            has_grounding=True,
            score=RubricScore(
                accuracy=2.0,  # abaixo do target 3.0
                grounding=5.0, citation=5.0, format=4.5, zero_price=5.0
            ),
        )
        report = aggregate([r])
        assert report.gate_passed is False
        assert any("accuracy" in f.lower() for f in report.gate_failures)

    def test_high_cost_fails_gate(self) -> None:
        from eval.run_eval import EvalResult, RubricScore

        r = EvalResult(
            case_id="expensive",
            question="q",
            category="knowledge",
            cloud="aws",
            answer="x" * 100000,  # resposta gigante
            score=RubricScore(accuracy=4.5, grounding=5.0, citation=5.0, format=4.5, zero_price=5.0),
            cost_estimated_usd=1.0,  # $1 — bem acima do target
        )
        report = aggregate([r])
        assert report.gate_passed is False
        assert any("custo" in f.lower() for f in report.gate_failures)

    def test_zero_price_violation_above_5pct_fails(self) -> None:
        from eval.run_eval import EvalResult, RubricScore

        # 10 casos, 1 com violação = 10% > 5%
        results = []
        for i in range(10):
            r = EvalResult(
                case_id=f"t-{i}",
                question="q",
                category="knowledge",
                cloud="aws",
                score=RubricScore(accuracy=4.5, grounding=5.0, citation=5.0, format=4.5, zero_price=5.0),
            )
            if i == 0:
                r.zero_price_violations = ["$100"]
                r.score.zero_price = 4.0
            results.append(r)

        report = aggregate(results)
        assert report.gate_passed is False
        assert any("zero-price" in f.lower() for f in report.gate_failures)

    def test_by_category_grouping(self) -> None:
        from eval.run_eval import EvalResult, RubricScore

        results = []
        for cat, n in [("knowledge", 5), ("iac_review", 3), ("custo", 2)]:
            for i in range(n):
                results.append(EvalResult(
                    case_id=f"{cat}-{i}",
                    question="q",
                    category=cat,
                    cloud="aws",
                    score=RubricScore(accuracy=4.5, grounding=5.0, citation=5.0, format=4.5, zero_price=5.0),
                ))

        report = aggregate(results)
        assert "knowledge" in report.by_category
        assert "iac_review" in report.by_category
        assert "custo" in report.by_category
        assert report.by_category["knowledge"]["n"] == 5


class TestRenderMarkdown:
    """Renderização do relatório Markdown."""

    def test_markdown_includes_scores(self) -> None:
        from eval.run_eval import EvalResult, RubricScore

        r = EvalResult(
            case_id="md-test",
            question="q",
            category="knowledge",
            cloud="aws",
            score=RubricScore(accuracy=4.5, grounding=5.0, citation=5.0, format=4.5, zero_price=5.0),
        )
        report = aggregate([r])
        md = render_markdown(report)
        assert "# Relatório de Avaliação CIP" in md
        assert "accuracy" in md
        assert "GATE" in md or "Gate" in md

    def test_markdown_includes_gate_failures(self) -> None:
        from eval.run_eval import EvalResult, RubricScore

        r = EvalResult(
            case_id="fail",
            question="q",
            category="knowledge",
            cloud="aws",
            score=RubricScore(accuracy=2.0, grounding=5.0, citation=5.0, format=4.5, zero_price=5.0),
        )
        report = aggregate([r])
        md = render_markdown(report)
        assert "FALHOU" in md
        assert "Falhas do gate" in md


# ─────────────────────────────────────────────────────────────────────────
# Offline runner (Inspection Engine)
# ─────────────────────────────────────────────────────────────────────────


class TestRunCaseOffline:
    """Runner offline valida Inspection Engine sem LLM."""

    def test_iac_case_with_payload(self) -> None:
        case = {
            "id": "iac-test-001",
            "category": "iac_review",
            "cloud": "aws",
            "question": "Revise esse Terraform",
            "iac_payload": (
                'resource "aws_s3_bucket" "x" { bucket = "x" }\n'
                'resource "aws_security_group" "web" {\n'
                '  ingress {\n'
                '    from_port = 22\n'
                '    to_port = 22\n'
                '    protocol = "tcp"\n'
                '    cidr_blocks = ["0.0.0.0/0"]\n'
                '  }\n'
                '}\n'
            ),
            "must_find_severity": ["critical", "high"],
        }
        result = run_case_offline(case)
        # SG 0.0.0.0/0 → critical, S3 sem encryption → high
        assert "critical" in result.findings_severities
        assert "high" in result.findings_severities
        assert result.severity_ok is True
        # Score automático (offline)
        assert result.score.grounding == 5.0
        assert result.score.citation == 5.0
        assert result.score.zero_price == 5.0

    def test_skip_case_without_payload(self) -> None:
        case = {
            "id": "no-payload",
            "category": "knowledge",
            "cloud": "aws",
            "question": "O que é S3?",
        }
        result = run_case_offline(case)
        assert result.error == "skipped"

    def test_iac_severity_miss(self) -> None:
        case = {
            "id": "iac-miss",
            "category": "iac_review",
            "cloud": "aws",
            "question": "Revise",
            "iac_payload": 'resource "aws_s3_bucket" "x" { bucket = "x" }',
            "must_find_severity": ["critical"],  # S3 sozinho é só high
        }
        result = run_case_offline(case)
        assert result.severity_ok is False