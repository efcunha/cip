"""
Locustfile para testes de carga do CIP API (Round 22+ Phase 2).

Como rodar:
  # 1. Subir infra
  docker compose up -d
  # 2. Instalar locust
  pip install locust
  # 3. Rodar (web UI em http://localhost:8089)
  locust -f tests/load/locustfile.py --host=http://localhost:8000
  # 4. Ou headless (CI)
  locust -f tests/load/locustfile.py --host=http://localhost:8000 \
    --headless --users 200 --spawn-rate 20 --run-time 60s

Cenários:
  - ChatUser: simula user fazendo perguntas + dando feedback (mix realista)
  - HeavyAsker: faz /ask simples em loop (stress de leitura)
  - AdminScroller: lista conversas e exporta markdown (workload de auditoria)

Métricas-alvo (200 concurrent users):
  - p95 latency < 5s para /chat/.../messages
  - p99 latency < 15s
  - error rate < 1%
  - RPS > 50
"""
from __future__ import annotations

import os
import random
import time

from locust import HttpUser, between, task


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

QUESTIONS = [
    "Quais sao os 6 pilares do AWS Well-Architected Framework?",
    "Como identificar desperdicio de custo em EC2 ocioso?",
    "Explique o GCP Architecture Framework.",
    "Compare AWS Lambda vs Azure Functions.",
    "Quais as melhores praticas de seguranca em pods Kubernetes?",
    "Como aplicar circuit breaker em microsservicos?",
    "Licoes aprendidas do incident do AWS S3 US-EAST-1 em 2017?",
    "Como funcionam as regions no Azure?",
    "O que e FinOps e como aplicar?",
    "Quando usar Lambda vs containers?",
]


def make_body(question: str, cloud: str = None) -> dict:
    body = {"question": question}
    if cloud:
        body["cloud"] = cloud
    return body


# ─────────────────────────────────────────────────────────────────────────
# User persona: ChatUser (mix realista)
# ─────────────────────────────────────────────────────────────────────────


class ChatUser(HttpUser):
    """User realista: cria conversa → pergunta → feedback → repete."""

    wait_time = between(2, 8)  # simula thinking time

    def on_start(self):
        # Cria conversa no startup
        self.conv_id = None
        try:
            r = self.client.post(
                "/chat/conversations",
                json={"title": f"load-{random.randint(1000, 9999)}"},
                headers={"X-Tenant-Id": "loadtest"},
            )
            if r.status_code == 201:
                self.conv_id = r.json()["id"]
        except Exception:
            pass  # tenta em cada @task

    @task(5)
    def ask(self):
        if not self.conv_id:
            return
        q = random.choice(QUESTIONS)
        cloud = random.choice(["aws", "gcp", "azure", None])
        with self.client.post(
            f"/chat/conversations/{self.conv_id}/messages",
            json=make_body(q, cloud),
            headers={"X-Tenant-Id": "loadtest"},
            name="/chat/conversations/{id}/messages [ask]",
        ) as r:
            if r.status_code == 201:
                msg = r.json()
                # 50% chance de dar feedback
                if random.random() < 0.5:
                    fb = random.choices(["up", "down"], weights=[0.7, 0.3])[0]
                    self.client.post(
                        f"/chat/messages/{msg['id']}/feedback",
                        json={"feedback": fb},
                        headers={"X-Tenant-Id": "loadtest"},
                        name="/chat/messages/{id}/feedback",
                    )

    @task(2)
    def list_conversations(self):
        with self.client.get(
            "/chat/conversations?limit=20",
            headers={"X-Tenant-Id": "loadtest"},
            name="/chat/conversations [list]",
        ):
            pass

    @task(1)
    def export_conversation(self):
        if not self.conv_id:
            return
        with self.client.get(
            f"/chat/conversations/{self.conv_id}/export?format=md",
            headers={"X-Tenant-Id": "loadtest"},
            name="/chat/conversations/{id}/export",
        ):
            pass


# ─────────────────────────────────────────────────────────────────────────
# HeavyAsker: stress puro de leitura (RPS puro)
# ─────────────────────────────────────────────────────────────────────────


class HeavyAsker(HttpUser):
    """Faz /ask simples em loop — workload de stress do LLM pipeline."""

    wait_time = between(0.5, 2)

    @task
    def ask(self):
        with self.client.post(
            "/ask",
            json=make_body(random.choice(QUESTIONS), random.choice(["aws", "gcp"])),
            headers={"X-Tenant-Id": "loadtest"},
            name="/ask [heavy]",
        ):
            pass


# ─────────────────────────────────────────────────────────────────────────
# AdminScroller: auditoria (lista tudo, exporta)
# ─────────────────────────────────────────────────────────────────────────


class AdminScroller(HttpUser):
    """Simula admin fazendo auditoria: lista conversations, exporta markdown."""

    wait_time = between(5, 15)

    @task(3)
    def list_conversations(self):
        with self.client.get(
            "/chat/conversations?limit=50",
            headers={"X-Tenant-Id": "loadtest"},
            name="/chat/conversations [admin-list]",
        ):
            pass

    @task(1)
    def health(self):
        with self.client.get("/health/ready", name="/health/ready"):
            pass

    @task(1)
    def metrics(self):
        with self.client.get("/metrics", name="/metrics"):
            pass
