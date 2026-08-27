"""Analisador estático de Terraform/HCL.

Regras heurísticas focadas nos problemas mais comuns e de maior impacto (segurança e
custo). Não substitui tfsec/checkov, mas dá findings acionáveis e explicáveis pela LLM.

Catálogo atual (7 regras):

SEGURANÇA:
  T1 - S3 sem server-side encryption
  T2 - Security Group ingress 0.0.0.0/0
  T3 - RDS sem storage_encrypted
  T4 - RDS sem Multi-AZ em ambiente de produção

FINOPS:
  T5 - Recurso de compute sem tags/labels (governança/custo)
  T6 - Instância oversized (m5/m4/c5 families sem justification para tamanho)

OPERATIONS:
  T7 - Recurso crítico sem lifecycle/prevent_destroy

RELIABILITY:
  (extra) - Terraform sem backend remoto de state (state local)
"""

from __future__ import annotations

import re
from typing import Any

from cip.agents.models import Finding
from cip.logging import get_logger

log = get_logger(__name__)


def _parse(payload: str) -> dict[str, Any]:
    import hcl2

    return hcl2.loads(payload)


def _unq(value: Any) -> Any:
    """Remove aspas literais que algumas versões do hcl2 preservam em chaves/valores.

    hcl2 retorna tudo como lista: from_port=[22], cidr_blocks=[["0.0.0.0/0"]].
    _unq desembrulha listas para extrair o valor escalar (string/int/bool) quando
    a lista tem um único elemento, e aplica strip(") recursivamente.
    """
    if isinstance(value, str):
        return value.strip().strip('"')
    if isinstance(value, list):
        # Achata 1 nível se for lista de strings simples
        if len(value) == 1:
            return _unq(value[0])
        # Caso especial: cidr_blocks é lista de strings dentro de lista
        if all(isinstance(v, list) and len(v) == 1 and isinstance(v[0], str) for v in value):
            return [v[0] for v in value]
        return [_unq(v) for v in value]
    return value


def _iter_resources(parsed: dict[str, Any]):
    for block in parsed.get("resource", []):
        for rtype_raw, bodies in block.items():
            rtype = _unq(rtype_raw)
            # bodies pode ser dict (nome->corpo) ou lista
            if isinstance(bodies, dict):
                for name_raw, body in bodies.items():
                    yield rtype, _unq(name_raw), (body if isinstance(body, dict) else {})
            elif isinstance(bodies, list):
                for item in bodies:
                    if isinstance(item, dict):
                        for name_raw, body in item.items():
                            yield rtype, _unq(name_raw), (body if isinstance(body, dict) else {})


# Tipos de instância grandes (>=$0.10/h em on-demand) — candidates a oversized
_LARGE_INSTANCE_PREFIXES = (
    "m5.", "m5n.", "m6i.", "m6a.", "c5.", "c5n.", "c6i.", "r5.", "r6i.",
    "x2.", "x1.", "p3.", "p4.", "g4.", "g5.",
)


def _is_large_instance_type(instance_type: str) -> tuple[bool, float]:
    """Retorna (is_large, on_demand_usd_per_hour)."""
    for prefix in _LARGE_INSTANCE_PREFIXES:
        if instance_type.startswith(prefix):
            # Estimativa grosseira — refinar com Cost Explorer quando disponível
            if ".large" in instance_type:
                return True, 0.10
            if ".xlarge" in instance_type:
                return True, 0.20
            if ".2xlarge" in instance_type:
                return True, 0.40
            if ".4xlarge" in instance_type:
                return True, 0.80
            return True, 0.30
    return False, 0.0


def analyze(payload: str) -> list[Finding]:
    try:
        parsed = _parse(payload)
    except Exception as exc:
        log.warning("hcl_parse_failed", error=str(exc))
        return []

    findings: list[Finding] = []

    for rtype, name, body in _iter_resources(parsed):
        ref = f"{rtype}.{name}"

        # ─────────────────────────────────────────────────────────────────────
        # T1 — S3 sem criptografia server-side
        # ─────────────────────────────────────────────────────────────────────
        if rtype == "aws_s3_bucket" and "server_side_encryption_configuration" not in body:
            findings.append(
                Finding(
                    title=f"S3 bucket sem criptografia server-side ({ref})",
                    severity="high",
                    domain="security",
                    description="Bucket S3 sem SSE configurado explicitamente — dados em repouso desprotegidos.",
                    recommendation=(
                        "Habilite SSE (aws:kms para dados sensíveis ou AES256). "
                        "Adicione bucket_key_enabled e force SSL via bucket policy."
                    ),
                    effort="low",
                    references=[
                        "[aws, s3, Well-Architected: Security > Data protection]",
                        "[aws, s3, Server-side encryption best practices]",
                    ],
                )
            )

        # ─────────────────────────────────────────────────────────────────────
        # T2 — Security group ingress 0.0.0.0/0
        # ─────────────────────────────────────────────────────────────────────
        if rtype in {"aws_security_group", "aws_vpc_security_group_ingress_rule"}:
            ingress = body.get("ingress", [])
            ingress = ingress if isinstance(ingress, list) else [ingress]
            for rule in ingress:
                rule_dict = rule if isinstance(rule, dict) else {}
                cidrs = _unq(rule_dict.get("cidr_blocks", []) or [])
                ipv6 = _unq(rule_dict.get("ipv6_cidr_blocks", []) or [])
                if "0.0.0.0/0" in cidrs or "::/0" in ipv6:
                    from_port = rule_dict.get("from_port")
                    to_port = rule_dict.get("to_port")
                    # hcl2 retorna valores como listas; _unq já desembrulha
                    fp = _unq(from_port) if from_port is not None else None
                    tp = _unq(to_port) if to_port is not None else None
                    port_str = (
                        f"porta {fp}-{tp}"
                        if fp is not None
                        else "todas as portas"
                    )
                    findings.append(
                        Finding(
                            title=f"Security group aberto para a internet ({ref}, {port_str})",
                            severity="critical",
                            domain="security",
                            description=(
                                f"Regra de ingress permite 0.0.0.0/0. "
                                "Exposição pública da workload — risco de ataque direto."
                            ),
                            recommendation=(
                                "Restrinja o CIDR ao range corporativo/VPN. "
                                "Para SSH/RDP (22/3389) use SSM Session Manager ou Bastion em subnet privada. "
                                "Considere AWS Shield + WAF para mitigação adicional."
                            ),
                            effort="low",
                            financial_impact_usd=0.0,
                            references=[
                                "[aws, vpc, Well-Architected: Security > Network protection]",
                                "[aws, ec2, Security group best practices]",
                            ],
                        )
                    )

        # ─────────────────────────────────────────────────────────────────────
        # T3 — RDS sem storage_encrypted
        # ─────────────────────────────────────────────────────────────────────
        if rtype == "aws_db_instance" and not body.get("storage_encrypted"):
            findings.append(
                Finding(
                    title=f"RDS sem criptografia de storage ({ref})",
                    severity="high",
                    domain="security",
                    description="storage_encrypted não habilitado — dados em repouso desprotegidos.",
                    recommendation=(
                        "Habilite storage_encrypted=true (KMS). "
                        "Para Aurora use storage_encrypted=true no cluster. "
                        "Para requisitos regulatórios (PCI/HIPAA) use customer-managed CMK."
                    ),
                    effort="medium",
                    references=[
                        "[aws, rds, Well-Architected: Security > Data protection]",
                        "[aws, rds, Encrypting Amazon RDS resources]",
                    ],
                )
            )

        # ─────────────────────────────────────────────────────────────────────
        # T4 — RDS sem Multi-AZ em produção
        # ─────────────────────────────────────────────────────────────────────
        if rtype == "aws_db_instance":
            multi_az_raw = _unq(body.get("multi_az"))
            is_multi = multi_az_raw is True or (
                isinstance(multi_az_raw, str) and multi_az_raw.lower() == "true"
            )
            if not is_multi:
                # hcl2 retorna tags como dict (valor pode reter aspas literais:
                # {"Environment": '"prod"'}) — normalizar via _unq antes de comparar.
                tags_raw = body.get("tags")
                env = ""
                if isinstance(tags_raw, list) and tags_raw:
                    first = tags_raw[0]
                    if isinstance(first, dict):
                        env = str(
                            _unq(first.get("Environment") or first.get("env")) or ""
                        ).lower()
                elif isinstance(tags_raw, dict):
                    env = str(
                        _unq(tags_raw.get("Environment") or tags_raw.get("env")) or ""
                    ).lower()
                if env in {"prod", "production", "prd"}:
                    findings.append(
                        Finding(
                            title=f"RDS em produção sem Multi-AZ ({ref})",
                            severity="high",
                            domain="reliability",
                            description=(
                                "RDS marcado como produção (tag Environment=prod) sem Multi-AZ. "
                                "Falha de AZ causa indisponibilidade até failover manual."
                            ),
                            recommendation=(
                                "Habilite multi_az=true para SLA de 99.95%. "
                                "Para Aurora, considere Aurora Multi-Master para HA ativa-ativa."
                            ),
                            effort="medium",
                            references=[
                                "[aws, rds, Multi-AZ deployments for high availability]",
                                "[aws, rds, Well-Architected: Reliability]",
                            ],
                        )
                    )

        # ─────────────────────────────────────────────────────────────────────
        # T5 — Compute sem tags/labels
        # ─────────────────────────────────────────────────────────────────────
        if rtype in {"aws_instance", "google_compute_instance", "azurerm_linux_virtual_machine", "azurerm_windows_virtual_machine"}:
            tags = body.get("tags")
            labels = body.get("labels")
            if not tags and not labels:
                # Estimativa conservadora: $50/mês de alocação errada de custo
                findings.append(
                    Finding(
                        title=f"Recurso de compute sem tags/labels ({ref})",
                        severity="medium",
                        domain="finops",
                        description=(
                            "Sem tags/labels, alocação de custo e governança ficam prejudicadas. "
                            "Impossível cobrar de times/projetos ou detectar recursos órfãos."
                        ),
                        recommendation=(
                            "Adicione tags obrigatórias: Owner, Environment (dev/stg/prod), "
                            "CostCenter, Project. Padronize via Terraform variables ou AWS Organizations SCP."
                        ),
                        effort="low",
                        financial_impact_usd=50.0,
                        references=[
                            "[multi, governance, Cost allocation tags]",
                            "[aws, organizations, Tag policies]",
                        ],
                    )
                )

        # ─────────────────────────────────────────────────────────────────────
        # T6 — Instância oversized
        # ─────────────────────────────────────────────────────────────────────
        if rtype in {"aws_instance", "google_compute_instance"}:
            instance_type = _unq(body.get("instance_type") or body.get("machine_type"))
            if isinstance(instance_type, str) and instance_type:
                is_large, hourly_usd = _is_large_instance_type(instance_type)
                if is_large:
                    # Custo mensal: hourly * 24 * 30
                    monthly = hourly_usd * 24 * 30
                    # Direitosizing típico economiza 40-60% em instances grandes
                    potential_savings = monthly * 0.5
                    findings.append(
                        Finding(
                            title=f"Possível oversized em compute ({ref}: {instance_type})",
                            severity="medium",
                            domain="finops",
                            description=(
                                f"Instância grande ({instance_type}) sem tags de justificativa. "
                                f"Custo estimado ~${monthly:,.0f}/mês. "
                                "Workloads típicos em rightsizing reduzem 40-60% do custo."
                            ),
                            recommendation=(
                                "Verifique uso de CPU/memória no CloudWatch (mínimo 2 semanas). "
                                "Considere: rightsizing para tipo menor, "
                                "Savings Plans / Reserved Instances / Committed Use Discount, "
                                "ou migrar para família Graviton (m6g/c6g/r6g) — 20-40% mais barato."
                            ),
                            effort="medium",
                            financial_impact_usd=potential_savings,
                            references=[
                                "[aws, ec2, Rightsizing guidance]",
                                "[aws, compute, Savings Plans overview]",
                                "[aws, graviton, Migrating to AWS Graviton]",
                            ],
                        )
                    )

        # ─────────────────────────────────────────────────────────────────────
        # T7 — Sem lifecycle/prevent_destroy em recursos críticos
        # ─────────────────────────────────────────────────────────────────────
        if rtype in {"aws_s3_bucket", "aws_db_instance", "aws_rds_cluster"}:
            # hcl2: lifecycle=[{"prevent_destroy": [true]}]
            lifecycle_raw = body.get("lifecycle")
            has_prevent_destroy = False
            if isinstance(lifecycle_raw, list) and lifecycle_raw:
                for entry in lifecycle_raw:
                    if not isinstance(entry, dict):
                        continue
                    pd = entry.get("prevent_destroy")
                    pd_unwrapped = _unq(pd)
                    if pd_unwrapped is True or pd_unwrapped == "true":
                        has_prevent_destroy = True
                        break
            elif isinstance(lifecycle_raw, dict):
                pd = _unq(lifecycle_raw.get("prevent_destroy"))
                if pd is True or pd == "true":
                    has_prevent_destroy = True
            if not has_prevent_destroy:
                findings.append(
                    Finding(
                        title=f"Recurso crítico sem prevent_destroy ({ref})",
                        severity="medium",
                        domain="operations",
                        description=(
                            f"{rtype} sem lifecycle.prevent_destroy. "
                            "Um `terraform destroy` acidental apaga dados em produção."
                        ),
                        recommendation=(
                            "Adicione lifecycle { prevent_destroy = true } em recursos críticos "
                            "(DB, buckets com dados, KMS keys). Para state files, use remote backend com versioning."
                        ),
                        effort="low",
                        financial_impact_usd=0.0,
                        references=[
                            "[multi, terraform, Lifecycle meta-arguments]",
                            "[aws, s3, Versioning and lifecycle configuration]",
                        ],
                    )
                )

    # ─────────────────────────────────────────────────────────────────────────
    # EXTRA — Terraform sem backend remoto de state
    # ─────────────────────────────────────────────────────────────────────────
    if "terraform" in parsed:
        tf_blocks = parsed["terraform"]
        tf_blocks = tf_blocks if isinstance(tf_blocks, list) else [tf_blocks]
        has_backend = any("backend" in b for b in tf_blocks if isinstance(b, dict))
        if not has_backend:
            findings.append(
                Finding(
                    title="Terraform sem backend remoto de state",
                    severity="medium",
                    domain="operations",
                    description=(
                        "State local dificulta trabalho em equipe e não tem lock. "
                        "Perda do arquivo state = perda total da infraestrutura gerenciada."
                    ),
                    recommendation=(
                        "Configure backend remoto: "
                        "AWS (S3 + DynamoDB lock), "
                        "GCP (GCS), "
                        "Azure (azurerm storage container). "
                        "Habilite versioning no bucket para recuperação."
                    ),
                    effort="medium",
                    financial_impact_usd=0.0,
                    references=[
                        "[multi, terraform, State management best practices]",
                        "[aws, s3, Terraform state bucket configuration]",
                    ],
                )
            )

    return findings