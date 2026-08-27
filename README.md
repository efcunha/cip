# Cloud Intelligence Platform (CIP)

LLM especialista em **AWS, GCP e Azure** que atua como um **engenheiro de cloud sênior**:
analisa ambientes reais, revisa infraestrutura (IaC + Kubernetes), detecta riscos e
sugere ajustes de arquitetura, segurança e custo — sempre com citação de fonte oficial.

> **Não é um chatbot genérico.** O conhecimento das clouds vive num banco vetorial
> (RAG) com metadados por provedor/serviço, e todo dado sensível a tempo (preço,
> inventário, recomendações) vem de **tools read-only ao vivo**, nunca dos pesos do modelo.

> **Knowledge areas expandidos (Round 22+)**: além de AWS/GCP/Azure, a base agora
> inclui **Software Architecture patterns** (microservices, CQRS, circuit breaker,
> saga, event sourcing) e **case studies / postmortems** de HackerNews, dev.to,
> Reddit e blogs de engenharia (Netflix, LinkedIn, Uber, Cloudflare, Stripe, …).
> Tudo preservando o foco principal em arquitetura cloud.

[![Tests](https://img.shields.io/badge/tests-590%20passed%2F0%20failed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/license-Apache--2.0-green)]()
[![Version](https://img.shields.io/badge/version-0.2.0%2Bintegration-orange)]()

---

## Princípios de design

1. **RAG é o cérebro** — conhecimento das clouds indexado em `pgvector`, não gravado no modelo.
2. **Tools para dados ao vivo** — Cost Explorer, Azure Advisor, GCP Recommender (read-only).
3. **Especialistas por domínio** — orquestrador roteia para AWS / GCP / Azure / Kubernetes / Terraform / FinOps / Security / Reliability / Platform Engineering / Software Architecture.
4. **Read-only por padrão** — zero permissão de escrita em ambientes de produção.
5. **Fine-tuning por último** — só para persona/formato, depois do RAG validado (fase opcional).

Ver a fundamentação da escolha em [`docs/01-analise-recomendacoes.md`](docs/01-analise-recomendacoes.md).

---

## Arquitetura (resumo)

```
Usuário ─► API (FastAPI) ─► Orquestrador ─┬─► Retriever ─► pgvector (docs oficiais)
                                          ├─► Especialistas (AWS/GCP/Azure/K8s/TF/FinOps/Sec)
                                          ├─► Cloud Tools (read-only, dados ao vivo)
                                          └─► Inspection Engine (Terraform/K8s/Helm)
                                                    │
                                              LLM (Bedrock/OpenAI/MiniMax/DeepSeek/local)
                                                    │
                                     Resposta estruturada + citações + priorização
```

Detalhes em [`docs/02-arquitetura.md`](docs/02-arquitetura.md).

---

## Quickstart (5 min)

```bash
# 1. Setup
git clone <repo> && cd cip
make install

# 2. Subir Postgres+pgvector (via Docker)
docker run -d --name cip-pg \
  -e POSTGRES_USER=cip -e POSTGRES_PASSWORD=cip -e POSTGRES_DB=cip \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# 3. Configurar (dev: aceita sem credenciais)
cp .env.example .env
# editar DATABASE_URL=postgresql://cip:cip@localhost:5432/cip

# 4. Aplicar schema + migrations (requer DATABASE_URL e o binário psql)
make schema
make schema-migrate

# 5. Ingerir a base de conhecimento MVP (Well-Architected das 3 clouds)
make ingest

# 6. Subir a API
make up
# API em http://localhost:8000

# 7. Testar
curl http://localhost:8000/health
curl -X POST localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question":"Como reduzir custo de EC2?","cloud":"aws"}'
```

**Targets Makefile úteis:**

```bash
make help                 # Lista 30+ targets
make demo                 # Demo end-to-end (6 queries showcase)
make test                 # Roda 590+ testes
make preflight            # 7 gates antes de deploy
make docs                 # Exporta OpenAPI spec
make homolog              # Setup completo de homolog (stub LLM)
make homolog-real         # Homolog com LLM REAL (MiniMax M3 / Bedrock)
make homolog-software-arch # Homolog focado em Software Architecture patterns
make homolog-cases        # Homolog focado em case studies / postmortems
make ingest-forum-cases   # Busca + ingest de postmortems em HN/dev.to/Reddit
make schema-migrate       # Aplica migrations SQL pendentes
```

### Homologação com LLM Real (MiniMax M3, Bedrock, OpenAI)

Para validar a qualidade real do LLM antes de produção:

```bash
# 1. Subir stack
make homolog

# 2. Configurar LLM real
export LLM_PROVIDER=minimax
export LLM_MODEL=MiniMax-M3
export LLM_API_KEY=sk-cp-...

# 3. Rodar homolog end-to-end (~30s, 5 knowledge areas, ~10 queries)
make homolog-real

# Relatórios em eval/results/homolog_report.{md,json}
```

Ver [`docs/32-homolog-with-real-llm.md`](docs/32-homolog-with-real-llm.md) para o guia completo.

Ver [QUICKSTART.md](QUICKSTART.md) para guia completo com troubleshooting.

---

## Estrutura do repositório

```
cloud-intelligence-platform/
├── README.md / README.en.md    # documentação principal (PT-BR / EN)
├── CHANGELOG.md / .en.md       # histórico de mudanças
├── CONTRIBUTING.md / .en.md    # guia de contribuição
├── QUICKSTART.md / .en.md      # guia de início rápido
├── pyproject.toml              # dependências e config de tooling
├── .env.example                # variáveis de ambiente
├── Dockerfile                  # imagem da API
├── docker-compose.yml          # API + Web UI + Postgres (dev)
├── docker-compose.prod.yml     # stack self-contained (Postgres próprio + bootstrap)
├── Makefile                    # atalhos: make ingest / make eval / make up / make homolog
├── mcp-config.json             # config MCP Server para editores (Cursor/Kiro/Claude)
├── db/
│   ├── schema.sql              # tabelas cloud_docs, environments, analyses, findings + HNSW
│   ├── curated/                # fontes de conhecimento curadas (versionadas)
│   └── migrations/             # migrations SQL aplicadas via make schema-migrate
├── docs/
│   ├── 01-analise-recomendacoes.md   # análise das 3 propostas + decisão
│   ├── 02-arquitetura.md             # arquitetura C4
│   ├── 03-roadmap.md                 # roadmap por fases
│   ├── 04-modelo-de-dados.md         # schema + relações
│   ├── mcp-server.md / .en.md        # documentação do MCP Server
│   ├── RELEASE.md / .en.md           # guia de release/deploy
│   ├── homologation.md / .en.md      # procedimento de homologação
│   ├── EXECUTIVE_SUMMARY.md / .en.md # resumo executivo
│   ├── 10..52-progresso-round-*.md   # registros de progresso (rounds 1-26)
│   └── adr/                          # Architecture Decision Records
├── src/cip/
│   ├── config.py               # settings via env
│   ├── mcp_server.py           # MCP Server (3 tools: cip_ask, cip_inspect, cip_analyze)
│   ├── logging.py              # logging estruturado (structlog)
│   ├── observability.py        # métricas e tracing
│   ├── prompts/                # system prompts (persona + especialistas)
│   ├── rag/                    # embeddings, retriever, engine
│   ├── ingestion/              # crawler/chunker/ingest + sources.yaml
│   ├── agents/                 # orquestrador + 8 especialistas de domínio
│   ├── tools/                  # wrappers read-only por cloud (pricing, inventory)
│   ├── inspection/             # Terraform (7 regras) / Kubernetes (7 regras)
│   └── api/                    # FastAPI (REST + WebSocket + auth + rate limit)
├── eval/
│   ├── test_cases.json         # suíte de 95 cenários
│   ├── run_eval.py             # runner com rubrica 1-5 + gate de produção
│   └── results/                # resultados de homologação
├── iac/
│   ├── aws-readonly-policy.json
│   ├── azure-setup.sh
│   └── gcp-setup.sh
├── ops/
│   └── grafana/                # dashboards de observabilidade
├── scripts/                    # utilitários (CLI, load test, homolog, fine-tune, etc.)
├── web/                        # Web UI (HTML + JS + CSS)
└── tests/                      # testes unitários e de integração
```

---

## Roadmap resumido

| Fase | Entrega | Status |
|---|---|---|
| 1A | MVP Funcional (RAG + API) | ✅ |
| 1B | Ingestion Hardening (idempotência, drift) | ✅ |
| 2 | Tools cloud read-only (mock wire-up completo) | ✅ |
| 3 | Inspection Engine (14 regras: 7 TF + 7 K8s) | ✅ |
| 4 | 8 Especialistas de domínio + ReAct/function-calling | ✅ |
| 5 | Quality Gate (rubrica 1-5 + 95 casos) | ✅ |
| 6 | Production Hardening (auth, rate limit, CI/CD) | ✅ |
| 7 | Fine-tuning infra (opcional) | ✅ |
| **Deploy** | Standalone self-contained (podman/podman compose) | ✅ Ver `docs/RELEASE.md` |
| **Eval real** | Validação com LLM real (MiniMax M3 / DeepSeek) | ✅ Rounds 19–22 |
| **MCP Server** | Expõe CIP como tool para agentes externos (Cursor/Kiro/Claude) | ✅ Ver [`docs/mcp-server.md`](docs/mcp-server.md) |

Detalhes e critérios de aceite em [`docs/09-plano-execucao-llm-cloud.md`](docs/09-plano-execucao-llm-cloud.md) e [`CHANGELOG.md`](CHANGELOG.md).

## Segurança

- Credenciais **temporárias** (STS / Workload Identity / Managed Identity).
- Escopo IAM **mínimo e read-only** — ver `iac/`.
- Preço/inventário nunca inferidos pelo modelo: sempre de tool ao vivo.
- Logs de prompt mascaram PII (LGPD/GDPR).
- API key + tenant_id em cada request (multi-tenant isolation).
- Audit log JSONL com retenção configurável.
- Rate limit por tenant (token bucket).

## Métricas do projeto

- **590+ testes** (baseline da homologação fechada; 0 failed)
- **Latência p95**: 1.9s (com stub LLM)
- **4.785 chunks** indexados (KB completa) — expansível com `--expand`
- **11 especialistas** (3 cloud + 8 domain)
- **14 regras Inspection** (7 TF + 7 K8s)
- **95 casos de eval** (gate de qualidade)
- **6 ADRs** documentados
- **~12.900+ linhas** de código (src/ + tests/)
- **64 documentos** (docs/ + raiz, com versões `.en.md` em inglês)
- **20+ Makefile targets**
- **3 GitHub templates** (bug, feature, PR)

## Documentação adicional

| Documento | Conteúdo |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | 5min onboarding (Docker + local) |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow, convenções, code of conduct |
| [CHANGELOG.md](CHANGELOG.md) | Histórico round-by-round |
| [docs/23-architecture-c4.md](docs/23-architecture-c4.md) | C4 architecture (System, Container, Component, Code) |
| [docs/18-production-runbook.md](docs/18-production-runbook.md) | Runbook de produção (deploy + monitoring + incidents) |
| [docs/14-revisao-humana.md](docs/14-revisao-humana.md) | Workflow de revisão humana (5 arquitetos × 20 casos) |
| [docs/adr/](docs/adr/) | 6 ADRs (RAG-first, pgvector, read-only, etc.) |
| OpenAPI spec | Gerado do FastAPI via `make docs` → `docs/openapi.json` |
