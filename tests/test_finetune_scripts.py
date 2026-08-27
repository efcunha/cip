"""Testes para os scripts de fine-tuning (Fase 7).

Valida:
- generate_finetune_dataset.py: gera dataset, dedupe, stats
- eval_ab_finetune.py: verdict logic, decisão de promoção
- train_lora.py: config validation (sem GPU)

Uso:
    pytest tests/test_finetune_scripts.py -v
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────
# Path setup
# ─────────────────────────────────────────────────────────────────────────


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def temp_dir():
    """Cria diretório temporário com permissões abertas (Windows-safe)."""
    import uuid
    base_tmp = ROOT / ".tmp_test"
    base_tmp.mkdir(exist_ok=True)
    path = base_tmp / f"cip_test_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────
# Dataset generation
# ─────────────────────────────────────────────────────────────────────────


class TestGenerateDataset:
    """Geração de dataset sintético."""

    def test_script_exists(self) -> None:
        script = ROOT / "scripts" / "generate_finetune_dataset.py"
        assert script.exists()
        assert script.stat().st_size > 1000  # tem código

    def test_runs_and_creates_files(self, temp_dir: Path) -> None:
        """Rodar script com count baixo e verificar outputs."""
        out_dir = temp_dir / "finetune"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "generate_finetune_dataset.py"),
                "--output", str(out_dir),
                "--count", "50",
                "--seed", "42",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Outputs criados
        assert (out_dir / "train.jsonl").exists()
        assert (out_dir / "train.stats.json").exists()
        assert (out_dir / "curation_checklist.md").exists()

    def test_dataset_has_required_fields(self, temp_dir: Path) -> None:
        out_dir = temp_dir / "finetune"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "generate_finetune_dataset.py"),
                "--output", str(out_dir),
                "--count", "20",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        # Verifica estrutura do JSONL
        with (out_dir / "train.jsonl").open() as f:
            first = json.loads(f.readline())
        assert "instruction" in first
        assert "input" in first
        assert "output" in first
        assert "persona" in first
        assert "category" in first
        assert "cloud" in first

    def test_dataset_includes_eval_seeds(self, temp_dir: Path) -> None:
        """Com --seed-from-eval, casos do eval/test_cases.json entram."""
        out_dir = temp_dir / "finetune"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "generate_finetune_dataset.py"),
                "--output", str(out_dir),
                "--count", "10",
                "--seed-from-eval",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        with (out_dir / "train.jsonl").open() as f:
            items = [json.loads(line) for line in f]
        eval_seeded = [i for i in items if i["source"] == "eval_case"]
        assert len(eval_seeded) > 0, "Esperava itens seeded do eval"
        assert all("reviewed" in i for i in eval_seeded)

    def test_stats_reflect_diversity(self, temp_dir: Path) -> None:
        out_dir = temp_dir / "finetune"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "generate_finetune_dataset.py"),
                "--output", str(out_dir),
                "--count", "100",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        stats = json.loads((out_dir / "train.stats.json").read_text())
        # 100 variations geradas, dedup pode reduzir ~50-70% (templates com mesmo instruction+input)
        assert stats["total_items"] >= 30
        # Diversidade: pelo menos 3 personas
        assert len(stats["by_persona"]) >= 3
        # Pelo menos 3 categorias
        assert len(stats["by_category"]) >= 3
        # Todas as 3 clouds
        assert "aws" in stats["by_cloud"]
        assert "gcp" in stats["by_cloud"]
        assert "azure" in stats["by_cloud"]


# ─────────────────────────────────────────────────────────────────────────
# A/B Eval verdict
# ─────────────────────────────────────────────────────────────────────────


class TestABVerdict:
    """Verdict de promoção A/B."""

    def test_script_exists(self) -> None:
        script = ROOT / "scripts" / "eval_ab_finetune.py"
        assert script.exists()
        assert script.stat().st_size > 1000

    def test_promote_when_all_improvements(self) -> None:
        from scripts.eval_ab_finetune import EvalPhase, compute_verdict

        base = EvalPhase(
            phase_name="base", api_url="http://base",
            avg_scores={
                "accuracy": 4.0, "grounding": 4.0, "citation": 3.5,
                "format": 3.5, "zero_price": 5.0,
            },
            cost_median=0.01, latency_p95_ms=1000, zero_price_violations=0,
        )
        tuned = EvalPhase(
            phase_name="tuned", api_url="http://tuned",
            avg_scores={
                "accuracy": 4.2, "grounding": 4.1, "citation": 4.0,
                "format": 4.0, "zero_price": 5.0,
            },
            cost_median=0.012, latency_p95_ms=1100, zero_price_violations=0,
        )
        verdict = compute_verdict(base, tuned)
        assert verdict.should_promote is True
        assert verdict.factual_regression is False
        assert verdict.style_improvement is True

    def test_reject_on_factual_regression(self) -> None:
        from scripts.eval_ab_finetune import EvalPhase, compute_verdict

        base = EvalPhase(
            phase_name="base", api_url="x",
            avg_scores={
                "accuracy": 4.0, "grounding": 4.0, "citation": 4.0,
                "format": 4.0, "zero_price": 5.0,
            },
            cost_median=0.01, latency_p95_ms=1000, zero_price_violations=0,
        )
        # Tuned tem accuracy -0.3 (regressão factual)
        tuned = EvalPhase(
            phase_name="tuned", api_url="y",
            avg_scores={
                "accuracy": 3.7, "grounding": 4.0, "citation": 4.5,
                "format": 4.5, "zero_price": 5.0,
            },
            cost_median=0.015, latency_p95_ms=1200, zero_price_violations=0,
        )
        verdict = compute_verdict(base, tuned)
        assert verdict.factual_regression is True
        assert verdict.should_promote is False

    def test_reject_on_cost_overrun(self) -> None:
        from scripts.eval_ab_finetune import EvalPhase, compute_verdict

        base = EvalPhase(
            phase_name="base", api_url="x",
            avg_scores={
                "accuracy": 4.0, "grounding": 4.0, "citation": 4.0,
                "format": 4.0, "zero_price": 5.0,
            },
            cost_median=0.01, latency_p95_ms=1000, zero_price_violations=0,
        )
        # Custo 2x (acima de 1.5x threshold)
        tuned = EvalPhase(
            phase_name="tuned", api_url="y",
            avg_scores={
                "accuracy": 4.2, "grounding": 4.2, "citation": 4.5,
                "format": 4.5, "zero_price": 5.0,
            },
            cost_median=0.02, latency_p95_ms=1100, zero_price_violations=0,
        )
        verdict = compute_verdict(base, tuned)
        assert verdict.cost_ratio == 2.0
        assert verdict.should_promote is False

    def test_reject_on_zero_price_violations_increase(self) -> None:
        from scripts.eval_ab_finetune import EvalPhase, compute_verdict

        base = EvalPhase(
            phase_name="base", api_url="x",
            avg_scores={
                "accuracy": 4.0, "grounding": 4.0, "citation": 4.0,
                "format": 4.0, "zero_price": 5.0,
            },
            cost_median=0.01, latency_p95_ms=1000, zero_price_violations=0,
        )
        # Tuned tem 1 nova violação zero-price
        tuned = EvalPhase(
            phase_name="tuned", api_url="y",
            avg_scores={
                "accuracy": 4.2, "grounding": 4.2, "citation": 4.5,
                "format": 4.5, "zero_price": 4.0,
            },
            cost_median=0.012, latency_p95_ms=1100, zero_price_violations=1,
        )
        verdict = compute_verdict(base, tuned)
        assert verdict.zero_price_delta == 1
        assert verdict.should_promote is False

    def test_reject_on_no_style_improvement(self) -> None:
        from scripts.eval_ab_finetune import EvalPhase, compute_verdict

        base = EvalPhase(
            phase_name="base", api_url="x",
            avg_scores={
                "accuracy": 4.0, "grounding": 4.0, "citation": 4.0,
                "format": 4.0, "zero_price": 5.0,
            },
            cost_median=0.01, latency_p95_ms=1000, zero_price_violations=0,
        )
        # Sem melhora de estilo (format+citation delta < 0.2)
        tuned = EvalPhase(
            phase_name="tuned", api_url="y",
            avg_scores={
                "accuracy": 4.1, "grounding": 4.1, "citation": 4.05,
                "format": 4.05, "zero_price": 5.0,
            },
            cost_median=0.012, latency_p95_ms=1100, zero_price_violations=0,
        )
        verdict = compute_verdict(base, tuned)
        # format delta = 0.05, citation delta = 0.05 → soma 0.10 < 0.2
        assert verdict.style_improvement is False
        assert verdict.should_promote is False


# ─────────────────────────────────────────────────────────────────────────
# Train Lora validation
# ─────────────────────────────────────────────────────────────────────────


class TestTrainLoraValidation:
    """Validação de config LoRA sem GPU."""

    def test_script_exists(self) -> None:
        script = ROOT / "scripts" / "train_lora.py"
        assert script.exists()
        assert script.stat().st_size > 1000

    def test_validate_only_runs(self) -> None:
        """--validate-only não treina, só valida deps + dataset."""
        result = subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "train_lora.py"),
                "--validate-only",
                "--train-file", "eval/finetune/train.jsonl",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Deve sair com 0 (validação OK) ou 1 (deps faltando)
        # Nunca deve chegar ao treino real
        assert "Iniciando Treino" not in result.stdout
        assert "Validação completa" in result.stdout or "WARN" in result.stdout

    def test_config_defaults(self) -> None:
        """Config padrão do LoRA tem hiperparâmetros recomendados do roadmap."""
        sys.path.insert(0, str(ROOT / "scripts"))
        from train_lora import LoRATrainingConfig

        config = LoRATrainingConfig()
        # Do docs/05-fine-tuning.md
        assert config.lora_r == 64
        assert config.lora_alpha == 128
        assert config.lora_dropout == 0.05
        assert config.num_train_epochs == 3
        assert config.learning_rate == 2e-4
        assert config.use_4bit is True
        # Target modules incluem attention + MLP
        assert "q_proj" in config.target_modules
        assert "down_proj" in config.target_modules

    def test_dataset_validation_too_small(self, temp_dir: Path) -> None:
        """Dataset com < 10 items deve ser rejeitado."""
        # Cria dataset pequeno
        ds_path = temp_dir / "tiny.jsonl"
        with ds_path.open("w") as f:
            for i in range(5):
                f.write(json.dumps({
                    "instruction": f"q{i}",
                    "input": "",
                    "output": f"a{i}",
                }) + "\n")

        sys.path.insert(0, str(ROOT / "scripts"))
        from train_lora import validate_dataset

        result = validate_dataset(ds_path)
        assert result is not None
        assert "pequeno" in result.lower() or "10" in result

    def test_dataset_validation_missing_review(self, temp_dir: Path) -> None:
        """Dataset sem revisão humana suficiente deve ser warning."""
        ds_path = temp_dir / "no_review.jsonl"
        items = []
        for i in range(20):
            items.append({
                "instruction": f"q{i}",
                "input": "",
                "output": f"a{i}",
                "reviewed": False,  # nenhum revisado
            })
        with ds_path.open("w") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

        sys.path.insert(0, str(ROOT / "scripts"))
        from train_lora import validate_dataset

        result = validate_dataset(ds_path)
        assert result is not None
        assert "revisado" in result.lower() or "30%" in result