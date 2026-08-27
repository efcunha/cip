# Quickstart — CIP in 5 minutes

> Onboarding guide to run CIP locally in 5 minutes.
> **Audience**: Engineers, developers new to the project.

---

## 1. Prerequisites (1 min)

- **Python 3.11+**
- **PostgreSQL 16 with pgvector** — or use the `docker-compose.yml`
- **Git**
- 2 GB of available RAM (for bge-large embeddings)

```bash
# Check versions
python --version  # 3.11+
git --version
psql --version     # or use docker
```

---

## 2. Quick setup (2 min)

### Option A: Docker Compose (recommended)

> Compose **reuses** the external Postgres `cloudpilot_postgres` (pgvector:pg16);
> it does not start its own Postgres. `cip-api` starts on host port **8001**
> (8000 is already used by `cloudpilot_backend`).

```bash
# 1. Clone and enter
git clone <repo-url> cip && cd cip

# 2. Prerequisite (once): make sure the external Postgres is up and on the compose
#    DNS network. The podman default network has dns_enabled=false, so
#    cip-api only resolves `cloudpilot_postgres` by name via the cip_default network.
podman start cloudpilot_postgres
podman network connect cip_default cloudpilot_postgres

# 3. Start the API (uses the external Postgres cloudpilot_postgres)
docker compose up -d

# 4. Apply migrations (first time) to the external Postgres
docker exec cloudpilot_postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/002_relax_cloud_and_doc_type_constraints.sql
docker exec cloudpilot_postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/003_conversations_and_feedback.sql

# 5. Populate the knowledge base (MVP, ~700+ chunks in ~15 min)
#    IMPORTANT (Podman WSL2 on Windows): host port 5432 is NOT reachable
#    from outside the containers (rootful podman-machine forwarding does not reach
#    Windows 127.0.0.1). So ingestion runs INSIDE the cip-api container,
#    where the DB is resolved by DNS (cloudpilot_postgres:5432 on the cip_default network):
docker exec -d cip-api bash -c "nohup python -m cip.ingestion.ingest --scope mvp > /tmp/ingest.log 2>&1 &"

#    Track progress (the physical table is `data_cloud_docs`):
docker exec cloudpilot_postgres psql -U cip -d cip -tAc "SELECT COUNT(*) FROM data_cloud_docs"
docker exec cip-api tail -f /tmp/ingest.log

#    Validate readiness (should return HTTP 200 / healthy:true as soon as there are chunks):
docker exec cip-api curl -s http://localhost:8000/health/ready

# 7. Start the standalone UI (multi-turn chat + feedback)
python scripts/serve_web.py --port 8080
# → http://localhost:8080 (UI)
# → http://localhost:8001 (API)
```

### Option B: Local PostgreSQL + venv

```bash
# 1. Clone and enter
git clone <repo-url> cip && cd cip

# 2. Create venv and install
python -m venv .venv && source .venv/bin/activate
make install

# 3. Start Postgres+pgvector (via Docker)
docker run -d --name cip-pg \
  -e POSTGRES_USER=cip -e POSTGRES_PASSWORD=cip -e POSTGRES_DB=cip \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# 4. Configure .env
cp .env.example .env
# edit: DATABASE_URL=postgresql://cip:cip@localhost:5432/cip

# 5. Apply schema
make schema

# 6. Populate KB
make ingest
```

---

## 3. Run (30s)

```bash
# Start the API
make up
# API at http://localhost:8000

# In another terminal, test
curl http://localhost:8000/health
# {"status":"ok","version":"0.2.0+integration","env":"dev","readonly":"true"}

# Real test
curl -H "X-API-Key: dev-key" -H "X-Tenant-Id: default" \
     -d '{"question":"Quais os 6 pilares do AWS Well-Architected?"}' \
     -H "Content-Type: application/json" \
     http://localhost:8000/ask
```

**Dev mode**: API key is not required (warning log). In production, set `CIP_API_KEYS=key:tenant:60` in `.env`.

---

## 4. Full demo (1 min)

```bash
# 6 showcase queries (knowledge, comparison, inspection, FinOps, security)
make demo
# Output includes response + findings + sources for each query

# With mock cloud (recommended if you don't have AWS/Azure/GCP credentials)
# Terminal 1:
make mock-server
# Terminal 2:
make demo-mock

# With ReAct mode (adaptive reasoning)
make demo-react

# Multi-turn chat (Round 22+)
# Creates a conversation + persists it + injects history into the LLM
curl -X POST http://localhost:8000/chat/conversations \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"title":"FinOps Q&A"}' | jq .

# Feedback (👍/👎) on a response
curl -X POST http://localhost:8000/chat/messages/<msg-uuid>/feedback \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"feedback":"up","note":"util"}' | jq .
```

---

## 5. Run tests (10s)

```bash
# Full suite (~5min)
make test

# Fast suite (CI, ~2min, no smoke/ingest)
make test-fast

# ReAct only
make test-react

# Mock + integration only
make test-mock
```

**Expected output**: `302 passed in ~5min`.

---

## 6. Next steps

| What do you want to do? | Command |
|---|---|
| View C4 architecture | `cat docs/23-architecture-c4.md` |
| View ADRs (decisions) | `ls docs/adr/` |
| View API OpenAPI spec | `cat docs/openapi.json` |
| Validate production (preflight) | `make preflight` |
| View Prometheus metrics | `curl localhost:8000/metrics` |
| View audit log | `cat .audit/audit.jsonl` |
| Run benchmark | `make bench` |
| Explore KB (chunks) | `psql -c "SELECT COUNT(*) FROM data_cloud_docs"` |

---

## 🆘 Troubleshooting

| Error | Solution |
|---|---|
| `connection refused` on DB | `docker compose ps` to check if Postgres is running |
| `LLM stub ativo` in the log | OK in dev. In production, set `LLM_PROVIDER=bedrock` + AWS creds |
| `0 chunks` in the log | Run `make ingest` to populate the KB |
| Out of memory on embedding | Use `EMBED_PROVIDER=bedrock` (Titan) instead of `local` |
| `permission denied` on `.audit/` | `mkdir -p .audit && chmod 700 .audit` |

---

## 📚 Next steps by role

### Platform engineer
1. `make install && make test-fast` to validate setup
2. `make preflight` to see what's missing in production
3. `make docs` to generate the OpenAPI spec
4. `cat docs/18-production-runbook.md` for deployment

### Software Architect (Round 22+)
1. `make homolog-software-arch` to validate the Software Architecture area
2. `cat docs/adr/0002-rag-vector-store-choice.md` to understand the RAG foundation
3. Explore `eval/test_cases.json` → `software_architecture` section for real cases
4. To add a new pattern: edit `src/cip/prompts/specialists.py` (SOFTWARE_ARCHITECTURE)

### SRE focused on lessons learned (Round 22+)
1. `make homolog-cases` to validate the case studies area
2. `make ingest-forum-cases` to pull new postmortems from HN/dev.to/Reddit
3. `cat docs/22-sre-recovery-patterns.md` for recovery patterns

### ML/AI engineer
1. `cat docs/05-fine-tuning.md` to understand the fine-tuning pipeline
2. `python scripts/generate_finetune_dataset.py` to generate a synthetic dataset
3. `python scripts/train_lora.py --validate-only` to validate config
4. `python scripts/eval_ab_finetune.py --help` for A/B eval

### SRE / Operator
1. `cat docs/18-production-runbook.md` (essential)
2. `cat docs/24-progresso-round-12.md` (current status)
3. `make preflight` before each deploy
4. `cat docs/09-plano-execucao-llm-cloud.md` (original plan)

### Cloud Architect
1. `cat docs/23-architecture-c4.md` (C4 architecture)
2. `cat docs/adr/0001-rag-first-em-vez-de-fine-tuning.md` (ADR-0001)
3. `cat docs/adr/0003-tools-read-only-para-dados-ao-vivo.md` (ADR-0003)
4. `cat docs/adr/0005-orchestrator-static-vs-react.md` (ADR-0005)

---

**Welcome to CIP! 🚀**

If you run into issues, open an issue on GitHub or ask the team.

— CIP Team
