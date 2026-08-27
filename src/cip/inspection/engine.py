"""Dispatcher do Inspection Engine: detecta o tipo de payload e roteia.

`inspect_payload` é chamado pelo orquestrador quando há artefatos de IaC/K8s.
"""

from __future__ import annotations

import re

from cip.agents.models import Finding
from cip.inspection import kubernetes as k8s
from cip.inspection import terraform as tf

_TF_HINTS = re.compile(r'\b(resource|provider|variable|module|terraform)\s+"?', re.I)
_K8S_HINTS = re.compile(r'^\s*(apiVersion|kind)\s*:', re.M)


def detect_type(payload: str) -> str:
    """Retorna 'terraform' | 'kubernetes' | 'unknown'."""
    if _K8S_HINTS.search(payload) and re.search(r"kind\s*:", payload):
        return "kubernetes"
    if _TF_HINTS.search(payload):
        return "terraform"
    return "unknown"


def inspect_payload(payload: str) -> list[Finding]:
    kind = detect_type(payload)
    if kind == "terraform":
        return tf.analyze(payload)
    if kind == "kubernetes":
        return k8s.analyze(payload)
    # fallback: tenta ambos e junta o que der
    findings = tf.analyze(payload) + k8s.analyze(payload)
    return findings
