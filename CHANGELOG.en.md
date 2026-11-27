# Changelog

> Change history for CIP — Cloud Intelligence Platform.
> Format: [Keep a Changelog](https://keepachangelog.com/) adapted for round cycles.

---

## [Unreleased] — Round 14+

### Added (DeepInfra / Gemma 3 27B)
- `LLM_CONTEXT_TOP_K` default 4 -> 5 (6+ fixed the AKS node pools answer but broke the GCP pillars and DynamoDB ones; chunk size 1600/2000 changed nothing); `eval/ollama_compare.py` gains `--ctx-top-k`/`--chunk-chars`
- Production deploy with `LLM_PROVIDER=local` pointing to DeepInfra (`google/gemma-3-27b-it`), extractive fallback kept
- Ingested 3 pages (Cosmos DB consistency levels, K8s pod disruptions, AKS node pools): 2928 -> 2973 chunks
- Eval reports in `eval/reports/` (post-ingest: in-RAG false refusal 19% -> 0%)

### Added (local LLM / Ollama)
- `local` provider reads `LLM_BASE_URL`/`LLM_API_KEY` (was a hardcoded URL); new `LLM_FIRST_TOKEN_TIMEOUT_S`, `LLM_CONTEXT_TOP_K`, `LLM_CONTEXT_CHUNK_CHARS`
- Grounded generation (`rag/grounded.py`): numbered context, citation validation, automatic extractive fallback on error/timeout
- Real SSE streaming (chat, `/ask/stream`, `/analyze/stream`) with `LLM_PROVIDER=local`; `done` gains `fallback` and `ttft_ms`
- `ops/ollama/`: Ollama Quadlet unit (internal, CPU/memory limits open), env and instructions
- docs/53-ollama-local-llm.en.md

Planned:
- CHANGELOG.md (this file)
- Main README.md
- Executive summary one-pager
- Real production deployment (requires external credentials)
- Performance optimization (cache, connection pooling)

---

## [0.2.0+integration] — 2026-08-24 — Round 13 (DX)

### Added
- **Makefile** with 20+ targets (install, test, lint, demo, preflight, docs, ci-*)
- **QUICKSTART.md** — 5min onboarding with 2 options (Docker Compose / local)
- **CONTRIBUTING.md** — workflow, conventions (Conventional Commits), structure, patterns, code of conduct
- **VS Code dev container** (`.devcontainer/devcontainer.json`) — Python 3.11 + Postgres 16 + extensions
- **GitHub templates** (`.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`)
- **32 DX tests** (Makefile, Quickstart, Contributing, DevContainer, GitHub templates)
- **Stats:** 334 total tests (100% passing)

### Metrics
- Lines of code: ~9,600+
- Documents: 27+
- Makefile targets: 20+
- ADRs: 6

---

## [0.2.0+integration] — 2026-08-24 — Round 12 (Architecture Documentation)

### Added
- **C4 Architecture** (`docs/23-architecture-c4.md`) — 4 levels (System, Container, Component, Code) with Mermaid diagrams
- **OpenAPI spec export** (`scripts/export_openapi.py`) — generates `docs/openapi.json` from FastAPI
- **Demo script** (`scripts/demo.py`) — 6 showcase queries (knowledge, comparison, TF inspection, K8s inspection, FinOps, security)
- **ADR-0005**: Orchestrator — Static Mode + ReAct as Opt-in
- **ADR-0006**: Mock Cloud APIs for Dev/CI
- **15 documentation tests** (OpenAPI export, demo, C4, ADRs)

### Metrics
- Lines of code: ~8,500+
- Tests: 302
- Mermaid diagrams: 4 (C1-C4) + 2 sequence

---

## [0.2.0+integration] — 2026-08-24 — Round 11 (ReAct/Function-Calling)

### Added
- **ReAct module** (`src/cip/agents/react.py`) — Thought → Action → Observation loop with 4 tools
- **Tool schema** (OpenAI function calling-like): query_rag, invoke_specialist, get_live_data, inspect_iac
- **Robust JSON parser** with regex fallback
- **Graceful fallback** to static mode on error
- **Orchestrator integration** — `react_mode` flag (param + env var)
- **API schema** `react_mode` in `AnalyzeRequest`
- **19 ReAct tests** (tool schema, parser, tools, loop, orchestrator)

### Decisions
- Max 5 steps prevent infinite loops
- Default = static (backward compatible)
- ReAct opt-in via `CIP_REACT_MODE=true` or param

---

## [0.2.0+integration] — 2026-08-24 — Round 10 (Mock Wire-up + Load Test)

### Added
- **Mock client** (`src/cip/tools/mock_client.py`) — 7 HTTP call wrappers
- **Refactored tools** (AWS/Azure/GCP) with graceful fallback to mock
- **Full mock wire-up** — `CIP_USE_MOCK_CLOUDS=true` makes tools call the mock
- **Load testing script** (`scripts/load_test.py`) — validates p95 SLA < 5s
- **18 integration tests** (mock + tools + orchestrator)

### Decisions
- `CIP_USE_MOCK_CLOUDS=true` (env var) controls the mode
- `CIP_MOCK_CLOUD_URL` (default `http://127.0.0.1:8888`)
- Transparent mock: summary includes `[MOCK]` for auditing

---

## [0.2.0+integration] — 2026-08-24 — Round 9 (Mock Cloud + CLI)

### Added
- **Mock Cloud API Server** (`scripts/mock_cloud_server.py`) — 7 emulated endpoints
  - AWS: Cost Explorer, Rightsizing, Savings Plans, EC2 Volumes, EC2 EIPs
  - Azure: Advisor Recommendations
  - GCP: Recommender (3 types)
- **Unified CLI** (`scripts/cip_cli.py`) — 8 subcommands:
  - `status`, `ingest`, `eval`, `preflight`, `drift`, `audit`, `metrics`, `bench`
- **27 tests** (mock server + CLI)

### Decisions
- Deterministic mock (same request → same response) by seed
- Simulated latency (~200-700ms)
- JSON structure faithful to the official API

---

## [0.2.0+integration] — 2026-08-24 — Round 8 (Production Observability)

### Added
- **Deep health checks** (`src/cip/api/health.py`) — k8s-style:
  - `/health` — simple liveness
  - `/health/live` — liveness probe (no deps)
  - `/health/ready` — readiness probe (4 checks: DB, LLM, vector store, rate limiter)
- **Prometheus metrics** (`src/cip/observability.py`) — `/metrics` endpoint
  - Counters + histograms with per-tenant labels
  - Renders Prometheus text format
- **Audit logging** (`src/cip/observability.py`) — append-only JSONL
- **Pre-flight check** (`scripts/preflight.py`) — 7 gates before deploy
- **Production Runbook** (`docs/18-production-runbook.md`) — 400+ lines
- **24 tests** (health, metrics, audit, preflight)

### Metrics
- 8 total API endpoints (4 new)
- 7 pre-flight gates
- JSONL audit log format (LGPD-compliant)

---

## [0.2.0+integration] — 2026-08-24 — Round 7 (Fine-tuning Infra)

### Added
- **Dataset generator** (`scripts/generate_finetune_dataset.py`) — Alpaca format
- **Training script** (`scripts/train_lora.py`) — LoRA/QLoRA config
- **A/B eval framework** (`scripts/eval_ab_finetune.py`) — automated verdict
- **16 tests** (dataset gen, training config, A/B eval)

### Decisions
- Hyperparameters: r=64, alpha=128, dropout=0.05, lr=2e-4, 3 epochs
- Llama 3.3 8B (prototyping) or 70B (production)
- 30% minimum human review (ADR-0001)
- A/B eval blocks promotion if factual < baseline

---

## [0.2.0+integration] — 2026-08-24 — Round 6 (Production Hardening)

### Added
- **Auth middleware** (`src/cip/api/auth.py`) — X-API-Key + X-Tenant-Id
- **Rate limiting** per tenant (token bucket)
- **Tracing** (`src/cip/tracing.py`) — optional Langfuse + local stub
- **Monthly cron wrapper** (`scripts/monthly_cron.py`) — drift detection + re-ingest
- **CI/CD GitHub Actions** (`.github/workflows/ci.yml`) — 5 parallel jobs
- **Production Runbook draft**
- **28 tests** (auth, rate limit, tracing)

### Decisions
- Auth via `CIP_API_KEYS=key:tenant:rpm`
- Rate limit: token bucket with 60+ rpm default
- Langfuse: enabled if `LANGFUSE_PUBLIC_KEY` is set

---

## [0.2.0+integration] — 2026-08-24 — Round 5 (Quality Gate)

### Added
- **Automated 1-5 rubric** across 5 criteria (accuracy, grounding, citation, format, zero_price)
- **Production gate** — blocks if score < 4.0 OR cost > $0.05 OR zero-price > 5%
- **95 eval cases** (60 knowledge + 10 IAC + 5 compare + 10 sec + 10 cost)
- **Human review document** (`docs/14-revisao-humana.md`) — 9-10 day workflow
- **41 tests** (eval runner)

### Decisions
- ADR-0001: RAG-first (fine-tuning only for persona, never for knowledge)
- Score < 3.0 on accuracy = blocks go-live
- Target cost: < $0.05/query
- Zero-price violations > 5% = blocks

---

## [0.2.0+integration] — 2026-08-24 — Round 4 (Specialists)

### Added
- **8 specialists** (3 cloud-provider + 5 domain):
  - Provider: aws, gcp, azure
  - Domain: finops, security, sre, kubernetes, terraform
- **Improved router** (`src/cip/agents/router.py`) — expanded keywords, cap=3, provider+domain combination
- **Orchestrator with parallel execution** — `asyncio.gather` of specialists
- **42 tests** (router v2 + specialists)

### Decisions
- Cap=3 specialists per query (1-3, no more)
- Provider specialist → forces cloud filter
- Domain specialist → first detected cloud

---

## [0.2.0+integration] — 2026-08-24 — Round 3 (Inspection Engine)

### Added
- **Inspection Engine** (`src/cip/inspection/`) with 14 rules:
  - **7 Terraform**: S3 without encryption, open SG, oversized, without tags, without Multi-AZ, oversized instances, without prevent_destroy
  - **7 Kubernetes**: privileged container, without runAsNonRoot, without resource limits, without probes, hostNetwork, `:latest` image, broad RBAC
- **3 HCL parsing bugs** fixed (tags, lifecycle, instance_type)
- **33 positive/negative tests**

### Decisions
- Each finding has: severity, domain, $ impact, references
- Severities: critical / high / medium / low
- Domains: finops, security, reliability, performance, operations

---

## [0.2.0+integration] — 2026-08-24 — Round 2 (Live Tools)

### Added
- **AWS tools** (`src/cip/tools/aws_cost.py`) — Cost Explorer, Rightsizing, Savings Plans
- **Azure tools** (`src/cip/tools/azure_advisor.py`) — Advisor Cost/Security/HA
- **GCP tools** (`src/cip/tools/gcp_recommender.py`) — Cost, Idle, IAM
- **TTL Cache** (`src/cip/tools/cache.py`) — `@cached(ttl=3600)` decorator
- **14 tests** (cache + tools)
- Tools degrade gracefully if credentials are missing

### Decisions
- ADR-0003: Read-only tools (never mutate)
- 1h cache default (avoids rate limit)
- Optional mock via `CIP_USE_MOCK_CLOUDS` (implemented in Round 10)

---

## [0.2.0+integration] — 2026-08-24 — Round 1 (Functional MVP)

### Added
- **Complete RAG pipeline** (Postgres+pgvector + bge-large embeddings)
- **Sources** (`src/cip/ingestion/sources.yaml`) — 245 URLs, 100+ services
- **FastAPI API** — `/health`, `/ask`, `/analyze`
- **RAG Engine** (`src/cip/rag/engine.py`) — retrieval with cloud/service/category filters
- **LLM Provider** (`src/cip/rag/llm.py`) — abstract (bedrock/openai/local/stub)
- **Ingestion pipeline** — markdown-aware + semantic chunking
- **Embedding model** — `intfloat/multilingual-e5-small` (local) or Titan (Bedrock)

### Initial metrics
- 237 chunks indexed (MVP)
- 20 smoke-test questions, 100% grounding
- p95 latency: 1.9s

---

## [0.1.0] — 2026-07 (Planning)

### Architectural decisions (ADRs)
- **ADR-0001**: RAG-first (not fine-tuning for knowledge)
- **ADR-0002**: pgvector as the vector DB
- **ADR-0003**: Read-only tools for live data
- **ADR-0004**: Claude Sonnet 4.5 via Bedrock + local embeddings
- **ADR-0005**: Orchestrator — Static + ReAct opt-in (Round 11)
- **ADR-0006**: Mock Cloud APIs for Dev/CI (Round 9)

### Foundational documents
- `docs/01-analise-recomendacoes.md` — analysis of 3 approaches
- `docs/02-arquitetura.md` — architecture diagram
- `docs/03-roadmap.md` — 7 phases in 10-14 weeks
- `docs/04-modelo-de-dados.md` — SQL schema
- `docs/05-fine-tuning.md` — persona fine-tuning
- `docs/06-planejamento-proximas-fases.md` — critical path
- `docs/09-plano-execucao-llm-cloud.md` — complete plan

---

## Legend

- **Added** — new feature
- **Changed** — change to an existing feature
- **Fixed** — bug fix
- **Removed** — removed (rare)
- **Deprecated** — marked for future removal
- **Security** — vulnerability-related
- **Performance** — optimization
- **Documentation** — docs only

---

**Maintainer**: CIP Team
**Current version**: 0.2.0+integration
**Last updated**: 2026-08-24
