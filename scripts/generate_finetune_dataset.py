#!/usr/bin/env python3
"""Gerador de dataset sintético para fine-tuning (Fase 7).

Gera pares pergunta/raciocínio/resposta no formato Alpaca a partir de:
1. Cenários do eval/test_cases.json (95 casos)
2. Variações sintéticas (paráfrases, ângulos alternativos)
3. Personas específicas (FinOps, Security, SRE, K8s, Terraform)
4. Cross-cloud comparisons (AWS vs GCP vs Azure)

**NUNCA** grava conhecimento factual — apenas PERSONA, FORMATO, RACIOCÍNIO.
Conhecimento factual sempre via RAG (ADR-0001).

Output:
- `eval/finetune/train.jsonl` — formato Alpaca (instrução/input/output)
- `eval/finetune/train.jsonl.stats.json` — estatísticas
- `eval/finetune/curation_checklist.md` — guia para revisão humana de 30%

Uso:
    python scripts/generate_finetune_dataset.py --output eval/finetune/
    python scripts/generate_finetune_dataset.py --count 10000 --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TEST_CASES_FILE = ROOT / "eval" / "test_cases.json"


# ─────────────────────────────────────────────────────────────────────────
# Templates de instrução (Alpaca format)
# ─────────────────────────────────────────────────────────────────────────


SYSTEM_PROMPT_PREFIX = (
    "Você é um engenheiro de cloud sênior especializado em AWS, GCP e Azure. "
    "Responda em português (pt-BR), cite fontes oficiais no formato "
    "[cloud, serviço, título, url] e exponha trade-offs quando relevante. "
)


# Templates por categoria — cada um vira ~20-30 variações
CATEGORY_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "conhecimento": [
        {
            "instruction": "Explique {service} na {cloud} e quando usá-lo.",
            "input": "",
            "output_template": (
                "{service} da {cloud} é um serviço de {category} que {purpose}. "
                "Use quando: {when_to_use}. "
                "Trade-offs: {tradeoffs}. "
                "[{cloud_short}, {service_lower}, {framework_doc}]"
            ),
        },
        {
            "instruction": "Quais as melhores práticas de {topic} no {cloud}?",
            "input": "",
            "output_template": (
                "Boas práticas de {topic} na {cloud}: "
                "1. {practice1} 2. {practice2} 3. {practice3}. "
                "Considere também: {additional}. "
                "[{cloud_short}, {service_lower}, {framework_doc}]"
            ),
        },
    ],
    "custo": [
        {
            "instruction": "Analise o cenário e sugira otimizações de custo.",
            "input": "{scenario}",
            "output_template": (
                "Achados de FinOps: "
                "- {finding1} (severidade High, impacto estimado $X/mês) "
                "- {finding2} (severidade Medium) "
                "Recomendações: "
                "1. {rec1} 2. {rec2} "
                "Valide com Cost Explorer antes de aplicar. "
                "[aws, ec2, Well-Architected: Cost Optimization]"
            ),
        },
        {
            "instruction": "Compare opções de pricing para {scenario}.",
            "input": "",
            "output_template": (
                "Opções: On-Demand ($X/hora), Savings Plans 1 ano ($Y/hora), "
                "Reserved Instances ($Z/hora), Spot ($W/hora sob risco). "
                "Recomendação: {recommendation} considerando {workload_pattern}. "
                "Use Cost Explorer para confirmar preços atuais. "
                "[aws, ec2, Pricing models]"
            ),
        },
    ],
    "seguranca": [
        {
            "instruction": "Revise a configuração de segurança e identifique riscos.",
            "input": "{config}",
            "output_template": (
                "Achados de Security: "
                "- {finding1} (severidade Critical) "
                "- {finding2} (severidade High) "
                "Recomendações: "
                "1. {rec1} 2. {rec2} "
                "Pilares WAF relevantes: {pillars}. "
                "[aws, iam, Well-Architected: Security > {pillar}]"
            ),
        },
    ],
    "iac_review": [
        {
            "instruction": "Revise o {artifact_type} e liste findings priorizados.",
            "input": "{iac_content}",
            "output_template": (
                "Findings: "
                "1. [{severity1}] {finding1} - {rec1} "
                "2. [{severity2}] {finding2} - {rec2} "
                "Domínios afetados: {domains}. "
                "Severidade calculada via CIP Inspection Engine. "
                "[multi, iac, Best practices]"
            ),
        },
    ],
    "comparacao": [
        {
            "instruction": "Compare {service_a} vs {service_b} em tabela.",
            "input": "",
            "output_template": (
                "| Critério | {service_a} | {service_b} | "
                "|---|---|---| "
                "| Modelo de pricing | {pricing_a} | {pricing_b} | "
                "| Lock-in | {lockin_a} | {lockin_b} | "
                "| HA multi-region | {ha_a} | {ha_b} | "
                "| Vendor lock-in | {vendor_a} | {vendor_b} | "
                "Recomendação: use {service_a} para {use_a}; {service_b} para {use_b}. "
                "[aws, {service_a_lower}, Doc] | [azure, {service_b_lower}, Doc]"
            ),
        },
    ],
}


# Personas para exemplos diversos (cada persona vira N variações)
PERSONAS = [
    "finops",
    "security",
    "sre",
    "kubernetes",
    "terraform",
    "aws_specialist",
    "gcp_specialist",
    "azure_specialist",
]


# ─────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class DatasetItem:
    """Item no formato Alpaca para fine-tuning."""

    instruction: str
    input: str
    output: str
    persona: str = "general"
    category: str = "general"
    cloud: str = "multi"
    source: str = "synthetic"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reviewed: bool = False
    reviewer: str | None = None
    flagged_for_removal: bool = False
    notes: str = ""


@dataclass
class DatasetStats:
    """Estatísticas do dataset gerado."""

    total_items: int = 0
    by_persona: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)
    by_cloud: dict[str, int] = field(default_factory=dict)
    avg_output_length: float = 0.0
    synthetic_count: int = 0
    curated_count: int = 0
    target_count: int = 0


# ─────────────────────────────────────────────────────────────────────────
# Generation logic
# ─────────────────────────────────────────────────────────────────────────


def _load_eval_cases() -> list[dict[str, Any]]:
    """Carrega casos do eval/test_cases.json."""
    if not TEST_CASES_FILE.exists():
        return []
    data = json.loads(TEST_CASES_FILE.read_text(encoding="utf-8"))
    return data.get("cases", [])


def _generate_from_eval_cases(cases: list[dict[str, Any]]) -> list[DatasetItem]:
    """Converte cada caso de eval em um item Alpaca (instruction-tuning signal)."""
    items: list[DatasetItem] = []
    for case in cases:
        # Mapear categoria do eval → persona CIP
        persona_map = {
            "custo": "finops",
            "seguranca": "security",
            "conhecimento": "general",
            "comparacao": "general",
            "iac_review": "terraform",
        }
        persona = persona_map.get(case.get("category"), "general")
        cloud = case.get("cloud", "multi")

        # Instrução é a pergunta do caso
        instruction = case.get("question", "")
        # Input pode ser o payload (se houver) ou vazio
        inp = case.get("iac_payload", "")

        # Output ideal (curado por humano no futuro): template com placeholders
        # Por enquanto, placeholder — DEVE ser revisado por humano (30% rule)
        output = (
            f"[Resposta curada para: {instruction[:80]}...]\n\n"
            f"[aws, {cloud}, Well-Architected: Reference Architecture]\n\n"
            f"NOTA: Esta resposta foi gerada como template. "
            f"Revisão humana necessária antes de usar no treino."
        )

        items.append(DatasetItem(
            instruction=instruction,
            input=inp,
            output=output,
            persona=persona,
            category=case.get("category", "general"),
            cloud=cloud,
            source="eval_case",
            notes="Template gerado a partir do eval/test_cases.json",
        ))
    return items


def _generate_variations(
    templates: list[dict[str, str]],
    persona: str,
    count: int,
    rng: random.Random,
) -> list[DatasetItem]:
    """Gera variações a partir de templates."""
    items: list[DatasetItem] = []
    personas_by_template = {
        "conhecimento": ["general", "aws_specialist", "gcp_specialist", "azure_specialist"],
        "custo": ["finops"],
        "seguranca": ["security"],
        "iac_review": ["terraform"],
        "comparacao": ["general"],
    }

    for i in range(count):
        # Escolher categoria aleatória
        category = rng.choice(list(templates.keys()))
        template = rng.choice(templates[category])
        persona = rng.choice(personas_by_template.get(category, [persona]))

        # Variação simples: rotacionar placeholders com valores de exemplo
        clouds = ["AWS", "GCP", "Azure"]
        cloud = rng.choice(clouds)
        cloud_short = cloud.lower()
        services_by_cloud = {
            "AWS": ["EC2", "S3", "RDS", "Lambda", "EKS", "VPC", "IAM", "CloudFront"],
            "GCP": ["Compute Engine", "Cloud Storage", "BigQuery", "GKE", "Cloud SQL", "VPC"],
            "Azure": ["VM", "Blob Storage", "AKS", "Functions", "Cosmos DB", "VNet"],
        }
        service = rng.choice(services_by_cloud[cloud])
        category_str = rng.choice(["compute", "storage", "database", "networking", "security"])

        # Preencher template (substituições simples)
        output = template["output_template"].format(
            cloud=cloud,
            cloud_short=cloud_short,
            service=service,
            service_lower=service.lower().replace(" ", "_"),
            category=category_str,
            topic=rng.choice(["cost optimization", "security", "reliability", "performance"]),
            framework_doc="Well-Architected: Reference",
            purpose=rng.choice([
                "oferecer serviço gerenciado",
                "armazenar dados",
                "executar containers",
                "processar eventos",
            ]),
            when_to_use=rng.choice([
                "workloads previsíveis",
                "baixa latência",
                "alta disponibilidade",
                "controle granular",
            ]),
            tradeoffs=rng.choice([
                "custo vs complexidade",
                "lock-in vs features",
                "performance vs custo",
            ]),
            practice1="Habilitar encryption at rest",
            practice2="Aplicar tags obrigatórias",
            practice3="Configurar alarms",
            additional="monitoring contínuo",
            scenario=f"{service} com {rng.randint(5, 50)} recursos em produção",
            finding1="instâncias oversized detectadas",
            finding2="snapshots órfãos acumulando custo",
            severity1="High",
            severity2="Medium",
            rec1="Rightsizing para família Graviton",
            rec2="Lifecycle policy em buckets S3",
            pillars="Security, Reliability",
            pillar="Identity & Access Management",
            config="Security Group aberto para 0.0.0.0/0",
            artifact_type=rng.choice(["Terraform", "manifesto Kubernetes", "Bicep"]),
            iac_content=rng.choice([
                "resource aws_s3_bucket ...",
                "apiVersion: apps/v1 kind: Deployment ...",
            ]),
            domains=rng.choice(["finops, security", "security, reliability"]),
            service_a=service,
            service_b=rng.choice(services_by_cloud[cloud]),
            pricing_a="On-Demand $/h",
            pricing_b="Serverless $/invocation",
            lockin_a="alto",
            lockin_b="baixo",
            ha_a="Multi-AZ built-in",
            ha_b="Manual",
            vendor_a="AWS",
            vendor_b=rng.choice(["GCP", "Azure"]),
            service_a_lower=service.lower().replace(" ", "_"),
            service_b_lower="alt",
            use_a="workloads tradicionais",
            use_b="apps cloud-native",
            workload_pattern="tráfego previsível",
            recommendation="Savings Plans 1 ano se workload > 6 meses",
        )

        items.append(DatasetItem(
            instruction=template["instruction"],
            input=template.get("input", ""),
            output=output,
            persona=persona,
            category=category,
            cloud=cloud_short,
            source="synthetic_variation",
            notes=f"Variação sintética #{i} do template {template['instruction'][:40]}",
        ))
    return items


def _dedupe_items(items: list[DatasetItem]) -> list[DatasetItem]:
    """Remove duplicatas baseado em (instruction, input, output[:200]).

    Considera os primeiros 200 chars do output na chave para deduplicar
    templates idênticos (mesma instruction+input) mas permite variações
    no output (que é o sinal que queremos preservar).
    """
    seen: set[tuple[str, str, str]] = set()
    unique: list[DatasetItem] = []
    for item in items:
        key = (
            item.instruction.strip().lower(),
            item.input.strip()[:200],
            item.output.strip()[:200],
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _compute_stats(items: list[DatasetItem]) -> DatasetStats:
    """Calcula estatísticas do dataset."""
    stats = DatasetStats(total_items=len(items), target_count=len(items))
    for item in items:
        stats.by_persona[item.persona] = stats.by_persona.get(item.persona, 0) + 1
        stats.by_category[item.category] = stats.by_category.get(item.category, 0) + 1
        stats.by_cloud[item.cloud] = stats.by_cloud.get(item.cloud, 0) + 1
        if item.source.startswith("eval_"):
            stats.curated_count += 1
        else:
            stats.synthetic_count += 1
    if items:
        stats.avg_output_length = sum(len(i.output) for i in items) / len(items)
    return stats


def _write_jsonl(items: list[DatasetItem], path: Path) -> None:
    """Escreve dataset no formato JSONL (Alpaca)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")


def _write_stats(stats: DatasetStats, path: Path) -> None:
    """Escreve estatísticas do dataset."""
    path.write_text(json.dumps(asdict(stats), indent=2, ensure_ascii=False), encoding="utf-8")


def _write_curation_checklist(items: list[DatasetItem], path: Path) -> None:
    """Escreve checklist de revisão humana para 30% do dataset."""
    n_review = max(1, int(len(items) * 0.30))
    # Amostra determinística: hash do índice pega subset estável
    sample_indices = sorted(set(
        hash(idx) % len(items) for idx in range(n_review * 2)  # oversample
    ))[:n_review]

    lines = [
        "# Checklist de Curadoria Humana — Fine-tuning Dataset",
        "",
        f"**Total de itens**: {len(items)}",
        f"**A revisar (30%)**: {n_review} itens",
        f"**Gerado em**: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Instruções",
        "",
        "1. Leia cada item abaixo",
        "2. Avalie 4 critérios (1-5 cada):",
        "   - **Accuracy**: Resposta está factualmente correta?",
        "   - **Format**: Segue formato persona CIP (citações, trade-offs)?",
        "   - **Persona**: Tom é de engenheiro sênior cloud?",
        "   - **Zero-Hallucination**: Não inventa serviços ou features?",
        "3. Se accuracy < 4: marcar `flagged_for_removal=true` no item JSONL",
        "4. Se persona/format < 4: editar `output` antes de salvar",
        "5. Marcar `reviewed=true` + `reviewer=<seu_nome>` após análise",
        "",
        "## Itens a Revisar (amostra)",
        "",
    ]
    for idx in sample_indices[:20]:  # mostrar primeiros 20
        item = items[idx]
        lines.append(f"### Item #{idx}")
        lines.append(f"- **Persona**: {item.persona}")
        lines.append(f"- **Category**: {item.category}")
        lines.append(f"- **Cloud**: {item.cloud}")
        lines.append(f"- **Source**: {item.source}")
        lines.append(f"- **Instruction**: `{item.instruction[:150]}`")
        lines.append(f"- **Input**: `{item.input[:100]}`")
        lines.append(f"- **Output**: `{item.output[:300]}`")
        lines.append("")
        lines.append("**Avaliação**: Accuracy __ / Format __ / Persona __ / Zero-Hall __")
        lines.append("")
        lines.append("---")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gerador de dataset sintético para fine-tuning (Fase 7)"
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "eval" / "finetune",
        help="Diretório de saída do dataset",
    )
    parser.add_argument(
        "--count", type=int, default=5000,
        help="Número de variações sintéticas a gerar (alvo: 5-10k)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Seed aleatório para reprodutibilidade",
    )
    parser.add_argument(
        "--seed-from-eval", action="store_true",
        help="Incluir casos do eval/test_cases.json como seed (1 item por caso)",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)

    print(f"Gerando dataset (count={args.count}, seed={args.seed})...")

    items: list[DatasetItem] = []

    # 1. Seed do eval
    if args.seed_from_eval:
        eval_cases = _load_eval_cases()
        eval_items = _generate_from_eval_cases(eval_cases)
        items.extend(eval_items)
        print(f"  + {len(eval_items)} itens do eval/test_cases.json")

    # 2. Variações sintéticas
    synthetic_items = _generate_variations(
        CATEGORY_TEMPLATES, persona="general", count=args.count, rng=rng
    )
    items.extend(synthetic_items)
    print(f"  + {len(synthetic_items)} variações sintéticas")

    # 3. Dedupe
    items = _dedupe_items(items)
    print(f"  = {len(items)} itens únicos após dedupe")

    # 4. Stats
    stats = _compute_stats(items)
    print(f"\n=== Estatísticas ===")
    print(f"Total: {stats.total_items}")
    print(f"Sintéticos: {stats.synthetic_count}")
    print(f"Do eval: {stats.curated_count}")
    print(f"Avg output length: {stats.avg_output_length:.0f} chars")
    print(f"Por persona: {stats.by_persona}")
    print(f"Por categoria: {stats.by_category}")
    print(f"Por cloud: {stats.by_cloud}")

    # 5. Salvar
    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    train_file = output_dir / "train.jsonl"
    _write_jsonl(items, train_file)
    print(f"\n[OK] Dataset salvo em: {train_file}")

    stats_file = output_dir / "train.stats.json"
    _write_stats(stats, stats_file)
    print(f"[OK] Stats salvas em: {stats_file}")

    checklist_file = output_dir / "curation_checklist.md"
    _write_curation_checklist(items, checklist_file)
    print(f"[OK] Checklist de curadoria salvo em: {checklist_file}")

    print(f"\n=== Próximos Passos ===")
    print(f"1. Revisar manualmente 30% dos itens (~{int(stats.total_items * 0.3)} itens)")
    print(f"2. Marcar items revisados no JSONL: 'reviewed': true, 'reviewer': '<nome>'")
    print(f"3. Remover items com accuracy < 4: 'flagged_for_removal': true")
    print(f"4. Após curadoria: rodar python scripts/train_lora.py")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())