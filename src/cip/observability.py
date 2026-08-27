"""Métricas Prometheus-style + Audit Logging para produção.

Métricas expostas em /metrics (text/plain, formato Prometheus):
- cip_requests_total{endpoint,method,status,tenant} - counter
- cip_request_duration_seconds{endpoint,method} - histogram
- cip_tokens_total{type,model} - counter (input/output)
- cip_cost_usd_total{tenant,model} - counter
- cip_grounding_rate{tenant} - gauge (% de respostas com grounding)
- cip_cache_hits_total{cache_name} - counter
- cip_drift_detected_total - counter (cron)
- cip_specialist_executions_total{specialist} - counter
- cip_findings_total{severity,domain} - counter

Audit log: arquivo JSONL com TODA request:
- timestamp, tenant_id, api_key_hash, endpoint, method, status, latency_ms,
  question_preview, answer_length, tools_used, specialists_used,
  findings_count, has_grounding, n_sources
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cip.logging import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Metrics (in-memory counters/histograms)
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class Counter:
    """Contador monotônico com labels."""

    value: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class Histogram:
    """Histograma com buckets padrão (latência em segundos)."""

    # Buckets padrão Prometheus (em segundos)
    buckets: list[float] = field(default_factory=lambda: [
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0
    ])
    counts: list[int] = field(default_factory=lambda: [0] * 12)
    sum_value: float = 0.0
    count: int = 0
    inf_count: int = 0  # > max bucket
    labels: dict[str, str] = field(default_factory=dict)


class MetricsRegistry:
    """Registro singleton de métricas (in-memory)."""

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def inc_counter(
        self,
        name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Incrementa contador."""
        key = f"{name}|{json.dumps(labels or {}, sort_keys=True)}"
        if key not in self._counters:
            self._counters[key] = Counter(value=0.0, labels=labels or {})
        self._counters[key].value += value

    def observe_histogram(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Registra observação em histograma."""
        key = f"{name}|{json.dumps(labels or {}, sort_keys=True)}"
        if key not in self._histograms:
            self._histograms[key] = Histogram(labels=labels or {})

        h = self._histograms[key]
        h.sum_value += value
        h.count += 1
        # Encontrar bucket
        placed = False
        for i, b in enumerate(h.buckets):
            if value <= b:
                h.counts[i] += 1
                placed = True
                break
        if not placed:
            h.inf_count += 1

    def render(self) -> str:
        """Renderiza métricas no formato Prometheus text."""
        lines: list[str] = []
        # Counters
        by_name: dict[str, list[Counter]] = defaultdict(list)
        for c in self._counters.values():
            metric_name = c.labels.get("__name__", "")
            # Agrupar por (name, sorted labels excluding __name__)
            by_name[metric_name].append(c)

        # Output por nome
        seen_names: set[str] = set()
        for key, c in self._counters.items():
            # extrai nome do key (formato: name|{labels_json})
            name = key.split("|")[0]
            if name not in seen_names:
                lines.append(f"# HELP {name} {name} counter")
                lines.append(f"# TYPE {name} counter")
                seen_names.add(name)
            labels_str = _format_labels(c.labels)
            lines.append(f"{name}{labels_str} {c.value}")

        # Histograms
        for key, h in self._histograms.items():
            name = key.split("|")[0]
            if name not in seen_names:
                lines.append(f"# HELP {name} {name} histogram")
                lines.append(f"# TYPE {name} histogram")
                seen_names.add(name)
            labels_str = _format_labels(h.labels)
            # Cumulative bucket counts
            cumulative = 0
            for i, b in enumerate(h.buckets):
                cumulative += h.counts[i]
                bucket_labels = {**h.labels, "le": str(b)}
                bucket_labels_str = _format_labels(bucket_labels)
                lines.append(f"{name}_bucket{bucket_labels_str} {cumulative}")
            # +Inf bucket
            cumulative += h.inf_count
            inf_labels = {**h.labels, "le": "+Inf"}
            inf_labels_str = _format_labels(inf_labels)
            lines.append(f"{name}_bucket{inf_labels_str} {cumulative}")
            # sum + count
            lines.append(f"{name}_sum{labels_str} {h.sum_value}")
            lines.append(f"{name}_count{labels_str} {h.count}")

        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Reset (útil para testes)."""
        self._counters.clear()
        self._histograms.clear()


def _format_labels(labels: dict[str, str]) -> str:
    """Formata labels no formato Prometheus."""
    if not labels:
        return ""
    items = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + items + "}"


# Singleton
_metrics: MetricsRegistry | None = None


def get_metrics() -> MetricsRegistry:
    """Retorna registry singleton."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsRegistry()
    return _metrics


def reset_metrics() -> None:
    """Limpa singleton (para testes)."""
    global _metrics
    _metrics = None


# ─────────────────────────────────────────────────────────────────────────
# Round 22+ Phase 2: métricas de chat/feedback (formato Prometheus)
#
# Não duplicam MetricsRegistry acima — expõem via _metrics.labels(...)
# -----------------------------------------------------------------------

from prometheus_client import (  # noqa: E402
    CollectorRegistry,
    Counter as PromCounter,
    Gauge as PromGauge,
    Histogram as PromHistogram,
)

# Registry DEDICADO para as métricas de chat/feedback. Usar o registry global
# default do prometheus_client causava `DuplicateTimeseries` quando o módulo
# era re-importado sob dois paths (``src.cip.observability`` vs
# ``cip.observability``) no MESMO processo — cada import re-executa a criação
# module-level dos collectors e registra de novo no registry global.
# Com um registry PRÓPRIO por instância de módulo, o re-import cria um novo
# registry (não o global) e nunca colide.
_CHAT_REGISTRY = CollectorRegistry()

chat_conversations_created_total = PromCounter(
    "cip_conversations_created_total",
    "Total de conversas criadas",
    ["tenant_id"],
    registry=_CHAT_REGISTRY,
)

chat_messages_created_total = PromCounter(
    "cip_messages_created_total",
    "Total de mensagens criadas (user/assistant)",
    ["tenant_id", "role"],
    registry=_CHAT_REGISTRY,
)

chat_feedback_total = PromCounter(
    "cip_feedback_total",
    "Total de feedback por mensagem",
    ["tenant_id", "feedback"],  # feedback=up|down
    registry=_CHAT_REGISTRY,
)

chat_latency_seconds = PromHistogram(
    "cip_chat_latency_seconds",
    "Latência por operação de chat",
    ["operation", "tenant_id"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
    registry=_CHAT_REGISTRY,
)

chat_feedback_negative_ratio = PromGauge(
    "cip_chat_feedback_negative_ratio",
    "Ratio de feedback 👎 vs total (proxy de qualidade)",
    ["tenant_id"],
    registry=_CHAT_REGISTRY,
)


def record_chat_conversation_created(tenant_id: str) -> None:
    chat_conversations_created_total.labels(tenant_id=tenant_id).inc()


def record_chat_message_created(tenant_id: str, role: str) -> None:
    """role: 'user' | 'assistant' | 'system'."""
    chat_messages_created_total.labels(tenant_id=tenant_id, role=role).inc()


def record_chat_feedback(tenant_id: str, feedback: str) -> None:
    """feedback: 'up' | 'down'."""
    chat_feedback_total.labels(tenant_id=tenant_id, feedback=feedback).inc()


def observe_chat_latency(operation: str, tenant_id: str, seconds: float) -> None:
    """operation: 'chat_message' | 'chat_export' | 'chat_share'."""
    chat_latency_seconds.labels(operation=operation, tenant_id=tenant_id).observe(seconds)


def update_chat_feedback_ratio(tenant_id: str, total: int, down: int) -> None:
    """Atualiza o gauge (chamado por background job ou via admin endpoint)."""
    if total > 0:
        chat_feedback_negative_ratio.labels(tenant_id=tenant_id).set(down / total)


# ─────────────────────────────────────────────────────────────────────────
# Audit logging
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class AuditEntry:
    """Entrada de audit log para uma request."""

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tenant_id: str = "anonymous"
    api_key_hash: str = "none"
    endpoint: str = ""
    method: str = ""
    status: int = 0
    latency_ms: int = 0
    user_agent: str = ""
    source_ip: str = ""
    question_preview: str = ""  # primeiros 100 chars
    answer_length: int = 0
    has_grounding: bool = False
    n_sources: int = 0
    tools_used: list[str] = field(default_factory=list)
    specialists_used: list[str] = field(default_factory=list)
    findings_count: int = 0
    error: str = ""


class AuditLogger:
    """Logger de auditoria (compliance + debugging)."""

    def __init__(self, log_path: str | None = None) -> None:
        # Default: AUDIT_LOG_PATH env var ou .audit/audit.jsonl
        if log_path is None:
            log_path = os.getenv("CIP_AUDIT_LOG_PATH", ".audit/audit.jsonl")
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, entry: AuditEntry) -> None:
        """Adiciona entrada ao audit log (append-only JSONL)."""
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            log.warning("audit_log_failed", error=str(exc), path=str(self.log_path))

    def tail(self, n: int = 100) -> list[dict[str, Any]]:
        """Retorna últimas N entradas (para debug/auditoria)."""
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        entries: list[dict[str, Any]] = []
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries


# Singleton lazy
_audit: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Retorna audit logger singleton."""
    global _audit
    if _audit is None:
        _audit = AuditLogger()
    return _audit


def reset_audit_logger() -> None:
    """Para testes."""
    global _audit
    _audit = None