# Changelog

> Histórico de mudanças do CIP — Cloud Intelligence Platform.
> Formato: [Keep a Changelog](https://keepachangelog.com/) adaptado para ciclos de round.

---

## [Unreleased] — Round 14+

### Adicionado (DeepInfra / Gemma 3 27B)
- Deploy em produção com `LLM_PROVIDER=local` apontando para DeepInfra (`google/gemma-3-27b-it`), fallback extrativo mantido
- Ingestão de 3 páginas (Cosmos DB consistency levels, K8s pod disruptions, AKS node pools): 2928 -> 2973 chunks
- Relatórios de avaliação em `eval/reports/` (pós-ingestão: falsa recusa in-RAG 19% -> 0%)

### Adicionado (LLM local / Ollama)
- Provider `local` lê `LLM_BASE_URL`/`LLM_API_KEY` (antes URL fixa); novos `LLM_FIRST_TOKEN_TIMEOUT_S`, `LLM_CONTEXT_TOP_K`, `LLM_CONTEXT_CHUNK_CHARS`
- Geração fundamentada (`rag/grounded.py`): contexto numerado, validação de citações, fallback extrativo automático em erro/timeout
- Streaming SSE real (chat, `/ask/stream`, `/analyze/stream`) com `LLM_PROVIDER=local`; `done` ganha `fallback` e `ttft_ms`
- `ops/ollama/`: unit Quadlet do Ollama (interno, limites de CPU/memória em aberto), env e instruções
- docs/53-ollama-local-llm.md

Planejado:
- CHANGELOG.md (este arquivo)
- README.md principal
- Executive summary one-pager
- Production deployment real (requer credenciais externas)
- Performance optimization (cache, connection pooling)

---

## [0.2.0+integration] — 2026-08-24 — Round 13 (DX)

### Adicionado
- **Makefile** com 20+ targets (install, test, lint, demo, preflight, docs, ci-*)
- **QUICKSTART.md** — 5min onboarding com 2 opções (Docker Compose / local)
- **CONTRIBUTING.md** — workflow, convenções (Conventional Commits), estrutura, padrões, code of conduct
- **VS Code dev container** (`.devcontainer/devcontainer.json`) — Python 3.11 + Postgres 16 + extensions
- **GitHub templates** (`.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`)
- **32 testes DX** (Makefile, Quickstart, Contributing, DevContainer, GitHub templates)
- **Stats:** 334 testes totais (100% passing)

### Métricas
- Linhas de código: ~9.600+
- Documentos: 27+
- Makefile targets: 20+
- ADRs: 6

---

## [0.2.0+integration] — 2026-08-24 — Round 12 (Architecture Documentation)

### Adicionado
- **C4 Architecture** (`docs/23-architecture-c4.md`) — 4 níveis (System, Container, Component, Code) com diagramas Mermaid
- **OpenAPI spec export** (`scripts/export_openapi.py`) — gera `docs/openapi.json` do FastAPI
- **Demo script** (`scripts/demo.py`) — 6 queries showcase (knowledge, comparison, inspection TF, inspection K8s, FinOps, security)
- **ADR-0005**: Orchestrator — Modo Estático + ReAct como Opt-in
- **ADR-0006**: Mock Cloud APIs para Dev/CI
- **15 testes de documentação** (OpenAPI export, demo, C4, ADRs)

### Métricas
- Linhas de código: ~8.500+
- Testes: 302
- Diagramas Mermaid: 4 (C1-C4) + 2 sequence

---

## [0.2.0+integration] — 2026-08-24 — Round 11 (ReAct/Function-Calling)

### Adicionado
- **Módulo ReAct** (`src/cip/agents/react.py`) — loop Thought → Action → Observation com 4 tools
- **Tool schema** (OpenAI function calling-like): query_rag, invoke_specialist, get_live_data, inspect_iac
- **Parser JSON** robusto com regex fallback
- **Fallback gracioso** para modo estático em caso de erro
- **Integração no Orchestrator** — flag `react_mode` (param + env var)
- **API schema** `react_mode` no `AnalyzeRequest`
- **19 testes ReAct** (tool schema, parser, tools, loop, orchestrator)

### Decisões
- Max 5 steps previnem loops infinitos
- Default = estático (backward compatible)
- ReAct opt-in via `CIP_REACT_MODE=true` ou param

---

## [0.2.0+integration] — 2026-08-24 — Round 10 (Mock Wire-up + Load Test)

### Adicionado
- **Mock client** (`src/cip/tools/mock_client.py`) — 7 wrappers de chamada HTTP
- **Tools refatorados** (AWS/Azure/GCP) com fallback gracioso para mock
- **Mock wire-up completo** — `CIP_USE_MOCK_CLOUDS=true` faz tools chamarem mock
- **Load testing script** (`scripts/load_test.py`) — valida SLA p95 < 5s
- **18 testes integração** (mock + tools + orchestrator)

### Decisões
- `CIP_USE_MOCK_CLOUDS=true` (env var) controla modo
- `CIP_MOCK_CLOUD_URL` (default `http://127.0.0.1:8888`)
- Mock transparente: summary inclui `[MOCK]` para auditoria

---

## [0.2.0+integration] — 2026-08-24 — Round 9 (Mock Cloud + CLI)

### Adicionado
- **Mock Cloud API Server** (`scripts/mock_cloud_server.py`) — 7 endpoints emulados
  - AWS: Cost Explorer, Rightsizing, Savings Plans, EC2 Volumes, EC2 EIPs
  - Azure: Advisor Recommendations
  - GCP: Recommender (3 tipos)
- **CLI unificada** (`scripts/cip_cli.py`) — 8 subcomandos:
  - `status`, `ingest`, `eval`, `preflight`, `drift`, `audit`, `metrics`, `bench`
- **27 testes** (mock server + CLI)

### Decisões
- Mock determinístico (mesmo request → mesma response) por seed
- Latência simulada (~200-700ms)
- Estrutura JSON fiel à API oficial

---

## [0.2.0+integration] — 2026-08-24 — Round 8 (Production Observability)

### Adicionado
- **Health checks profundos** (`src/cip/api/health.py`) — k8s-style:
  - `/health` — liveness simples
  - `/health/live` — liveness probe (sem deps)
  - `/health/ready` — readiness probe (4 checks: DB, LLM, vector store, rate limiter)
- **Métricas Prometheus** (`src/cip/observability.py`) — endpoint `/metrics`
  - Counters + histograms com labels por tenant
  - Renderiza formato Prometheus text
- **Audit logging** (`src/cip/observability.py`) — JSONL append-only
- **Pre-flight check** (`scripts/preflight.py`) — 7 gates antes de deploy
- **Production Runbook** (`docs/18-production-runbook.md`) — 400+ linhas
- **24 testes** (health, metrics, audit, preflight)

### Métricas
- 8 endpoints API total (4 novos)
- 7 gates de pre-flight
- Audit log format JSONL (LGPD-compliant)

---

## [0.2.0+integration] — 2026-08-24 — Round 7 (Fine-tuning Infra)

### Adicionado
- **Dataset generator** (`scripts/generate_finetune_dataset.py`) — formato Alpaca
- **Training script** (`scripts/train_lora.py`) — LoRA/QLoRA config
- **A/B eval framework** (`scripts/eval_ab_finetune.py`) — verdict automatizado
- **16 testes** (dataset gen, training config, A/B eval)

### Decisões
- Hiperparâmetros: r=64, alpha=128, dropout=0.05, lr=2e-4, 3 épocas
- Llama 3.3 8B (prototipagem) ou 70B (produção)
- 30% revisão humana mínima (ADR-0001)
- A/B eval bloqueia promoção se factual < baseline

---

## [0.2.0+integration] — 2026-08-24 — Round 6 (Production Hardening)

### Adicionado
- **Auth middleware** (`src/cip/api/auth.py`) — X-API-Key + X-Tenant-Id
- **Rate limiting** por tenant (token bucket)
- **Tracing** (`src/cip/tracing.py`) — Langfuse opcional + stub local
- **Cron mensal wrapper** (`scripts/monthly_cron.py`) — drift detection + re-ingest
- **CI/CD GitHub Actions** (`.github/workflows/ci.yml`) — 5 jobs paralelos
- **Production Runbook draft**
- **28 testes** (auth, rate limit, tracing)

### Decisões
- Auth via `CIP_API_KEYS=key:tenant:rpm`
- Rate limit: token bucket com 60+ rpm default
- Langfuse: habilitado se `LANGFUSE_PUBLIC_KEY` setada

---

## [0.2.0+integration] — 2026-08-24 — Round 5 (Quality Gate)

### Adicionado
- **Rubrica 1-5 automatizada** em 5 critérios (accuracy, grounding, citation, format, zero_price)
- **Gate de produção** — bloqueia se score < 4.0 OU custo > $0.05 OU zero-price > 5%
- **95 casos de eval** (60 conhecimento + 10 IAC + 5 compare + 10 sec + 10 cost)
- **Documento de revisão humana** (`docs/14-revisao-humana.md`) — workflow 9-10 dias
- **41 testes** (eval runner)

### Decisões
- ADR-0001: RAG-first (fine-tuning só para persona, nunca para conhecimento)
- Score < 3.0 em accuracy = bloqueia go-live
- Custo alvo: < $0.05/query
- Zero-price violations > 5% = bloqueia

---

## [0.2.0+integration] — 2026-08-24 — Round 4 (Especialistas)

### Adicionado
- **8 especialistas** (3 provedor-cloud + 5 domínio):
  - Provedor: aws, gcp, azure
  - Domínio: finops, security, sre, kubernetes, terraform
- **Router melhorado** (`src/cip/agents/router.py`) — keywords expandidos, cap=3, combinação provedor+domínio
- **Orchestrator com execução paralela** — `asyncio.gather` de specialists
- **42 testes** (router v2 + specialists)

### Decisões
- Cap=3 specialists por query (1-3, não mais)
- Provedor specialist → força filtro cloud
- Domain specialist → primeiro cloud detectado

---

## [0.2.0+integration] — 2026-08-24 — Round 3 (Inspection Engine)

### Adicionado
- **Inspection Engine** (`src/cip/inspection/`) com 14 regras:
  - **7 Terraform**: S3 sem encryption, SG aberto, oversized, sem tags, sem Multi-AZ, oversized instances, sem prevent_destroy
  - **7 Kubernetes**: container privileged, sem runAsNonRoot, sem resource limits, sem probes, hostNetwork, imagem :latest, RBAC amplo
- **3 bugs de parsing HCL** corrigidos (tags, lifecycle, instance_type)
- **33 testes** positivos/negativos

### Decisões
- Cada finding tem: severity, domain, $ impact, references
- Severities: critical / high / medium / low
- Domains: finops, security, reliability, performance, operations

---

## [0.2.0+integration] — 2026-08-24 — Round 2 (Tools ao Vivo)

### Adicionado
- **Tools AWS** (`src/cip/tools/aws_cost.py`) — Cost Explorer, Rightsizing, Savings Plans
- **Tools Azure** (`src/cip/tools/azure_advisor.py`) — Advisor Cost/Security/HA
- **Tools GCP** (`src/cip/tools/gcp_recommender.py`) — Cost, Idle, IAM
- **TTL Cache** (`src/cip/tools/cache.py`) — `@cached(ttl=3600)` decorator
- **14 testes** (cache + tools)
- Tools se degradam gracefully se credenciais ausentes

### Decisões
- ADR-0003: Tools read-only (nunca mutam)
- Cache 1h default (evita rate limit)
- Mock opcional via `CIP_USE_MOCK_CLOUDS` (implementado Round 10)

---

## [0.2.0+integration] — 2026-08-24 — Round 1 (MVP Funcional)

### Adicionado
- **Pipeline RAG completo** (Postgres+pgvector + embeddings bge-large)
- **Sources** (`src/cip/ingestion/sources.yaml`) — 245 URLs, 100+ serviços
- **API FastAPI** — `/health`, `/ask`, `/analyze`
- **RAG Engine** (`src/cip/rag/engine.py`) — retrieval com filtros cloud/service/category
- **LLM Provider** (`src/cip/rag/llm.py`) — abstrato (bedrock/openai/local/stub)
- **Ingestion pipeline** — markdown-aware + semantic chunking
- **Embedding model** — `intfloat/multilingual-e5-small` (local) ou Titan (Bedrock)

### Métricas iniciais
- 237 chunks indexados (MVP)
- 20 perguntas smoke test 100% grounding
- Latência p95: 1.9s

---

## [0.1.0] — 2026-07 (Planejamento)

### Decisões arquiteturais (ADRs)
- **ADR-0001**: RAG-first (não fine-tuning para conhecimento)
- **ADR-0002**: pgvector como vector DB
- **ADR-0003**: Tools read-only para dados ao vivo
- **ADR-0004**: Claude Sonnet 4.5 via Bedrock + embeddings locais
- **ADR-0005**: Orchestrator — Estático + ReAct opt-in (Round 11)
- **ADR-0006**: Mock Cloud APIs para Dev/CI (Round 9)

### Documentos fundacionais
- `docs/01-analise-recomendacoes.md` — análise de 3 abordagens
- `docs/02-arquitetura.md` — diagrama de arquitetura
- `docs/03-roadmap.md` — 7 fases em 10-14 semanas
- `docs/04-modelo-de-dados.md` — schema SQL
- `docs/05-fine-tuning.md` — fine-tuning de persona
- `docs/06-planejamento-proximas-fases.md` — caminho crítico
- `docs/09-plano-execucao-llm-cloud.md` — plano completo

---

## Legenda

- **Adicionado** — nova feature
- **Modificado** — mudança em feature existente
- **Consertado** — bug fix
- **Removido** — removido (raro)
- **Deprecated** — marcado para remoção futura
- **Segurança** — relacionado a vulnerabilidades
- **Performance** — otimização
- **Documentação** — só docs

---

**Mantenedor**: Equipe CIP
**Versão atual**: 0.2.0+integration
**Última atualização**: 2026-08-24
