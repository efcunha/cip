"""Classificador de intenção (roteamento) — heurístico com fallback.

Estratégia: heurística barata por palavras-chave para o MVP. Em produção pode-se
substituir por classificação via LLM (function calling) sem mudar a interface.

Catálogo de especialistas (8 total, ver prompts/specialists.py):
  Provedor (3): aws, gcp, azure — roteados por cloud detectado
  Domínio (5): finops, security, sre, kubernetes, terraform — roteados por intent/tópico

Regras de roteamento:
  - 1-3 especialistas por query (nunca todos)
  - Sempre combina provedor-cloud + domínio quando ambos são identificáveis
  - IAC_REVIEW → terraform + kubernetes (se K8s detectado) + security
  - COST → finops (sempre) + provedor-cloud
  - ENVIRONMENT → finops + security + sre (full stack analysis)
  - KNOWLEDGE → provedor-cloud (se detectado) + domínio relevante
  - COMPARE → todos os provedores detectados + finops
"""

from __future__ import annotations

import re

from cip.agents.models import AnalysisPlan, Intent

# ─────────────────────────────────────────────────────────────────────────
# Keywords
# ─────────────────────────────────────────────────────────────────────────

_CLOUD_KEYWORDS = {
    "aws": [
        "aws", "ec2", "s3", "eks", "ecs", "lambda", "rds", "aurora", "dynamodb",
        "cloudfront", "vpc", "iam", "cloudwatch", "cloudtrail", "route53",
        "guardduty", "security hub",
        # NOTE: "well-architected" NÃO é keyword — é ambíguo entre AWS/Azure/GCP
        # (todos têm "Well-Architected Framework"). A detecção de cloud se apoia
        # na palavra "aws"/"azure"/"gcp" explícita da pergunta (Round 22.1).
    ],
    "azure": [
        "azure", "aks", "vnet", "nsg", "blob", "entra", "defender", "advisor",
        "key vault", "app service", "container apps", "functions",
    ],
    "gcp": [
        "gcp", "gke", "bigquery", "cloud sql", "alloydb", "compute engine",
        "cloud run", "cloud functions", "recommender", "security command center",
        "cloud storage", "pub/sub", "architecture framework",
    ],
}

_DOMAIN_KEYWORDS = {
    "finops": [
        "custo", "custos", "economizar", "economia", "cost", "gasto", "gastos",
        "fatura", "billing", "rightsizing", "savings plans", "reserved",
        "spot", "orçamento", "orcamento", "finops", "$", "preço", "preco",
    ],
    "security": [
        "segurança", "seguranca", "security", "iam", "rbac", "least privilege",
        "criptografia", "encriptação", "encriptacao", "encryption", "secrets",
        "vulnerability", "vulnerabilidade", "compliance", "conformidade",
        "pci", "hipaa", "lgpd", "gdpr", "public", "público", "publico", "sensitive",
        "zero trust", "policy-as-code", "supply chain",
    ],
    "sre": [
        "sre", "confiabilidade", "reliability", "sli", "sla", "monitoring",
        "observabilidade", "observability", "métricas", "metricas",
        "alertas", "alerts", "backup", "ha ", "high availability",
        "alta disponibilidade", "multi-az", "spof", "single point",
    ],
    # Round 18: reliability engineering profundo (SRE básico + SLO design + chaos + DR)
    "reliability": [
        "slo", "slis", "error budget", "postmortem", "post-mortem",
        "chaos", "fault injection", "circuit breaker", "bulkhead",
        "multi-region", "rpo", "rto", "active-active", "active-passive",
        "pilot light", "warm standby", "disaster recovery", "failover",
        "runbook", "on-call", "incident", "mttr", "mtbf",
        "capacidade", "capacity planning", "headroom",
    ],
    "kubernetes": [
        "kubernetes", "k8s", "pod", "deployment", "statefulset", "daemonset",
        "helm", "operator", "ingress", "hpa", "vpa", "cluster-autoscaler",
        "networkpolicy", "podsecurity", "cni", "service mesh", "istio",
        # Round 22+: NÃO incluir eks/aks/gke — elas já vivem em cloud keywords
        # e disparariam IAC_REVIEW via IAC_KEYWORDS = terraform + kubernetes.
        # Se a query cita EKS + kubernetes explícito ("kubernetes no EKS"),
        # o termo "kubernetes" sozinho já dispara.
    ],
    "terraform": [
        "terraform", ".tf", "cloudformation", "bicep", "pulumi", "opentofu",
        "hcl", "iac", "infraestrutura como código",
    ],
    # Round 18: Platform Engineering (IDPs, Golden Paths, self-service)
    "platform_engineering": [
        "platform engineering", "idp", "internal developer platform",
        "golden path", "self-service", "developer portal", "backstage",
        "crossplane", "humanitec", "cortex", "devex", "developer experience",
        "platform as a product", "service catalog", "developer onboarding",
        "internal tools", "paved path",
    ],
    # Round 22: Software Architecture patterns — microserviços, event-driven,
    # padrões de resiliência. Roteado quando a pergunta cita o VOCABULÁRIO
    # do domínio (não serviços específicos de cloud).
    "software_architecture": [
        "microsserviço", "microsserviços", "microsservicos", "microservice", "microservices",
        "monolito", "monolitos", "monolith", "monolítico", "monolithic", "strangler",
        "cqrs", "event sourcing", "event-sourcing", "saga", "saga pattern",
        "outbox", "bff", "backend for frontend",
        "bounded context", "bounded-context", "domain-driven", "ddd",
        "service mesh", "service discovery", "api gateway",
        "circuit breaker", "circuit-breaker", "bulkhead", "retry", "jitter",
        "pub/sub", "pubsub", "message broker", "kafka", "rabbitmq",
        "event-driven", "event driven", "eventual consistency",
        "idempotência", "idempotency", "idempotent",
        "design pattern", "design patterns", "padrão de projeto",
        "padrões de projeto", "padrões de arquitetura", "arquitetura de software",
        "arquitetura de microsserviços", "arquitetura distribuída",
        "software architecture", "distributed systems",
        "12-factor", "12 factor", "twelve-factor",
        "saga orchestration", "saga choreography",
    ],
}

_COST_KEYWORDS = _DOMAIN_KEYWORDS["finops"]
_IAC_KEYWORDS = _DOMAIN_KEYWORDS["terraform"] + _DOMAIN_KEYWORDS["kubernetes"]
_COMPARE_KEYWORDS = ["comparar", "comparação", "comparacao", "versus", " vs ", "diferença entre", "diferenca entre", "vs."]
_ENV_KEYWORDS = [
    "analise meu", "analisar meu", "meu ambiente", "minha conta",
    "revise meu", "revisar", "inventário", "inventario", "ambiente atual",
    "minha infra", "nossa infra",
]


# ─────────────────────────────────────────────────────────────────────────
# Detection helpers
# ─────────────────────────────────────────────────────────────────────────


def _detect_clouds(text: str) -> list[str]:
    t = text.lower()
    found = [c for c, kws in _CLOUD_KEYWORDS.items() if any(k in t for k in kws)]
    return found


def _detect_domains(text: str) -> list[str]:
    t = text.lower()
    return [d for d, kws in _DOMAIN_KEYWORDS.items() if any(k in t for k in kws)]


def _cap_specialists(specialists: list[str], max_n: int = 3) -> list[str]:
    """Limita especialistas a max_n, priorizando cloud_provider primeiro.

    Round 22+: NÃO aplicamos bump automático aqui — respeitamos o max_n
    do caller. KNOWLEDGE (com software_architecture + cloud) usa max_n=4
    explicitamente para acomodar múltiplos domínios relevantes.
    """
    # Ordem: cloud_provider > domain
    providers = [s for s in specialists if s in _CLOUD_KEYWORDS]
    domains = [s for s in specialists if s not in _CLOUD_KEYWORDS]
    ordered = providers + domains
    # Dedup preservando ordem
    seen: set[str] = set()
    deduped: list[str] = []
    for s in ordered:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped[:max_n]


# ─────────────────────────────────────────────────────────────────────────
# Main classifier
# ─────────────────────────────────────────────────────────────────────────


def classify(question: str, has_iac_payload: bool = False) -> AnalysisPlan:
    t = question.lower()
    clouds = _detect_clouds(t)
    domains = _detect_domains(t)

    # IAC review (Terraform/K8s) — specialists: terraform + kubernetes (se K8s detectado) + security
    # Round 22+: se a query cita padrões de software_architecture (microservices,
    # circuit breaker, CQRS…) E kubernetes, NÃO entra em IAC_REVIEW — o usuário
    # quer discutir o ORQUESTRADOR, não revisar manifestos. Mantém KNOWLEDGE.
    has_iac_trigger = has_iac_payload or any(k in t for k in _IAC_KEYWORDS)
    has_arch_signal = any(
        k in t for k in _DOMAIN_KEYWORDS["software_architecture"]
    )
    if has_iac_trigger and has_arch_signal and not has_iac_payload:
        # Cai pra KNOWLEDGE abaixo (deixa o fluxo continuar)
        pass
    elif has_iac_trigger:
        iac_specialists = ["terraform", "security"]
        # Se há menção a K8s nos IAC keywords ou payload parece ser k8s (heurística simples)
        if any(k in t for k in _DOMAIN_KEYWORDS["kubernetes"]):
            iac_specialists.insert(1, "kubernetes")
        # Adiciona provedor cloud se detectado
        if clouds:
            iac_specialists = [clouds[0]] + iac_specialists
        return AnalysisPlan(
            intent=Intent.IAC_REVIEW,
            clouds=clouds,
            specialists=_cap_specialists(iac_specialists),
            use_inspection=True,
            use_tools=False,
        )

    # Compare (multi-cloud) — todos provedores detectados + finops (se custo)
    # Round 22.1: se a query tem SINAL de arquitetura (cqrs, saga, circuit
    # breaker, monolito vs microservices…), NÃO é comparação multi-cloud —
    # cai para KNOWLEDGE com o especialista software_architecture. Antes,
    # "Diferença entre CQRS e CRUD" disparava COMPARE (por "diferença entre")
    # e roteava para aws/gcp/azure, ignorando o domínio de arquitetura e
    # derrubando a accuracy da homologação.
    is_compare = any(k in t for k in _COMPARE_KEYWORDS) or len(clouds) >= 2
    if is_compare and not has_arch_signal:
        compare_specialists = list(clouds or ["aws", "gcp", "azure"])
        # Se pergunta envolve custo, adiciona finops
        if any(k in t for k in _COST_KEYWORDS):
            compare_specialists.append("finops")
        # Se envolve segurança
        elif any(k in t for k in _DOMAIN_KEYWORDS["security"]):
            compare_specialists.append("security")
        return AnalysisPlan(
            intent=Intent.COMPARE,
            clouds=clouds or ["aws", "gcp", "azure"],
            specialists=_cap_specialists(compare_specialists, max_n=4),
        )

    # Cost-focused
    if any(k in t for k in _COST_KEYWORDS):
        env = any(k in t for k in _ENV_KEYWORDS)
        cost_specialists = ["finops"]
        if clouds:
            cost_specialists = [clouds[0], "finops"]
        # Se a query também envolve security (ex: "economizar sem comprometer segurança")
        if any(k in t for k in _DOMAIN_KEYWORDS["security"]):
            if "security" not in cost_specialists:
                cost_specialists.append("security")
        return AnalysisPlan(
            intent=Intent.COST,
            clouds=clouds,
            specialists=_cap_specialists(cost_specialists),
            use_tools=env,  # usa tools ao vivo se for sobre o ambiente do usuário
        )

    # Environment analysis (full stack)
    if any(k in t for k in _ENV_KEYWORDS):
        env_specialists = ["finops", "security", "sre"]
        if clouds:
            env_specialists = [clouds[0]] + env_specialists
        return AnalysisPlan(
            intent=Intent.ENVIRONMENT,
            clouds=clouds,
            specialists=_cap_specialists(env_specialists),
            use_tools=True,
        )

    # Knowledge — provedor cloud + domínio detectado
    # Round 22+: bumpamos cap para 4 para acomodar queries multi-domínio
    # (ex.: microservices + kubernetes + reliability + aws).
    knowledge_specialists: list[str] = []
    if clouds:
        knowledge_specialists.append(clouds[0])
    # Adiciona todos os domínios detectados (cap será aplicado depois)
    for d in domains:
        if d not in knowledge_specialists:
            knowledge_specialists.append(d)

    # Default: se nenhum cloud detectado, sem especialistas específicos
    return AnalysisPlan(
        intent=Intent.KNOWLEDGE,
        clouds=clouds,
        # Round 22+: cap=4 em KNOWLEDGE para acomodar microservices+k8s+reliability
        specialists=(
            _cap_specialists(knowledge_specialists, max_n=4) if knowledge_specialists else []
        ),
    )