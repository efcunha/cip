#!/usr/bin/env python3
"""Script de fine-tuning com LoRA/QLoRA (Fase 7).

Treina um adapter LoRA sobre Llama 3.3 8B ou 70B usando:
- PEFT (LoRA)
- TRL SFTTrainer
- 4-bit quantization (QLoRA) para caber em 1 GPU

O script é READY mas NÃO treina por padrão — requer GPU + credenciais.
Valida que tudo está configurado antes de gastar recursos de treino.

Custo estimado (baseado em docs/05-fine-tuning.md):
- Llama 3.3 8B em A100 80GB: ~$50-200, 2-6 horas
- Llama 3.3 70B em 4×A100 80GB: ~$500-1500, 8-24 horas

Uso:
    # Validar configuração sem treinar (dry-run)
    python scripts/train_lora.py --validate-only

    # Treinar (requer GPU + credenciais HuggingFace)
    python scripts/train_lora.py --model meta-llama/Llama-3.3-8B-Instruct --epochs 3

    # Treinar 70B (requer múltiplas GPUs)
    python scripts/train_lora.py --model meta-llama/Llama-3.3-70B-Instruct --epochs 3

Hiperparâmetros de partida (do roadmap):
- LoRA r=64, alpha=128, dropout=0.05
- 3 épocas, lr=2e-4, bf16
- Effective batch size: 32 (per_device 4 × grad_accum 8)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class LoRATrainingConfig:
    """Config completa de fine-tuning."""

    # Modelo base
    base_model: str = "meta-llama/Llama-3.3-8B-Instruct"
    use_4bit: bool = True  # QLoRA: 4-bit quantization

    # LoRA hiperparâmetros
    lora_r: int = 64
    lora_alpha: int = 128
    lora_dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",  # MLP layers (Llama-style)
    ])
    bias: str = "none"
    task_type: str = "CAUSAL_LM"

    # Treino
    output_dir: str = "eval/finetune/checkpoints"
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 4
    gradient_accumulation_steps: int = 8  # effective batch = 32
    learning_rate: float = 2e-4
    weight_decay: float = 0.01
    warmup_ratio: float = 0.03
    lr_scheduler_type: str = "cosine"
    bf16: bool = True  # bfloat16 (A100+)
    fp16: bool = False
    max_grad_norm: float = 1.0
    seed: int = 42
    optim: str = "paged_adamw_8bit"  # 8-bit optimizer

    # Data
    train_file: str = "eval/finetune/train.jsonl"
    max_seq_length: int = 2048

    # Avaliação
    eval_strategy: str = "epoch"
    save_strategy: str = "epoch"
    save_total_limit: int = 3
    load_best_model_at_end: bool = True
    metric_for_best_model: str = "eval_loss"

    # Logging
    logging_steps: int = 10
    report_to: list[str] = field(default_factory=lambda: ["wandb"])

    # Persona-specific (NÃO deve mudar entre runs para preservar formato)
    system_prompt: str = (
        "Você é um engenheiro de cloud sênior especializado em AWS, GCP e Azure. "
        "Responda em português (pt-BR), cite fontes oficiais no formato "
        "[cloud, serviço, título, url] e exponha trade-offs quando relevante."
    )


# ─────────────────────────────────────────────────────────────────────────
# Validation (sem GPU)
# ─────────────────────────────────────────────────────────────────────────


def validate_dependencies() -> list[str]:
    """Verifica se deps de treino estão instaladas. Retorna lista de erros."""
    errors: list[str] = []
    required = {
        "torch": "PyTorch (GPU acceleration)",
        "transformers": "HuggingFace Transformers",
        "peft": "LoRA/QLoRA via PEFT",
        "trl": "SFT Trainer",
        "bitsandbytes": "4-bit quantization (QLoRA)",
        "datasets": "HuggingFace Datasets",
        "accelerate": "Distributed training helpers",
    }
    for module, desc in required.items():
        try:
            __import__(module)
        except ImportError:
            errors.append(f"Missing: {module} ({desc})")
    return errors


def validate_dataset(path: Path) -> str | None:
    """Valida que o dataset está pronto para treino."""
    if not path.exists():
        return f"Dataset não encontrado: {path}"
    with path.open() as f:
        lines = f.readlines()
    if len(lines) < 10:
        return f"Dataset muito pequeno: {len(lines)} items (mínimo: 10)"
    # Sample first item
    first = json.loads(lines[0])
    required_fields = {"instruction", "input", "output"}
    if not required_fields.issubset(first.keys()):
        return f"Item sem campos obrigatórios: {required_fields - set(first.keys())}"
    # Check reviewed ratio
    reviewed = sum(1 for line in lines if json.loads(line).get("reviewed", False))
    ratio = reviewed / len(lines)
    if ratio < 0.30:
        return (
            f"Apenas {ratio:.0%} do dataset revisado. "
            f"Mínimo recomendado: 30% (do ADR-0001 + roadmap)."
        )
    # Check flagged
    flagged = sum(1 for line in lines if json.loads(line).get("flagged_for_removal", False))
    if flagged > 0.10 * len(lines):
        return f"{flagged} itens flagged para remoção (>10%). Revisar antes."
    return None


def validate_gpu() -> tuple[bool, str]:
    """Verifica disponibilidade de GPU."""
    try:
        import torch

        if not torch.cuda.is_available():
            return False, "CUDA não disponível (requer GPU NVIDIA)"
        n_gpus = torch.cuda.device_count()
        gpu_name = torch.cuda.get_device_name(0)
        mem_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        return True, f"{n_gpus}× {gpu_name} ({mem_gb:.0f} GB)"
    except ImportError:
        return False, "PyTorch não instalado"


# ─────────────────────────────────────────────────────────────────────────
# Training (com GPU)
# ─────────────────────────────────────────────────────────────────────────


def setup_model_and_tokenizer(config: LoRATrainingConfig) -> tuple[Any, Any]:
    """Carrega modelo base + tokenizer com QLoRA config."""
    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
    )

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=config.use_4bit,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    ) if config.use_4bit else None

    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        config.base_model,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16 if config.bf16 else torch.float32,
    )
    model.config.use_cache = False  # incompatível com gradient checkpointing

    return model, tokenizer


def setup_lora(config: LoRATrainingConfig) -> Any:
    """Cria LoRA config."""
    from peft import LoraConfig

    return LoraConfig(
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        target_modules=config.target_modules,
        bias=config.bias,
        task_type=config.task_type,
    )


def load_and_format_dataset(config: LoRATrainingConfig) -> Any:
    """Carrega dataset JSONL e formata como instruction-tuning."""
    import torch
    from datasets import load_dataset
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(config.base_model)

    def format_example(example: dict[str, Any]) -> dict[str, list[int]]:
        """Formata item Alpaca em texto de treinamento."""
        if example.get("input"):
            text = (
                f"{config.system_prompt}\n\n"
                f"### Instruction:\n{example['instruction']}\n\n"
                f"### Input:\n{example['input']}\n\n"
                f"### Response:\n{example['output']}"
            )
        else:
            text = (
                f"{config.system_prompt}\n\n"
                f"### Instruction:\n{example['instruction']}\n\n"
                f"### Response:\n{example['output']}"
            )
        return {"text": text}

    raw = load_dataset("json", data_files=config.train_file, split="train")
    formatted = raw.map(
        format_example,
        remove_columns=raw.column_names,
        num_proc=os.cpu_count() or 1,
    )
    return formatted


def train(config: LoRATrainingConfig) -> None:
    """Executa o fine-tuning completo."""
    import torch
    from transformers import TrainingArguments
    from trl import SFTTrainer

    print(f"[INFO] Modelo: {config.base_model}")
    print(f"[INFO] Output: {config.output_dir}")
    print(f"[INFO] Épocas: {config.num_train_epochs}, LR: {config.learning_rate}")

    model, _ = setup_model_and_tokenizer(config)
    peft_config = setup_lora(config)
    train_dataset = load_and_format_dataset(config)
    print(f"[INFO] Dataset: {len(train_dataset)} items")

    training_args = TrainingArguments(
        output_dir=config.output_dir,
        num_train_epochs=config.num_train_epochs,
        per_device_train_batch_size=config.per_device_train_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        learning_rate=config.learning_rate,
        weight_decay=config.weight_decay,
        warmup_ratio=config.warmup_ratio,
        lr_scheduler_type=config.lr_scheduler_type,
        bf16=config.bf16,
        fp16=config.fp16,
        max_grad_norm=config.max_grad_norm,
        seed=config.seed,
        optim=config.optim,
        eval_strategy=config.eval_strategy,
        save_strategy=config.save_strategy,
        save_total_limit=config.save_total_limit,
        load_best_model_at_end=config.load_best_model_at_end,
        metric_for_best_model=config.metric_for_best_model,
        logging_steps=config.logging_steps,
        report_to=config.report_to,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        peft_config=peft_config,
    )

    print("[INFO] Iniciando treino...")
    trainer.train()
    print("[INFO] Salvando adapter final...")
    trainer.save_model(f"{config.output_dir}/final")
    print("[OK] Fine-tuning concluído.")


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fine-tuning LoRA/QLoRA (Fase 7)"
    )
    parser.add_argument(
        "--model", default="meta-llama/Llama-3.3-8B-Instruct",
        help="Modelo base HuggingFace",
    )
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lora-r", type=int, default=64)
    parser.add_argument("--lora-alpha", type=int, default=128)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--no-4bit", action="store_true", help="Desabilita quantização 4-bit")
    parser.add_argument(
        "--train-file", default="eval/finetune/train.jsonl",
        help="Dataset JSONL",
    )
    parser.add_argument(
        "--output-dir", default="eval/finetune/checkpoints",
        help="Diretório de saída dos checkpoints",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Apenas validar config + dataset, sem treinar",
    )
    args = parser.parse_args()

    config = LoRATrainingConfig(
        base_model=args.model,
        num_train_epochs=args.epochs,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        learning_rate=args.lr,
        use_4bit=not args.no_4bit,
        train_file=args.train_file,
        output_dir=args.output_dir,
    )

    print("=== LoRA Fine-tuning Config ===")
    print(json.dumps(asdict(config), indent=2, default=str))
    print()

    # Validate
    print("=== Validação ===")
    errors = validate_dependencies()
    if errors:
        print(f"[WARN] Dependências faltando (instale antes de treinar):")
        for e in errors:
            print(f"  - {e}")
        print()
        print("Para instalar:")
        print("  pip install torch transformers peft trl bitsandbytes datasets accelerate")
        print()
        if not args.validate_only:
            print("[FATAL] Não é possível treinar sem dependências.")
            return 1
    else:
        print("[OK] Todas as dependências instaladas")

    dataset_path = ROOT / config.train_file
    ds_error = validate_dataset(dataset_path)
    if ds_error:
        print(f"[WARN] Dataset: {ds_error}")
        if not args.validate_only:
            return 1
    else:
        print(f"[OK] Dataset válido: {dataset_path}")

    has_gpu, gpu_info = validate_gpu()
    print(f"[{'OK' if has_gpu else 'WARN'}] GPU: {gpu_info}")

    if args.validate_only:
        print("\n[OK] Validação completa (sem treino).")
        return 0

    if not has_gpu:
        print("[FATAL] Sem GPU — não é possível treinar.")
        return 1

    # Treino real
    print("\n=== Iniciando Treino ===")
    train(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())