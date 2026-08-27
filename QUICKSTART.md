# Quickstart — CIP em 5 minutos

> Guia de onboarding para rodar o CIP localmente em 5 minutos.
> **Audiência**: Engenheiros, Devs novos no projeto.

---

## 1. Pré-requisitos (1 min)

- **Python 3.11+**
- **PostgreSQL 16 com pgvector** — ou use o `docker-compose.yml`
- **Git**
- 2 GB de RAM disponível (para embeddings bge-large)

```bash
# Verificar versões
python --version  # 3.11+
git --version
psql --version     # ou use docker
```

---

## 2. Setup rápido (2 min)

### Opção A: Docker Compose (recomendado)

> O compose **reutiliza** o Postgres externo `cloudpilot_postgres` (pgvector:pg16);
> não sobe um Postgres próprio. O `cip-api` sobe na porta **8001** do host
> (8000 já é usado pelo `cloudpilot_backend`).

```bash
# 1. Clonar e entrar
git clone <repo-url> cip && cd cip

# 2. Pré-requisito (uma vez): garantir o Postgres externo de pé e na rede DNS
#    do compose. A rede default do podman tem dns_enabled=false, por isso o
#    cip-api só resolve `cloudpilot_postgres` pelo nome via a rede cip_default.
podman start cloudpilot_postgres
podman network connect cip_default cloudpilot_postgres

# 3. Subir API (usa o Postgres externo cloudpilot_postgres)
docker compose up -d

# 4. Aplicar migrations (primeira vez) no Postgres externo
docker exec cloudpilot_postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/002_relax_cloud_and_doc_type_constraints.sql
docker exec cloudpilot_postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/003_conversations_and_feedback.sql

# 5. Popular a knowledge base (MVP, ~700+ chunks em ~15 min)
#    IMPORTANTE (Podman WSL2 no Windows): a porta 5432 do host NÃO é alcançável
#    de fora dos containers (o forward do podman-machine rootful não chega em
#    127.0.0.1 do Windows). Por isso a ingestão roda DENTRO do container cip-api,
#    onde o DB é resolvido por DNS (cloudpilot_postgres:5432 na rede cip_default):
docker exec -d cip-api bash -c "nohup python -m cip.ingestion.ingest --scope mvp > /tmp/ingest.log 2>&1 &"

#    Acompanhar progresso (a tabela física é `data_cloud_docs`):
docker exec cloudpilot_postgres psql -U cip -d cip -tAc "SELECT COUNT(*) FROM data_cloud_docs"
docker exec cip-api tail -f /tmp/ingest.log

#    Validar readiness (deve virar HTTP 200 / healthy:true assim que houver chunks):
docker exec cip-api curl -s http://localhost:8000/health/ready

# 7. Subir UI standalone (chat multi-turn + feedback)
python scripts/serve_web.py --port 8080
# → http://localhost:8080 (UI)
# → http://localhost:8001 (API)
```

### Opção B: PostgreSQL local + venv

```bash
# 1. Clonar e entrar
git clone <repo-url> cip && cd cip

# 2. Criar venv e instalar
python -m venv .venv && source .venv/bin/activate
make install

# 3. Subir Postgres+pgvector (via Docker)
docker run -d --name cip-pg \
  -e POSTGRES_USER=cip -e POSTGRES_PASSWORD=cip -e POSTGRES_DB=cip \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# 4. Configurar .env
cp .env.example .env
# editar: DATABASE_URL=postgresql://cip:cip@localhost:5432/cip

# 5. Aplicar schema
make schema

# 6. Popular KB
make ingest
```

---

## 3. Rodar (30s)

```bash
# Iniciar API
make up
# API em http://localhost:8000

# Em outro terminal, testar
curl http://localhost:8000/health
# {"status":"ok","version":"0.2.0+integration","env":"dev","readonly":"true"}

# Teste real
curl -H "X-API-Key: dev-key" -H "X-Tenant-Id: default" \
     -d '{"question":"Quais os 6 pilares do AWS Well-Architected?"}' \
     -H "Content-Type: application/json" \
     http://localhost:8000/ask
```

**Modo dev**: API key não é necessária (warning log). Em prod, configure `CIP_API_KEYS=key:tenant:60` no `.env`.

---

## 4. Demo completa (1 min)

```bash
# 6 queries showcase (knowledge, comparison, inspection, FinOps, security)
make demo
# Saída inclui resposta + findings + sources para cada query

# Com mock cloud (recomendado se não tem credenciais AWS/Azure/GCP)
# Terminal 1:
make mock-server
# Terminal 2:
make demo-mock

# Com ReAct mode (raciocínio adaptativo)
make demo-react

# Chat multi-turn (Round 22+)
# Cria conversa + persiste + injeta historico no LLM
curl -X POST http://localhost:8000/chat/conversations \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"title":"FinOps Q&A"}' | jq .

# Feedback (👍/👎) em uma resposta
curl -X POST http://localhost:8000/chat/messages/<msg-uuid>/feedback \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"feedback":"up","note":"util"}' | jq .
```

---

## 5. Rodar testes (10s)

```bash
# Suite completa (~5min)
make test

# Suite rápida (CI, ~2min, sem smoke/ingest)
make test-fast

# Apenas ReAct
make test-react

# Apenas mock + integração
make test-mock
```

**Output esperado**: `590 passed in ~5min` (suite completa).

---

## 6. Próximos passos

| O que você quer fazer? | Comando |
|---|---|
| Ver arquitetura C4 | `cat docs/23-architecture-c4.md` |
| Ver ADRs (decisões) | `ls docs/adr/` |
| Ver API OpenAPI spec | `cat docs/openapi.json` |
| Validar produção (preflight) | `make preflight` |
| Ver métricas Prometheus | `curl localhost:8000/metrics` |
| Ver audit log | `cat .audit/audit.jsonl` |
| Rodar benchmark | `make bench` |
| Explorar KB (chunks) | `psql -c "SELECT COUNT(*) FROM data_cloud_docs"` |

---

## 🆘 Troubleshooting

| Erro | Solução |
|---|---|
| `connection refused` no DB | `docker compose ps` para ver se Postgres está rodando |
| `LLM stub ativo` no log | OK em dev. Em prod, configure `LLM_PROVIDER=bedrock` + AWS creds |
| `0 chunks` no log | Rode `make ingest` para popular a KB |
| Out of memory no embedding | Use `EMBED_PROVIDER=bedrock` (Titan) em vez de `local` |
| `permission denied` em `.audit/` | `mkdir -p .audit && chmod 700 .audit` |

---

## 📚 Próximos passos por papel

### Engenheiro de plataforma
1. `make install && make test-fast` para validar setup
2. `make preflight` para ver o que está faltando em prod
3. `make docs` para gerar OpenAPI spec
4. `cat docs/18-production-runbook.md` para deploy

### Arquiteto de Software (Round 22+)
1. `make homolog-software-arch` para validar a área de Software Architecture
2. `cat docs/adr/0002-pgvector-como-vector-db.md` para entender a base de RAG
3. Explore `eval/test_cases.json` → seção `software_architecture` para casos reais
4. Para adicionar nova pattern: edite `src/cip/prompts/specialists.py` (SOFTWARE_ARCHITECTURE)

### SRE focado em lições aprendidas (Round 22+)
1. `make homolog-cases` para validar a área de case studies
2. `make ingest-forum-cases` para puxar novos postmortems de HN/dev.to/Reddit
3. `cat docs/22-progresso-round-11.md` para padrões de recovery

### Engenheiro de ML/AI
1. `cat docs/05-fine-tuning.md` para entender o pipeline de fine-tuning
2. `python scripts/generate_finetune_dataset.py` para gerar dataset sintético
3. `python scripts/train_lora.py --validate-only` para validar config
4. `python scripts/eval_ab_finetune.py --help` para A/B eval

### SRE / Operador
1. `cat docs/18-production-runbook.md` (essencial)
2. `cat docs/24-progresso-round-12.md` (status atual)
3. `make preflight` antes de cada deploy
4. `cat docs/09-plano-execucao-llm-cloud.md` (plano original)

### Arquiteto Cloud
1. `cat docs/23-architecture-c4.md` (C4 architecture)
2. `cat docs/adr/0001-rag-first-em-vez-de-fine-tuning.md` (ADR-0001)
3. `cat docs/adr/0003-tools-read-only-para-dados-ao-vivo.md` (ADR-0003)
4. `cat docs/adr/0005-orchestrator-static-vs-react.md` (ADR-0005)

---

**Bem-vindo ao CIP! 🚀**

Se tiver problemas, abra uma issue no GitHub ou pergunte no time.

— Equipe CIP
