"""Analisador estático de manifestos Kubernetes (YAML, possivelmente multi-doc).

Catálogo atual (7 regras):

SEGURANÇA:
  K1 - Container privilegiado (securityContext.privileged=true)
  K2 - Workload usando hostNetwork=true
  K3 - RBAC amplo (ClusterRoleBinding com verbs/resources wildcard)
  K4 - Container sem securityContext.runAsNonRoot

RELIABILITY:
  K5 - Container sem resource.limits (noisy neighbor)
  K6 - Workload sem liveness/readiness probes

OPERATIONS:
  K7 - Imagem sem tag fixa (:latest ou sem tag)
"""

from __future__ import annotations

from typing import Any

import yaml

from cip.agents.models import Finding
from cip.logging import get_logger

log = get_logger(__name__)

_WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Pod", "Job", "CronJob"}
_RBAC_KINDS = {"ClusterRoleBinding", "RoleBinding"}


def _load_docs(payload: str) -> list[dict[str, Any]]:
    try:
        return [d for d in yaml.safe_load_all(payload) if isinstance(d, dict)]
    except Exception as exc:
        log.warning("yaml_parse_failed", error=str(exc))
        return []


def _pod_spec(doc: dict[str, Any]) -> dict[str, Any]:
    kind = doc.get("kind")
    spec = doc.get("spec", {}) or {}
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
        return (spec.get("template", {}) or {}).get("spec", {}) or {}
    if kind == "CronJob":
        return (
            ((spec.get("jobTemplate", {}) or {}).get("spec", {}) or {})
            .get("template", {})
            .get("spec", {})
            or {}
        )
    if kind == "Pod":
        return spec
    return {}


def _is_wildcard_rbac(role_ref: dict[str, Any], subjects: list) -> tuple[bool, str]:
    """Detecta RBAC excessivamente permissivo.

    Sinais de alerta:
    - ClusterRoleBinding com roleRef.kind = ClusterRole + subjects.kind = ServiceAccount
      (acesso cluster-wide)
    - roleRef.name com nomes suspeitos (admin, cluster-admin, edit, *)
    """
    kind = role_ref.get("kind", "")
    name = role_ref.get("name", "")
    if kind == "ClusterRole" and "*" in name:
        return True, f"ClusterRole '{name}' (wildcard)"
    if kind == "ClusterRole" and name in {"admin", "cluster-admin", "edit"}:
        return True, f"ClusterRole '{name}' (privilégio excessivo)"
    return False, ""


def analyze(payload: str) -> list[Finding]:
    findings: list[Finding] = []

    for doc in _load_docs(payload):
        kind = doc.get("kind")
        name = (doc.get("metadata", {}) or {}).get("name", "?")
        ref = f"{kind}/{name}"

        # ─────────────────────────────────────────────────────────────────────
        # K3 — RBAC amplo (verificar antes de workloads)
        # ─────────────────────────────────────────────────────────────────────
        if kind in _RBAC_KINDS:
            role_ref = doc.get("roleRef", {}) or {}
            subjects = doc.get("subjects", []) or []
            is_wild, detail = _is_wildcard_rbac(role_ref, subjects)
            if is_wild:
                subject_str = ", ".join(
                    f"{s.get('kind', '?')}/{s.get('name', '?')}" for s in subjects
                ) or "(sem subjects)"
                findings.append(
                    Finding(
                        title=f"RBAC excessivamente permissivo ({ref})",
                        severity="critical",
                        domain="security",
                        description=(
                            f"ClusterRoleBinding/RoleBinding '{name}' usa {detail}. "
                            f"Subjects: {subject_str}. "
                            "Privilégio excessivo — risco de privilege escalation."
                        ),
                        recommendation=(
                            "Aplique princípio de menor privilégio. "
                            "Use Roles (namespace-scoped) em vez de ClusterRoles quando possível. "
                            "Crie roles customizados com verbs/resources específicos. "
                            "Audite com kubectl auth can-i --as=system:serviceaccount:..."
                        ),
                        effort="medium",
                        references=[
                            "[multi, kubernetes, RBAC best practices]",
                            "[multi, kubernetes, Pod Security Standards: restricted]",
                        ],
                    )
                )

        # Skip demais regras se não for workload
        if kind not in _WORKLOAD_KINDS:
            continue

        pod = _pod_spec(doc)

        # ─────────────────────────────────────────────────────────────────────
        # K2 — hostNetwork habilitado
        # ─────────────────────────────────────────────────────────────────────
        if pod.get("hostNetwork"):
            findings.append(
                Finding(
                    title=f"Workload usando hostNetwork ({ref})",
                    severity="high",
                    domain="security",
                    description=(
                        "hostNetwork=true expõe a rede do nó ao pod — "
                        "bypass de NetworkPolicy, sniffing de tráfego entre pods."
                    ),
                    recommendation=(
                        "Remova hostNetwork salvo necessidade explícita (ex: CNI customizado). "
                        "Se necessário, isole via RuntimeClass dedicado e PodSecurityPolicy."
                    ),
                    effort="low",
                    references=[
                        "[multi, kubernetes, Pod Security Standards: baseline/restricted]",
                        "[multi, kubernetes, Network policies]",
                    ],
                )
            )

        # ─────────────────────────────────────────────────────────────────────
        # K6 — Sem liveness/readiness probes
        # ─────────────────────────────────────────────────────────────────────
        containers = pod.get("containers", []) or []
        for c in containers:
            cname = c.get("name", "?")
            liveness = c.get("livenessProbe")
            readiness = c.get("readinessProbe")
            if not liveness and not readiness:
                findings.append(
                    Finding(
                        title=f"Container sem probes ({ref}/{cname})",
                        severity="medium",
                        domain="reliability",
                        description=(
                            "Sem livenessProbe/readinessProbe o K8s não detecta pods travados. "
                            "Pods podem ficar em estado Running sem atender tráfego."
                        ),
                        recommendation=(
                            "Configure livenessProbe (detecta deadlock) "
                            "e readinessProbe (remove do Service quando não pronto). "
                            "Use httpGet, tcpSocket ou exec conforme o caso."
                        ),
                        effort="low",
                        references=[
                            "[multi, kubernetes, Liveness and readiness probes]",
                            "[multi, kubernetes, Configure liveness, readiness and startup probes]",
                        ],
                    )
                )

        # ─────────────────────────────────────────────────────────────────────
        # Análise por container (K1, K4, K5, K7)
        # ─────────────────────────────────────────────────────────────────────
        for c in containers:
            cname = c.get("name", "?")
            sc = c.get("securityContext", {}) or {}

            # ─────────────────────────────────────────────────────────────────
            # K1 — Container privilegiado
            # ─────────────────────────────────────────────────────────────────
            if sc.get("privileged"):
                findings.append(
                    Finding(
                        title=f"Container privilegiado ({ref}/{cname})",
                        severity="critical",
                        domain="security",
                        description=(
                            "privileged=true concede acesso quase total ao nó: "
                            "todos os devices, capabilities, bypass de AppArmor/SELinux."
                        ),
                        recommendation=(
                            "Remova privileged. Use capabilities mínimas necessárias "
                            "(NET_ADMIN, SYS_ADMIN apenas se inevitável). "
                            "Considere RuntimeClass com seccomp profile restritivo."
                        ),
                        effort="medium",
                        references=[
                            "[multi, kubernetes, Pod Security Standards: restricted]",
                            "[multi, kubernetes, Security context for pods]",
                        ],
                    )
                )

            # ─────────────────────────────────────────────────────────────────
            # K4 — Sem securityContext.runAsNonRoot
            # ─────────────────────────────────────────────────────────────────
            run_as_non_root = sc.get("runAsNonRoot")
            if not run_as_non_root:
                findings.append(
                    Finding(
                        title=f"Container sem runAsNonRoot ({ref}/{cname})",
                        severity="medium",
                        domain="security",
                        description=(
                            "Sem runAsNonRoot=true, o container pode rodar como UID 0 (root) "
                            "— vetor para privilege escalation se houver exploit."
                        ),
                        recommendation=(
                            "Adicione securityContext.runAsNonRoot=true. "
                            "Para imagens que exigem root (raro), use "
                            "PodSecurityPolicy/PSA com allowedUserIDs específicos."
                        ),
                        effort="low",
                        references=[
                            "[multi, kubernetes, Pod Security Standards: restricted]",
                            "[multi, kubernetes, Security context for pods]",
                        ],
                    )
                )

            # ─────────────────────────────────────────────────────────────────
            # K5 — Sem resource.limits
            # ─────────────────────────────────────────────────────────────────
            resources = c.get("resources", {}) or {}
            if not resources.get("limits"):
                findings.append(
                    Finding(
                        title=f"Container sem resource limits ({ref}/{cname})",
                        severity="medium",
                        domain="reliability",
                        description=(
                            "Sem limits, um pod pode consumir todo o nó (noisy neighbor). "
                            "Em clusters compartilhados, prejudica vizinhos."
                        ),
                        recommendation=(
                            "Defina requests (garantia) e limits (teto) de cpu/memory. "
                            "Comece com P95 de uso atual + 30% margem para limits."
                        ),
                        effort="low",
                        references=[
                            "[multi, kubernetes, Resource management for pods and containers]",
                            "[multi, kubernetes, Configure Quality of Service for pods]",
                        ],
                    )
                )

            # ─────────────────────────────────────────────────────────────────
            # K7 — Imagem sem tag fixa
            # ─────────────────────────────────────────────────────────────────
            image = c.get("image", "")
            if image:
                if image.endswith(":latest") or ":" not in image:
                    findings.append(
                        Finding(
                            title=f"Imagem sem tag fixa ({ref}/{cname}: {image})",
                            severity="medium",
                            domain="operations",
                            description=(
                                "Uso de :latest ou sem tag impede rollback determinístico "
                                "e build não-reprodutível. Tags imutáveis dão rastreabilidade."
                            ),
                            recommendation=(
                                "Pine a tag da imagem (semver ou SHA digest). "
                                "Use SHA digest (@sha256:...) para garantia máxima."
                            ),
                            effort="low",
                            references=[
                                "[multi, kubernetes, Image configuration best practices]",
                                "[multi, kubernetes, Production best practices: configuration]",
                            ],
                        )
                    )

    return findings