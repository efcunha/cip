# Cloud Intelligence Platform (CIP)

LLM specialized in **AWS, GCP and Azure** that acts as a **senior cloud engineer**:
analyzes real environments, reviews infrastructure (IaC + Kubernetes), detects risks and
suggests architecture, security and cost adjustments — always citing an official source.

> **This is not a generic chatbot.** Cloud knowledge lives in a vector database
> (RAG) with metadata by provider/service, and all time-sensitive data (pricing,
> inventory, recommendations) comes from **live read-only tools**, never from the model weights.

> **Expanded knowledge areas (Round 22+)**: beyond AWS/GCP/Azure, the base now
> includes **Software Architecture patterns** (microservices, CQRS, circuit breaker,
> saga, event sourcing) and **case studies / postmortems** from HackerNews, dev.to,
> Reddit and engineering blogs (Netflix, LinkedIn, Uber, Cloudflare, Stripe, …).
> All while keeping the primary focus on cloud architecture.

[![Tests](https://img.shields.io/badge/tests-590%20passed%2F0%20failed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/license-Apache--2.0-green)]()
[![Version](https://img.shields.io/badge/version-0.2.0%2Bintegration-orange)]()

---

## Design principles

1. **RAG is the brain** — cloud knowledge indexed in `pgvector`, not baked into the model.
2. **Tools for live data** — Cost Explorer, Azure Advisor, GCP Recommender (read-only).
3. **Domain specialists** — the orchestrator routes to AWS / GCP / Azure / Kubernetes / Terraform / FinOps / Security / Reliability / Platform Engineering / Software Architecture.
4. **Read-only by default** — zero write permissions in production environments.
5. **Fine-tuning last** — only for persona/format, after RAG is validated (optional phase).

See the rationale for this choice in [`docs/01-analise-recomendacoes.md`](docs/01-analise-recomendacoes.md).

---

## Architecture (summary)

```
User ─► API (FastAPI) ─► Orchestrator ─┬─► Retriever ─► pgvector (official docs)
                                       ├─► Specialists (AWS/GCP/Azure/K8s/TF/FinOps/Sec)
                                       ├─► Cloud Tools (read-only, live data)
                                       └─► Inspection Engine (Terraform/K8s/Helm)
                                                 │
                                           LLM (Bedrock/OpenAI/MiniMax/DeepSeek/local)
                                                 │
                                  Structured response + citations + prioritization
```

Details in [`docs/02-arquitetura.md`](docs/02-arquitetura.md).

---

## Quickstart (5 min)

```bash
# 1. Setup
git clone <repo> && cd cip
make install

# 2. Start Postgres+pgvector (via Docker)
docker run -d --name cip-pg \
  -e POSTGRES_USER=cip -e POSTGRES_PASSWORD=cip -e POSTGRES_DB=cip \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# 3. Configure (dev: works without credentials)
cp .env.example .env
# edit DATABASE_URL=postgresql://cip:cip@localhost:5432/cip

# 4. Apply schema + migrations (requires DATABASE_URL and the psql binary)
make schema
make schema-migrate

# 5. Ingest the MVP knowledge base (Well-Architected from the 3 clouds)
make ingest

# 6. Start the API
make up
# API at http://localhost:8000

# 7. Test
curl http://localhost:8000/health
curl -X POST localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question":"Como reduzir custo de EC2?","cloud":"aws"}'
```

**Useful Makefile targets:**

```bash
make help                 # Lists 30+ targets
make demo                 # End-to-end demo (6 showcase queries)
make test                 # Runs 590+ tests
make preflight            # 7 gates before deploy
make docs                 # Exports OpenAPI spec
make homolog              # Full homolog setup (stub LLM)
make homolog-real         # Homolog with REAL LLM (MiniMax M3 / Bedrock)
make homolog-software-arch # Homolog focused on Software Architecture patterns
make homolog-cases        # Homolog focused on case studies / postmortems
make ingest-forum-cases   # Fetch + ingest postmortems from HN/dev.to/Reddit
make schema-migrate       # Applies pending SQL migrations
```

### Homologation with a Real LLM (MiniMax M3, Bedrock, OpenAI)

To validate the real LLM quality before production:

```bash
# 1. Start the stack
make homolog

# 2. Configure the real LLM
export LLM_PROVIDER=minimax
export LLM_MODEL=MiniMax-M3
export LLM_API_KEY=sk-cp-...

# 3. Run end-to-end homolog (~30s, 5 knowledge areas, ~10 queries)
make homolog-real

# Reports in eval/results/homolog_report.{md,json}
```

See [`docs/32-homolog-with-real-llm.md`](docs/32-homolog-with-real-llm.md) for the complete guide.

See [QUICKSTART.md](QUICKSTART.md) for the complete guide with troubleshooting.

---

## Repository structure

```
cloud-intelligence-platform/
├── README.md / README.en.md    # main documentation (PT-BR / EN)
├── CHANGELOG.md / .en.md       # change history
├── CONTRIBUTING.md / .en.md    # contribution guide
├── QUICKSTART.md / .en.md      # quickstart guide
├── pyproject.toml              # dependencies and tooling config
├── .env.example                # environment variables
├── Dockerfile                  # API image
├── docker-compose.yml          # API + Web UI + Postgres (dev)
├── docker-compose.prod.yml     # self-contained stack (own Postgres + bootstrap)
├── Makefile                    # shortcuts: make ingest / make eval / make up / make homolog
├── mcp-config.json             # MCP Server config for editors (Cursor/Kiro/Claude)
├── db/
│   ├── schema.sql              # cloud_docs, environments, analyses, findings + HNSW indexes
│   ├── curated/                # curated knowledge sources (versioned)
│   └── migrations/             # SQL migrations applied via make schema-migrate
├── docs/
│   ├── 01-analise-recomendacoes.md   # analysis of the 3 proposals + decision
│   ├── 02-arquitetura.md             # C4 architecture
│   ├── 03-roadmap.md                 # phased roadmap
│   ├── 04-modelo-de-dados.md         # schema + relations
│   ├── mcp-server.md / .en.md        # MCP Server documentation
│   ├── RELEASE.md / .en.md           # release/deploy guide
│   ├── homologation.md / .en.md      # homologation procedure
│   ├── EXECUTIVE_SUMMARY.md / .en.md # executive summary
│   ├── 10..52-progresso-round-*.md   # progress records (rounds 1-26)
│   └── adr/                          # Architecture Decision Records
├── src/cip/
│   ├── config.py               # settings via env
│   ├── mcp_server.py           # MCP Server (3 tools: cip_ask, cip_inspect, cip_analyze)
│   ├── logging.py              # structured logging (structlog)
│   ├── observability.py        # metrics and tracing
│   ├── prompts/                # system prompts (persona + specialists)
│   ├── rag/                    # embeddings, retriever, engine
│   ├── ingestion/              # crawler/chunker/ingest + sources.yaml
│   ├── agents/                 # orchestrator + 8 domain specialists
│   ├── tools/                  # read-only wrappers per cloud (pricing, inventory)
│   ├── inspection/             # Terraform (7 rules) / Kubernetes (7 rules)
│   └── api/                    # FastAPI (REST + WebSocket + auth + rate limit)
├── eval/
│   ├── test_cases.json         # suite of 95 scenarios
│   ├── run_eval.py             # runner with 1-5 rubric + production gate
│   └── results/                # homologation results
├── iac/
│   ├── aws-readonly-policy.json
│   ├── azure-setup.sh
│   └── gcp-setup.sh
├── ops/
│   └── grafana/                # observability dashboards
├── scripts/                    # utilities (CLI, load test, homolog, fine-tune, etc.)
├── web/                        # Web UI (HTML + JS + CSS)
└── tests/                      # unit and integration tests
```

---

## Summary roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 1A | Functional MVP (RAG + API) | ✅ |
| 1B | Ingestion Hardening (idempotency, drift) | ✅ |
| 2 | Read-only cloud tools (full mock wire-up) | ✅ |
| 3 | Inspection Engine (14 rules: 7 TF + 7 K8s) | ✅ |
| 4 | 8 domain Specialists + ReAct/function-calling | ✅ |
| 5 | Quality Gate (1-5 rubric + 95 cases) | ✅ |
| 6 | Production Hardening (auth, rate limit, CI/CD) | ✅ |
| 7 | Fine-tuning infra (optional) | ✅ |
| **Deploy** | Standalone self-contained (podman/podman compose) | ✅ See `docs/RELEASE.md` |
| **Real eval** | Validation with a real LLM (MiniMax M3 / DeepSeek) | ✅ Rounds 19–22 |
| **MCP Server** | Exposes CIP as a tool for external agents (Cursor/Kiro/Claude) | ✅ See [`docs/mcp-server.en.md`](docs/mcp-server.en.md) |

Details and acceptance criteria in [`docs/09-plano-execucao-llm-cloud.md`](docs/09-plano-execucao-llm-cloud.md) and [`CHANGELOG.md`](CHANGELOG.md).

## Security

- **Temporary** credentials (STS / Workload Identity / Managed Identity).
- **Minimal, read-only** IAM scope — see `iac/`.
- Pricing/inventory never inferred by the model: always from a live tool.
- Prompt logs mask PII (LGPD/GDPR).
- API key + tenant_id in every request (multi-tenant isolation).
- JSONL audit log with configurable retention.
- Per-tenant rate limit (token bucket).

## Project metrics

- **590+ tests** (closed homologation baseline; 0 failed)
- **p95 latency**: 1.9s (with stub LLM)
- **4,785 chunks** indexed (full KB) — expandable with `--expand`
- **11 specialists** (3 cloud + 8 domain)
- **14 Inspection rules** (7 TF + 7 K8s)
- **95 eval cases** (quality gate)
- **6 ADRs** documented
- **~12,900+ lines** of code (src/ + tests/)
- **64 documents** (docs/ + root, with English `.en.md` versions)
- **20+ Makefile targets**
- **3 GitHub templates** (bug, feature, PR)

## Additional documentation

| Document | Content |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | 5min onboarding (Docker + local) |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow, conventions, code of conduct |
| [CHANGELOG.md](CHANGELOG.md) | Round-by-round history |
| [docs/23-architecture-c4.md](docs/23-architecture-c4.md) | C4 architecture (System, Container, Component, Code) |
| [docs/18-production-runbook.md](docs/18-production-runbook.md) | Production runbook (deploy + monitoring + incidents) |
| [docs/14-revisao-humana.md](docs/14-revisao-humana.md) | Human review workflow (5 architects × 20 cases) |
| [docs/adr/](docs/adr/) | 6 ADRs (RAG-first, pgvector, read-only, etc.) |
| OpenAPI spec | Generated from FastAPI via `make docs` → `docs/openapi.json` |
