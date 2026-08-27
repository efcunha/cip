#!/usr/bin/env python3
"""Validação end-to-end de homologação com LLM REAL (MiniMax M3, Bedrock, OpenAI).

Diferente do ``smoke_test.py`` (que valida só disponibilidade da API) e do
``run_eval.py --offline`` (que pula o LLM), este script:

  1. Garante que o LLM provider real está ativo (MiniMax M3, Bedrock, OpenAI…)
  2. Roda a suíte de homologação — um conjunto curado de queries representativas
     cobrindo TODOS os knowledge areas (aws/gcp/azure + architecture + case-studies)
  3. Coleta métricas de qualidade por critério (rubrica bilíngue PT/EN)
  4. Mede latência, custo estimado, e taxa de grounding
  5. Emite relatório Markdown + JSON + exit code (0/1/2) para CI

Uso:
    # Validação direta via orchestrator (RECOMENDADO - sem precisar de servidor HTTP)
    python scripts/homolog_validate.py

    # Validação via HTTP server (precisa de API rodando)
    python scripts/homolog_validate.py --api-url http://localhost:8001

    # Apenas 1 knowledge area
    python scripts/homolog_validate.py --area software_architecture

    # Modo strict (exit 1 se gate falhar)
    python scripts/homolog_validate.py --strict

    # Multi-run por maioria (reduz falso-negativo por variância de temperatura)
    python scripts/homolog_validate.py --runs 3

    # Provider custom (default = env LLM_PROVIDER)
    LLM_PROVIDER=bedrock python scripts/homolog_validate.py

Exit codes:
    0 = homolog passou
    1 = alguma query falhou (gate de qualidade)
    2 = erro de configuração (provider, API key, DB down…)

Rubrica BILÍNGUE (PT-BR + EN):
    Cada must_mention é uma lista de CONCEITOS: ``[{"variants": [...]}, ...]``.
    Um conceito é matched se QUALQUER das suas variantes (PT/EN/sinônimos)
    aparece na resposta. Formatos legacy (dict {"pt": [...], "en": [...]},
    list de strings, string) seguem aceitos para retrocompatibilidade.
    Isso resolve o mismatch onde a documentação está em inglês mas a rubrica
    original era em português.

Round 22+ melhorias:
    - Rubrica bilíngue (PT-BR + EN) para evitar mismatch de idioma
    - Round 22.5: must_mention como lista de grupos de variantes (imune a
      desalinhamento posicional pt[i] <-> en[i])
    - Modo direto via orchestrator (sem servidor HTTP) — mais rápido e confiável
    - Timeout por query (default 90s) — sobrevive a hangs do LLM
    - Source extraction robusto (aceita dict OU dataclass Source)
    - Estimativa de custo baseada no output real
    - Round 22.6: ``--runs N`` roda cada caso N vezes e decide PASS por MAIORIA
      (>= ceil(N/2)), reduzindo falso-negativo por variância temp do LLM. O
      default (1 run) preserva o comportamento single-run intacto.

Diferenças vs run_eval.py:
    - Foco em homolog (gate binário), não em benchmark fino
    - Usa o MESMO provider real que produção
    - Inclui novos knowledge areas (architecture, case-studies)
    - Reporta custos e latência por área
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────────────────
# Homolog suite — queries representativas cobrindo todos os knowledge areas
#
# Round 22.5: must_mention é uma LISTA DE CONCEITOS (grupos de variantes).
# Cada ``{"variants": [...]}`` é UM conceito; as variantes (PT/EN/sinônimos)
# casam por OR. Este formato elimina o pareamento posicional pt[i] <-> en[i]
# (frágil a desalinhamento) e declara o agrupamento explicitamente.
# ─────────────────────────────────────────────────────────────────────────

HOMOLOG_SUITE: list[dict[str, Any]] = [
    # ── AWS / GCP / Azure (foco principal preservado) ────────────────────
    {
        "id": "homolog-aws-001",
        "area": "aws",
        "question": "Quais são os 6 pilares do AWS Well-Architected Framework?",
        "must_mention": [
            {"variants": ["excelência operacional", "operational excellence"]},
            {"variants": ["segurança", "security"]},
            {"variants": ["confiabilidade", "reliability"]},
            {"variants": ["eficiência de performance", "performance efficiency"]},
            {"variants": ["otimização de custos", "cost optimization"]},
            {"variants": ["sustentabilidade", "sustainability"]},
        ],
    },
    {
        "id": "homolog-aws-002",
        "area": "aws",
        "question": "Como reduzir custo de EC2 com Savings Plans vs Reserved Instances?",
        "must_mention": [
            {"variants": ["compromisso", "compromisso de uso", "commitment"]},
            {"variants": ["desconto", "discount"]},
            {"variants": ["flexibilidade", "flexibility"]},
            {"variants": ["savings plan", "savings"]},
            {"variants": ["reserved instance", "reserved"]},
            {"variants": ["1-year"]},
            {"variants": ["3-year"]},
            {"variants": ["no-upfront"]},
            {"variants": ["upfront"]},
        ],
    },
    {
        "id": "homolog-gcp-001",
        "area": "gcp",
        "question": "Explique o GCP Architecture Framework e suas 6 dimensões.",
        "must_mention": [
            {"variants": ["system design"]},
            {"variants": ["segurança", "security"]},
            {"variants": ["confiabilidade", "reliability"]},
            {"variants": ["otimização de custos", "cost optimization"]},
            {"variants": ["excelência operacional", "operational excellence"]},
            {"variants": ["otimização de performance", "performance optimization"]},
        ],
    },
    {
        "id": "homolog-azure-001",
        "area": "azure",
        "question": "Quais os pilares do Azure Well-Architected Framework?",
        "must_mention": [
            {"variants": ["confiabilidade", "reliability"]},
            {"variants": ["segurança", "security"]},
            {"variants": ["otimização de custos", "cost optimization"]},
            {"variants": ["excelência operacional", "operational excellence"]},
            {"variants": ["eficiência de performance", "performance efficiency"]},
            {"variants": ["sustentabilidade", "sustainability"]},
        ],
    },
    # ── Software Architecture patterns (Round 22) ────────────────────────
    {
        "id": "homolog-arch-001",
        "area": "software_architecture",
        "question": "Quando usar microservices em vez de monolito? Liste os trade-offs.",
        "must_mention": [
            {"variants": ["monolito", "monolith"]},
            {"variants": ["microsserviço", "microsserviços", "microserviços",
                          "microservice", "microservices"]},
            {"variants": ["trade-off"]},
            {"variants": ["complexidade", "complexity"]},
            {"variants": ["acoplamento", "coupling"]},
            {"variants": ["deploy independente", "independent deployment"]},
        ],
    },
    {
        "id": "homolog-arch-002",
        "area": "software_architecture",
        "question": "Explique o padrão Circuit Breaker e quando aplicá-lo.",
        "must_mention": [
            {"variants": ["circuit breaker"]},
            {"variants": ["fechado", "closed"]},
            {"variants": ["aberto", "open"]},
            {"variants": ["meio-aberto", "half-open"]},
            {"variants": ["degradação", "degradation"]},
            {"variants": ["falha", "failure"]},
            {"variants": ["resilience"]},
        ],
    },
    {
        "id": "homolog-arch-003",
        "area": "software_architecture",
        "question": "Diferença entre CQRS e CRUD tradicional. Quando aplicar CQRS?",
        "must_mention": [
            {"variants": ["cqrs"]},
            {"variants": ["command", "comando"]},
            {"variants": ["query", "consulta"]},
            {"variants": ["separação", "separation"]},
            {"variants": ["leitura", "read"]},
            {"variants": ["escrita", "write"]},
            {"variants": ["read model"]},
            {"variants": ["write model"]},
            {"variants": ["event sourcing"]},
        ],
    },
    {
        "id": "homolog-arch-004",
        "area": "software_architecture",
        "question": "Como o padrão Saga resolve transações distribuídas?",
        "must_mention": [
            {"variants": ["saga"]},
            {"variants": ["orquestração", "orchestration"]},
            {"variants": ["coreografia", "choreography"]},
            {"variants": ["compensa", "compensat"]},
            {"variants": ["transação compensatória", "transações compensatórias",
                          "compensating transaction"]},
            {"variants": ["rollback"]},
            {"variants": ["distributed transaction"]},
            {"variants": ["consistência eventual", "eventual consistency"]},
        ],
    },
    # ── Real-world case studies / postmortems (Round 22) ─────────────────
    {
        "id": "homolog-cases-001",
        "area": "case_studies",
        "question": "Quais lições aprendidas do incident do S3 US-EAST-1 em fevereiro de 2017?",
        "must_mention": [
            # Núcleo factual do incidente S3 2017: (1) erro de digitação/typo,
            # (2) comando, (3) playbook, (4) billing, (5) degradação,
            # (6) indisponibilidade, (7) postmortem.
            {"variants": ["erro de digitação", "typo"]},
            {"variants": ["comando", "command"]},
            {"variants": ["playbook"]},
            {"variants": ["billing"]},
            {"variants": ["degradação", "degradation"]},
            {"variants": ["indisponibilidade", "unavailability"]},
            {"variants": ["postmortem"]},
        ],
    },
    {
        "id": "homolog-cases-002",
        "area": "case_studies",
        "question": "Que lições o caso Netflix Spark + Kafka deixa sobre pipelines de eventos em escala?",
        "must_mention": [
            {"variants": ["schema evolution"]},
            {"variants": ["backpressure"]},
            {"variants": ["idempotência", "idempotency", "idempot"]},
            {"variants": ["kafka"]},
            {"variants": ["spark"]},
            {"variants": ["streaming"]},
            {"variants": ["event pipeline"]},
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────
# Helper: matching bilíngue (PT/EN) accent-insensitive
# ─────────────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lowercase + remove acentos (para matching entre PT e EN)."""
    text = text.lower()
    # NFD = decompõe caracteres acentuados em base + combining mark
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def _matches_any(answer_norm: str, term: str) -> bool:
    """Verifica se `term` aparece em `answer_norm` (ambos normalizados)."""
    return _normalize(term) in answer_norm


def _is_concept_group(item: Any) -> bool:
    """True se `item` é um grupo de conceito ``{"variants": [...]}``."""
    return isinstance(item, dict) and isinstance(item.get("variants"), list)


def _iter_concept_groups(must: Any) -> list[list[str]]:
    """Normaliza `must_mention` para uma lista de conceitos (cada conceito é
    uma lista de variantes que casam por OR).

    Formatos aceitos (Round 22.5 — hardening):
      - list de grupos ``[{"variants": [...]}, ...]`` (CANÔNICO): cada grupo é
        UM conceito autônomo; suas variantes (PT/EN/sinônimos) casam por OR.
        NÃO há alinhamento posicional entre idiomas — cada grupo declara
        explicitamente todas as suas variantes.
      - dict ``{"pt": [...], "en": [...]}`` (legacy): mantido para
        retrocompatibilidade; cada índice i é um conceito cujas variantes são
        ``{pt[i], en[i]}`` (pareamento posicional, formato antigo).
      - list de strings (legacy): cada string é um conceito de variante única.
      - string: single concept de variante única.
    """
    if not must:
        return []
    if isinstance(must, str):
        return [[must]]
    if isinstance(must, list):
        # Distinguir: lista de grupos vs lista de strings (legacy EN-only).
        if any(_is_concept_group(item) for item in must):
            groups: list[list[str]] = []
            for item in must:
                if _is_concept_group(item):
                    variants = [str(v) for v in item["variants"] if v]
                    if variants:
                        groups.append(variants)
            return groups
        return [[str(t)] for t in must if t]
    if isinstance(must, dict):
        # Legacy dict pt/en: pareamento posicional explícito (documentado).
        all_pt = [str(v) for v in (must.get("pt") or [])]
        all_en = [str(v) for v in (must.get("en") or [])]
        n = max(len(all_pt), len(all_en))
        groups = []
        for i in range(n):
            pt = all_pt[i] if i < len(all_pt) else None
            en = all_en[i] if i < len(all_en) else None
            variants = [v for v in (pt, en) if v]
            if variants:
                groups.append(variants)
        return groups
    return []


def _check_must_mention_bilingual(answer: str, must: dict | list | str | None) -> tuple[list[str], list[str]]:
    """Compara answer contra must_mention como LISTA DE CONCEITOS.

    Round 22.5: cada must_mention é tratado como lista de conceitos, onde cada
    conceito é um grupo de variantes que casam por OR. O formato canónico é
    ``[{"variants": [...]}, ...]``, imune a desalinhamento posicional PT/EN
    (o pareamento `pt[i] <-> en[i]` do Round 22.4 era frágil: adicionar/remover
    uma variante num idioma deslocava todos os conceitos seguintes).

    Returns: (matched_terms, missing_terms)
    """
    groups = _iter_concept_groups(must)
    if not groups:
        return [], []

    answer_norm = _normalize(answer)
    matched: list[str] = []
    missing: list[str] = []
    for variants in groups:
        hits = [v for v in variants if _matches_any(answer_norm, v)]
        if hits:
            # Registra a variante que casou (para visibilidade), priorizando PT.
            matched.append(hits[0])
        else:
            # Registra a variante "canónica" (primeira) como pendente.
            missing.append(variants[0])
    return matched, missing


def _must_mention_total(must: dict | list | str | None) -> int:
    """Número de conceitos exigidos (len da lista de grupos de variantes).

    Cada grupo = 1 conceito. Formatos legacy (dict pt/en, list de strings, str)
    são convertidos pela mesma normalização usada no matching, garantindo que o
    denominador do ratio bata com o numerador de menções.
    """
    return len(_iter_concept_groups(must))


# ─────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class HomologCaseResult:
    """Resultado de uma query do homolog."""

    case_id: str
    area: str
    question: str
    answer: str = ""
    sources_count: int = 0
    has_grounding: bool = False
    mentions_found: list[str] = field(default_factory=list)
    mentions_missing: list[str] = field(default_factory=list)
    latency_ms: int = 0
    cost_estimated_usd: float = 0.0
    error: str | None = None
    passed: bool = False

    @property
    def accuracy(self) -> float:
        """Score 1-5 baseado em must_mention matched/total."""
        total = len(self.mentions_found) + len(self.mentions_missing)
        if total == 0:
            return 4.0  # neutro se sem must_mention
        if not self.mentions_missing:
            return 5.0
        ratio = len(self.mentions_found) / total
        return round(1.0 + ratio * 4.0, 2)


# ─────────────────────────────────────────────────────────────────────────
# Provider detection + cost estimation
# ─────────────────────────────────────────────────────────────────────────


def detect_active_provider() -> str:
    """Detecta qual LLM provider está configurado."""
    return os.environ.get("LLM_PROVIDER", "bedrock").lower()


def require_real_provider(provider: str) -> None:
    """Falha early se provider for stub/local-only."""
    if provider == "stub":
        raise SystemExit(
            "[FAIL] LLM_PROVIDER=stub detectado. "
            "Para homologar com LLM real, configure LLM_PROVIDER=minimax|deepseek|bedrock|openai "
            "no .env antes de rodar."
        )


def estimate_cost(answer: str, provider: str) -> float:
    """Estimativa grosseira de custo por query (USD)."""
    input_chars = 1500 * 4  # system + question + context
    output_chars = len(answer)
    in_tok = input_chars // 4
    out_tok = output_chars // 4
    rates = {
        # USD per 1M tokens (input, output)
        "bedrock": (3.0, 15.0),       # Claude Sonnet 4.5
        "openai": (2.5, 10.0),        # GPT-4o class
        "minimax": (2.0, 8.0),        # MiniMax M3
        "deepseek": (0.28, 0.42),     # DeepSeek-V4-Flash (estimativa)
        "local": (0.0, 0.0),          # self-hosted
    }
    in_rate, out_rate = rates.get(provider, (3.0, 15.0))
    return round((in_tok * in_rate + out_tok * out_rate) / 1_000_000, 6)


# ─────────────────────────────────────────────────────────────────────────
# Mode 1: Execução DIRETA via orchestrator (recomendado — sem HTTP)
# ─────────────────────────────────────────────────────────────────────────


def _normalize_sources(sources_raw: list[Any]) -> list[dict[str, Any]]:
    """Normaliza sources — aceita dataclass Source OU dict."""
    out = []
    for s in sources_raw or []:
        if hasattr(s, "url"):
            out.append({
                "url": getattr(s, "url", None),
                "title": getattr(s, "title", None),
                "cloud": getattr(s, "cloud", None),
                "service": getattr(s, "service", None),
                "score": getattr(s, "score", None),
            })
        elif isinstance(s, dict):
            out.append({
                "url": s.get("url"),
                "title": s.get("title"),
                "cloud": s.get("cloud"),
                "service": s.get("service"),
                "score": s.get("score"),
            })
    return out


def _resolve_cloud_from_area(area: str) -> str | None:
    """Mapeia area do homolog para cloud aceito pelo orchestrator.

    Round 22.1: `software_architecture` e `case_studies` retornam None — o
    roteamento por keywords (router.py) já direciona a pergunta para o
    especialista/domínio correto, e o RAG sem filtro de cloud recupera um
    conjunto MAIS AMPLO de chunks (incluindo architecture/case-studies via
    relevância semântica). Filtrar por `architecture`/`case-studies` aqui
    REGRIDIU a accuracy (6/10 → 3/10) porque o especialista
    software_architecture roda com spec_cloud=None e o rag_primary ficava
    restrito a um subconjunto menor.
    """
    return {
        "aws": "aws",
        "gcp": "gcp",
        "azure": "azure",
        "software_architecture": None,
        "case_studies": None,
    }.get(area)


def _build_orchestrator_sync_runner(timeout_s: float = 120, retries: int = 2):
    """Retorna uma função sync ``run_case(case, provider) -> HomologCaseResult``.

    Importa o orchestrator sob demanda (carrega embedding model + LLM).

    IMPORTANTE: cria UM único event loop asyncio e reusa para TODAS as queries.
    Sem isso, o asyncpg pool crasha com "RuntimeError: Event loop is closed"
    quando o cleanup do pool tenta usar o loop que já foi fechado pelo asyncio.run().

    Round 22+ RETRY: reexecutar até ``retries`` vezes em caso de falha transient
    (NoneType.send, Event loop closed, ConnectionError). Esses erros aparecem
    quando o asyncpg pool fica em estado inconsistente após queries pesadas
    (especialmente após intent COMPARE com 2+ specialists paralelos).
    """
    import asyncio as _asyncio
    from cip.config import get_settings
    get_settings.cache_clear()
    from cip.agents.orchestrator import get_orchestrator

    # Inicializa orchestrator (carrega embeddings + LLM uma única vez)
    orch = get_orchestrator()

    # Cria loop persistente
    loop = _asyncio.new_event_loop()
    _asyncio.set_event_loop(loop)

    TRANSIENT_ERRORS = (
        "NoneType",
        "Event loop is closed",
        "ConnectionError",
        "Connection refused",
        "RuntimeError",
        "Send closed",
        # Round 22.7: erros transitórios do provider upstream (MiniMax/HTTP)
        # 502/503 "Bad Gateway"/"Service Temporarily Unavailable" do gateway.
        "InternalServerError",
        "502 Bad Gateway",
        "503 Service Temporarily Unavailable",
        "Bad Gateway",
        "Service Unavailable",
        "Gateway",
    )

    def _is_transient(error: str) -> bool:
        return any(tok in error for tok in TRANSIENT_ERRORS)

    def _execute_once(case: dict[str, Any], provider: str) -> HomologCaseResult:
        result = HomologCaseResult(
            case_id=case["id"],
            area=case["area"],
            question=case["question"],
        )
        cloud = _resolve_cloud_from_area(case["area"])
        t0 = time.perf_counter()
        try:
            handle_coro = orch.handle(case["question"], cloud=cloud)
            handle_result = loop.run_until_complete(
                _asyncio.wait_for(handle_coro, timeout=timeout_s)
            )
            result.answer = getattr(handle_result, "summary", "") or ""
            sources = getattr(handle_result, "sources", []) or []
            sources_norm = _normalize_sources(sources)
            result.sources_count = len(sources_norm)
            result.has_grounding = bool(sources_norm) and any(s["url"] for s in sources_norm)
        except _asyncio.TimeoutError:
            result.error = f"TIMEOUT after {timeout_s}s"
        except Exception as exc:  # noqa: BLE001
            result.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        finally:
            result.latency_ms = int((time.perf_counter() - t0) * 1000)

        # Avalia menções (bilingue)
        result.mentions_found, result.mentions_missing = _check_must_mention_bilingual(
            result.answer, case.get("must_mention")
        )
        result.cost_estimated_usd = estimate_cost(result.answer, provider)

        # Gate binário
        must = case.get("must_mention") or {}
        n_total = _must_mention_total(must)
        if n_total == 0:
            n_total = 1
        ratio = len(result.mentions_found) / max(n_total, 1)
        result.passed = (ratio >= 0.6) and result.has_grounding
        return result

    def run_case(case: dict[str, Any], provider: str) -> HomologCaseResult:
        last = _execute_once(case, provider)
        for attempt in range(1, retries + 1):
            if not last.error or not _is_transient(last.error):
                return last
            # Pequeno backoff (sync sleep) para o pool estabilizar
            time.sleep(2 * attempt)
            print(f"      [retry {attempt}/{retries}] transient error '{last.error[:60]}' — retrying",
                  flush=True)
            last = _execute_once(case, provider)
        return last

    return run_case


# ─────────────────────────────────────────────────────────────────────────
# Mode 2: Execução via HTTP (legacy — requer API server rodando)
# ─────────────────────────────────────────────────────────────────────────


async def ask_api(client: Any, question: str, cloud: str | None, area: str) -> dict[str, Any]:
    """Faz POST /ask."""
    payload: dict[str, Any] = {"question": question}
    if cloud:
        payload["cloud"] = cloud
    resp = await client.post("/ask", json=payload, timeout=180)
    resp.raise_for_status()
    return resp.json()


def run_case_http(client: Any, case: dict[str, Any], provider: str) -> HomologCaseResult:
    """Executa 1 caso via API HTTP."""
    import asyncio

    result = HomologCaseResult(
        case_id=case["id"],
        area=case["area"],
        question=case["question"],
    )
    cloud = _resolve_cloud_from_area(case["area"])
    t0 = time.perf_counter()
    try:
        data = asyncio.run(ask_api(client, case["question"], cloud, case["area"]))
        result.answer = data.get("answer", "")
        sources = data.get("sources", [])
        sources_norm = _normalize_sources(sources)
        result.sources_count = len(sources_norm)
        result.has_grounding = data.get("has_grounding", False)
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return result
    finally:
        result.latency_ms = int((time.perf_counter() - t0) * 1000)

    result.mentions_found, result.mentions_missing = _check_must_mention_bilingual(
        result.answer, case.get("must_mention")
    )
    result.cost_estimated_usd = estimate_cost(result.answer, provider)
    must = case.get("must_mention") or {}
    n_total = _must_mention_total(must)
    if n_total == 0:
        n_total = 1
    ratio = len(result.mentions_found) / max(n_total, 1)
    result.passed = (ratio >= 0.6) and result.has_grounding
    return result


# ─────────────────────────────────────────────────────────────────────────
# Setup step
# ─────────────────────────────────────────────────────────────────────────


def step_setup(api_url: str) -> bool:
    """Chama scripts/setup_homolog.py se necessário."""
    print(f"\n[setup] Garantindo stack disponível em {api_url}...")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "setup_homolog.py"),
            "--skip-build",
            "--skip-tests",
            "--api-url",
            api_url,
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        print(proc.stdout[-2000:])
        print(proc.stderr[-1000:])
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────
# Relatório
# ─────────────────────────────────────────────────────────────────────────


def _write_partial_report(
    results: list[HomologCaseResult],
    md_path: str,
    json_path: str,
    provider: str,
    mode: str,
) -> None:
    """Salva report parcial a cada caso (proteção contra crashes silenciosos)."""
    Path(md_path).parent.mkdir(parents=True, exist_ok=True)
    md = render_report(results, provider, mode + " (parcial)")
    Path(md_path).write_text(md, encoding="utf-8")
    payload = {
        "provider": provider,
        "mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(r) for r in results],
        "summary": {
            "n_cases": len(results),
            "n_passed": sum(1 for r in results if r.passed),
            "avg_accuracy": statistics.mean([r.accuracy for r in results if not r.error])
            if [r for r in results if not r.error] else 0,
            "avg_latency_ms": statistics.mean([r.latency_ms for r in results])
            if results else 0,
            "total_cost_usd": sum(r.cost_estimated_usd for r in results),
            "n_grounded": sum(1 for r in results if r.has_grounding),
            "n_errors": sum(1 for r in results if r.error),
        },
    }
    Path(json_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def render_report(results: list[HomologCaseResult], provider: str, mode: str) -> str:
    n = len(results)
    n_pass = sum(1 for r in results if r.passed)
    avg_acc = statistics.mean([r.accuracy for r in results if not r.error]) if [r for r in results if not r.error] else 0.0
    avg_lat = statistics.mean([r.latency_ms for r in results]) if results else 0
    total_cost = sum(r.cost_estimated_usd for r in results)
    n_grounded = sum(1 for r in results if r.has_grounding)
    n_errors = sum(1 for r in results if r.error)

    by_area: dict[str, list[HomologCaseResult]] = {}
    for r in results:
        by_area.setdefault(r.area, []).append(r)

    lines: list[str] = []
    lines.append(f"# Relatório de Homologação — LLM Real ({provider})")
    lines.append("")
    lines.append(f"**Data**: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"**Provider**: `{provider}`")
    lines.append(f"**Modo**: {mode}")
    lines.append(f"**Casos**: {n_pass}/{n} passaram")
    lines.append(f"**Accuracy média**: {avg_acc:.2f}")
    lines.append(f"**Latência média**: {avg_lat:.0f} ms")
    lines.append(f"**Custo total estimado**: ${total_cost:.4f}")
    lines.append(f"**Grounding**: {n_grounded}/{n} casos")
    lines.append(f"**Erros**: {n_errors}")
    lines.append(f"**Gate**: {'✅ PASSOU' if n_pass == n else '❌ FALHOU'}")
    lines.append("")
    lines.append("## Por knowledge area")
    lines.append("")
    lines.append("| Area | N | Pass | Accuracy | Latência (ms) | Custo (USD) |")
    lines.append("|---|---|---|---|---|---|")
    for area, items in sorted(by_area.items()):
        passed = sum(1 for r in items if r.passed)
        acc_items = [r.accuracy for r in items if not r.error]
        acc = statistics.mean(acc_items) if acc_items else 0.0
        lat = statistics.mean([r.latency_ms for r in items])
        c = sum(r.cost_estimated_usd for r in items)
        lines.append(
            f"| {area} | {len(items)} | {passed}/{len(items)} | {acc:.2f} | "
            f"{lat:.0f} | ${c:.4f} |"
        )
    lines.append("")

    failed = [r for r in results if not r.passed]
    if failed:
        lines += [f"## Casos que falharam ({len(failed)})", ""]
        for r in failed:
            missing = ", ".join(r.mentions_missing) if r.mentions_missing else "—"
            err = f" err=`{r.error}`" if r.error else ""
            lines.append(
                f"- **{r.case_id}** ({r.area}): acc={r.accuracy:.2f} "
                f"lat={r.latency_ms}ms missing=[{missing}]{err}"
            )
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# Round 22.6: multi-run por maioria (reduz falso-negativo por variância temp)
# ─────────────────────────────────────────────────────────────────────────


def _majority_result(runs: list[HomologCaseResult]) -> HomologCaseResult:
    """Consolida N execuções de UM caso numa única decisão por MAIORIA.

    Reduz falsos-negativos causados por variância de temperatura do LLM: uma
    menção pontual omitida num único run não derruba o gate se a MAIORIA dos
    runs passar. O resultado final:
      - ``passed`` = True se a maioria (>= ceil(N/2)) dos runs passou.
      - ``accuracy`` = média das accuracies dos runs.
      - ``latency_ms`` = média das latências.
      - ``mentions_found/missing`` = união dos conceitos encontrados/perdidos
        através dos runs (um conceito é "encontrado" se apareceu em QUALQUER
        run), para dar visibilidade do comportamento agregado.
      - ``answer``/``sources``/``error`` vêm do run com maior accuracy
        (representativo da melhor resposta).

    Para ``n_runs == 1`` o comportamento é idêntico ao run único (nenhuma
    mudança no resultado), preservando o default intacto.
    """
    n = len(runs)
    if n == 0:
        raise ValueError("_majority_result requer ao menos 1 run")
    if n == 1:
        return runs[0]

    n_pass = sum(1 for r in runs if r.passed)
    majority = n_pass >= (n // 2 + 1)  # >= ceil(n/2)

    # Run representativo: maior accuracy (desempate -> primeiro que passou).
    best = max(runs, key=lambda r: (r.accuracy, r.passed))

    # União de conceitos através dos runs (visibilidade, não gate).
    found_union: list[str] = []
    seen_found: set[str] = set()
    for r in runs:
        for m in r.mentions_found:
            if m not in seen_found:
                seen_found.add(m)
                found_union.append(m)
    # missing = conceitos que faltaram no run representativo (best); a decisão
    # de gate já é por maioria, então isto é apenas para o relatório.
    missing_union = list(best.mentions_missing)

    merged = HomologCaseResult(
        case_id=best.case_id,
        area=best.area,
        question=best.question,
        answer=best.answer,
        sources_count=best.sources_count,
        has_grounding=best.has_grounding,
        mentions_found=found_union,
        mentions_missing=missing_union,
        latency_ms=int(statistics.mean(r.latency_ms for r in runs)),
        cost_estimated_usd=round(sum(r.cost_estimated_usd for r in runs), 6),
        error=best.error,
        passed=majority,
    )
    return merged


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validação de homolog com LLM real (MiniMax M3, Bedrock, OpenAI)"
    )
    parser.add_argument(
        "--api-url", default=None,
        help="Se fornecido, usa modo HTTP (precisa API rodando). Se omitido, "
             "roda direto via orchestrator (recomendado).",
    )
    parser.add_argument(
        "--api-key", default=os.environ.get("CIP_API_KEY", ""),
        help="API key (default: env CIP_API_KEY)",
    )
    parser.add_argument(
        "--tenant-id", default=os.environ.get("CIP_TENANT_ID", "default"),
        help="Tenant ID (default: env CIP_TENANT_ID ou 'default')",
    )
    parser.add_argument(
        "--skip-setup", action="store_true",
        help="Não rodar setup_homolog (assume stack já pronta)",
    )
    parser.add_argument(
        "--area", choices=["aws", "gcp", "azure", "software_architecture", "case_studies", "all"],
        default="all",
        help="Filtrar por knowledge area (default: all)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit 1 se qualquer caso falhar (gate de produção)",
    )
    parser.add_argument(
        "--timeout", type=float, default=120.0,
        help="Timeout por query em segundos (default: 120)",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Rodar cada caso N vezes e decidir PASS por MAIORIA (reduz "
             "falso-negativo por variância de temperatura). Default: 1 "
             "(comportamento single-run intacto). Ex.: --runs 3.",
    )
    parser.add_argument(
        "--report-md", default=str(ROOT / "eval" / "results" / "homolog_report.md"),
        help="Caminho do relatório Markdown",
    )
    parser.add_argument(
        "--report-json", default=str(ROOT / "eval" / "results" / "homolog_results.json"),
        help="Caminho do relatório JSON",
    )
    args = parser.parse_args()

    print("=" * 70)
    if args.api_url:
        print("  CIP - HOMOLOGAÇÃO COM LLM REAL (modo HTTP)")
    else:
        print("  CIP - HOMOLOGAÇÃO COM LLM REAL (modo direto via orchestrator)")
    print("=" * 70)

    # 1) Detecta provider
    provider = detect_active_provider()
    print(f"\n[1/4] Provider LLM: {provider}")
    try:
        require_real_provider(provider)
    except SystemExit as exc:
        print(str(exc))
        return 2
    print(f"  [OK] Provider real: {provider}")

    # 2) Setup opcional (só modo HTTP)
    if args.api_url and not args.skip_setup:
        if not step_setup(args.api_url):
            print("[FAIL] Setup não pôde garantir a stack. Tente --skip-setup.")
            return 2
        print("  [OK] Stack disponível")
    elif args.api_url:
        print("  [SKIP] Setup (--skip-setup)")

    # 3) Prepara suite
    suite = HOMOLOG_SUITE
    if args.area != "all":
        suite = [c for c in HOMOLOG_SUITE if c["area"] == args.area]
    print(f"\n[2/4] Rodando {len(suite)} caso(s) de homolog...")

    # Define mode (usado em logs e relatórios)
    mode = f"http://{args.api_url}" if args.api_url else "orchestrator direto"

    # 4) Executa suite
    results: list[HomologCaseResult] = []
    if args.api_url:
        # Modo HTTP (legacy)
        import httpx
        headers = {"X-Tenant-Id": args.tenant_id}
        if args.api_key:
            headers["X-API-Key"] = args.api_key
        try:
            with httpx.Client(base_url=args.api_url, headers=headers, timeout=180) as client:
                for case in suite:
                    print(f"  - {case['id']:24s} ({case['area']:22s})... ", end="", flush=True)
                    r = run_case_http(client, case, provider)
                    mark = "PASS" if r.passed else "FAIL"
                    print(f"{mark} acc={r.accuracy:.2f} lat={r.latency_ms}ms")
                    results.append(r)
        except Exception as e:
            print(f"\n[FAIL] HTTP client error: {e}")
            return 2
    else:
        # Modo direto via orchestrator (recomendado)
        print(f"  Inicializando orchestrator (carrega embedding model + LLM)...")
        try:
            run_case = _build_orchestrator_sync_runner(timeout_s=args.timeout)
            print(f"  [OK] Orchestrator pronto")
        except Exception as e:
            print(f"\n[FAIL] Erro ao inicializar orchestrator: {type(e).__name__}: {e}")
            return 2

        for case in suite:
            print(f"  - {case['id']:24s} ({case['area']:22s})... ", end="", flush=True)
            if args.runs <= 1:
                r = run_case(case, provider)
                mark = "PASS" if r.passed else "FAIL"
                extra = ""
                if r.error:
                    extra = f" ({r.error[:50]})"
                print(f"{mark} acc={r.accuracy:.2f} lat={r.latency_ms}ms src={r.sources_count}{extra}", flush=True)
                results.append(r)
            else:
                # Round 22.6: multi-run por maioria.
                runs: list[HomologCaseResult] = []
                for attempt in range(1, args.runs + 1):
                    rr = run_case(case, provider)
                    m = "PASS" if rr.passed else "FAIL"
                    runs.append(rr)
                    print(f"run{attempt}/{args.runs}={m}(acc={rr.accuracy:.2f}) ", end="", flush=True)
                r = _majority_result(runs)
                mark = "PASS" if r.passed else "FAIL"
                print(f"=> {mark} (maioria) acc={r.accuracy:.2f} lat={r.latency_ms}ms", flush=True)
                results.append(r)

            # Round 22+: salva progresso incremental a cada caso (proteção contra
            # morte silenciosa do processo Python — comum com asyncpg pool).
            _write_partial_report(results, args.report_md, args.report_json, provider, mode)

    # 5) Relatório final (substitui o parcial pelo completo)
    print(f"\n[3/4] Gerando relatório final...")
    Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
    md = render_report(results, provider, mode)
    Path(args.report_md).write_text(md, encoding="utf-8")

    payload = {
        "provider": provider,
        "mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(r) for r in results],
        "summary": {
            "n_cases": len(results),
            "n_passed": sum(1 for r in results if r.passed),
            "avg_accuracy": statistics.mean([r.accuracy for r in results if not r.error])
            if [r for r in results if not r.error] else 0,
            "avg_latency_ms": statistics.mean([r.latency_ms for r in results])
            if results else 0,
            "total_cost_usd": sum(r.cost_estimated_usd for r in results),
            "n_grounded": sum(1 for r in results if r.has_grounding),
            "n_errors": sum(1 for r in results if r.error),
        },
    }
    Path(args.report_json).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  - Markdown: {args.report_md}")
    print(f"  - JSON:     {args.report_json}")

    # 6) Veredicto
    n_fail = sum(1 for r in results if not r.passed)
    print(f"\n[4/4] Veredicto:")
    print(f"  {len(results) - n_fail}/{len(results)} passaram.")
    if n_fail == 0:
        print("  [OK] GATE DE HOMOLOG PASSOU.")
        return 0
    print(f"  [FAIL] {n_fail} caso(s) falharam.")
    if args.strict:
        return 1
    print("  (use --strict para exit 1)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
