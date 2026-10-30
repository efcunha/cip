# Execution Plan — AWS/GCP/Azure Specialist LLM

> **Version**: 1.0 | **Date**: 2026-08-19 | **Status**: APPROVED FOR EXECUTION
> **Objective**: Operationalize CIP as a non-generic specialist LLM for the 3 clouds, going from the current state (architecture ready) to production with score ≥ 4.0 and cost < $0.05/query.

---

## 1. 🎯 Final Objective

Put into production an **LLM specializing in AWS, GCP and Azure** that:

- ✅ Answers technical questions with **mandatory citation** of an official source
- ✅ Analyzes real environments (cost, inventory) via **read-only tools** live
- ✅ Inspects IaC code (Terraform/HCL) and Kubernetes/Helm generating **prioritized findings**
- ✅ Operates multi-tenant with **isolation by `tenant_id`**
- ✅ Has **score ≥ 4.0/5.0** on a senior architect rubric
- ✅ Costs **< $0.05 per query**
- ✅ Latency **p95 < 5s** (MVP) / **< 8s** (with specialists)
- ✅ **Zero inferred price** (100% via live tool)

---

## 2. 🧭 Non-Negotiable Principles

1. **RAG-first, fine-tuning only for persona** (ADR-0001). Factual knowledge never goes into the weights — prices and services change weekly.
2. **Mandatory anti-hallucination**: no retrieved context (`min_score=0.80`) → answer "no reliable reference found".
3. **Service whitelist** in the system prompt prevents invention of services.
4. **Read-only tools** with global lock `CIP_READONLY=true` (ADR-0003).
5. **Mandatory citation** `[cloud, service, title, url]` in every answer.
6. **Local-first pipeline**: implement → homologate locally → validate E2E → deploy.
7. **Human gate** between phases (review before advancing).

---

## 3. 📊 Current State (Snapshot)

| Component | Status | Gap |
|---|---|---|
| Config + Settings | ✅ Ready | — |
| FastAPI API | ✅ Ready | — |
| RAG Engine | ✅ Ready | Missing populating `cloud_docs` |
| Ingestion pipeline (structure) | ✅ Ready | `sources.yaml` empty |
| Router/Classifier | ✅ Ready | — |
| Orchestrator | ✅ Ready | Basic logic; advanced specialists pending |
| AWS/Azure/GCP tools (wrappers) | ✅ Structure | Real calls not implemented |
| Inspection Engine (dispatch) | ✅ Structure | Functional TF/K8s rules pending |
| SQL schema + pgvector | ✅ Ready | HNSW index to create |
| IAC (policies) | ✅ Ready | — |
| Tests | ⚠️ 5 suites | Basic coverage, missing integration tests |
| Eval suite | ⚠️ Placeholder | 60 scenarios to expand |
| Documentation | ✅ 18 docs | Master plan + 7 ADRs + roadmap |

---

## 4. 🛣️ Execution Phases

```
[1A Functional MVP] ─┬─► [2 Live tools] ─► [3 Inspection] ─► [4 Specialists] ─► [5 Eval] ─► [6 Production] ─► [Production Live]
                     │
                     └─► [1B Ingestion hardening] (parallel)
                                                                                           └─► [7 Optional fine-tuning]
```

### Priority legend
- 🔴 **Critical** (production blocker)
- 🟡 **Important** (differentiation vs. competitors)
- 🟢 **Desirable** (quality of life)

---

### 🔴 PHASE 1A — Functional End-to-End MVP (1-2 weeks)

**Objective:** `/ask` returns well-grounded answers for the 3 clouds, with citation and acceptable latency.

#### Tasks

| # | Task | Effort | Dependency | Deliverable |
|---|---|---|---|---|
| 1A.1 | Populate `ingestion/sources.yaml` with real URLs (Well-Architected AWS, Architecture Framework GCP, WAF Azure) | 4h | — | YAML with 50+ prioritized URLs |
| 1A.2 | Bring up Postgres+pgvector via `docker compose` (local port 5432) | 2h | — | DB running + HNSW index created |
| 1A.3 | Configure Bedrock in `.env` (or `stub` fallback for dev) | 2h | AWS account | `LLM_PROVIDER=bedrock` responding |
| 1A.4 | Run `python -m cip.ingestion.ingest` with MVP catalog | 4h | 1A.1, 1A.2 | ~5k chunks indexed |
| 1A.5 | Validate retrieval end-to-end (8 docs, score ≥ 0.80) | 2h | 1A.4 | Logs with scores |
| 1A.6 | Smoke test `/ask` with 20 questions (10 AWS, 5 GCP, 5 Azure) | 4h | 1A.5 | Answers with citation in Markdown |
| 1A.7 | Document local demo in the README | 2h | 1A.6 | `README.md` updated |

**Total effort:** ~22h | **Duration:** 1 week (1 full-time dev)

#### Acceptance Criteria

- [ ] 20 questions answered with a cited source
- [ ] Latency p95 < 5s
- [ ] Zero answers without grounding
- [ ] `docker compose up` → complete local demo

---

### 🟢 PHASE 1B — Ingestion Hardening (parallel, 1 week)

**Objective:** Reliable, idempotent and observable ingestion.

#### Tasks

| # | Task | Effort | Deliverable |
|---|---|---|---|
| 1B.1 | Implement dedupe by `content_hash` on upsert | 3h | `ON CONFLICT (content_hash) DO UPDATE` |
| 1B.2 | Markdown-aware chunking (headers as boundaries) | 4h | Tested semantic parser |
| 1B.3 | Progress tracking + resume on failure | 4h | Checkpoint in JSON |
| 1B.4 | `--dry-run` mode for validation | 2h | CLI flag |
| 1B.5 | Monthly cron + drift detection via changelog diff | 4h | Scheduled job + alert |
| 1B.6 | Structured logs with per-source count | 2h | structlog events |
| 1B.7 | Ingestion regression tests | 3h | 5+ pytest cases |

**Total effort:** ~22h | **Duration:** 1 week (parallel to 1A)

#### Acceptance Criteria

- [ ] Idempotent re-ingestion (zero duplicates)
- [ ] Partial failure does not corrupt the index
- [ ] Structured logs with per-source metrics

---

### 🔴 PHASE 2 — Read-Only Cloud Tools (2 weeks)

**Objective:** Real cost/inventory data from AWS/Azure/GCP accounts.

#### Tasks

| # | Task | Effort | Cloud |
|---|---|---|---|
| 2.1 | `AWSCostTools.summarize()` → real Cost Explorer (30d) | 6h | AWS |
| 2.2 | AWS Rightsizing Recommendations | 4h | AWS |
| 2.3 | AWS orphaned Volumes/Snapshots | 3h | AWS |
| 2.4 | `AzureAdvisorTools.summarize()` → Advisor (Cost/Security/HA) | 6h | Azure |
| 2.5 | Azure Cost Management API | 4h | Azure |
| 2.6 | `GCPRecommenderTools.summarize()` → Recommender (idle, cost) | 6h | GCP |
| 2.7 | GCP Asset Inventory | 4h | GCP |
| 2.8 | Validated sandbox IAM setup (policies from `iac/`) | 3h | Multi |
| 2.9 | Graceful degradation: no creds → skip, not crash | 3h | Multi |
| 2.10 | Cache + timeout (< 3s per tool) | 3h | Multi |
| 2.11 | Integration tests with sandbox accounts | 8h | Multi |

**Total effort:** ~50h | **Duration:** 2 weeks

#### Acceptance Criteria

- [ ] "Where can I save?" returns **real $** (not inference)
- [ ] Without credentials → pure RAG answer (not 500)
- [ ] Tools run in < 3s (cache when applicable)

---

### 🟡 PHASE 3 — Inspection Engine (2 weeks)

**Objective:** Useful findings from Terraform/K8s files.

#### Terraform/HCL Tasks

| # | Rule | Severity | $ Impact |
|---|---|---|---|
| 3.T1 | Public resources (S3, SG ingress 0.0.0.0/0) | Critical | High (data/RCE) |
| 3.T2 | Missing encryption (EBS, RDS, S3) | High | Medium (compliance) |
| 3.T3 | Missing required tags (env, owner, cost-center) | Medium | Low (governance) |
| 3.T4 | Oversized instances (heuristic by type/usage) | High | $$-$$$ |
| 3.T5 | Missing `lifecycle`/`prevent_destroy` on critical resources | High | Medium (drift) |
| 3.T6 | RDS/Aurora without Multi-AZ in production | Medium | Medium (HA) |
| 3.T7 | NAT Gateway without cost alarms | Medium | $ (egress) |

#### Kubernetes Tasks

| # | Rule | Severity | Impact |
|---|---|---|---|
| 3.K1 | Privileged containers | Critical | Full risk |
| 3.K2 | Missing `resource.limits`/`requests` | High | Stability |
| 3.K3 | `hostNetwork: true` | High | Security |
| 3.K4 | Broad RBAC (`ClusterRoleBinding` with `*`) | Critical | Full risk |
| 3.K5 | Missing `liveness`/`readiness` probes | Medium | Resilience |
| 3.K6 | `:latest` or untagged image | Medium | Reproducibility |
| 3.K7 | Missing `securityContext` (runAsNonRoot) | Medium | Security |

#### Cross-Cutting Tasks

| # | Task | Effort |
|---|---|---|
| 3.8 | Severity + financial impact estimation per rule | 8h |
| 3.9 | `/analyze` with IaC payload → prioritized findings | 6h |
| 3.10 | Test with 10+ real TF and 10+ real K8s scenarios | 8h |

**Total effort:** ~50h | **Duration:** 2 weeks

#### Acceptance Criteria

- [ ] Given `.tf` → findings with severity + $ impact
- [ ] Given K8s manifest → identifies ≥ 5 risk categories
- [ ] Zero false positives on a safe baseline

---

### 🟡 PHASE 4 — Specialists + Advanced Orchestration (2-3 weeks)

**Objective:** Deep multi-domain analysis with intelligent routing.

#### Specialists to implement (prompts already exist in `prompts/specialists.py`)

| Specialist | Domain | Retrieval filter | Priority tools |
|---|---|---|---|
| `aws_specialist` | AWS native | `cloud=aws` | AWS Cost, AWS Inventory |
| `gcp_specialist` | GCP native | `cloud=gcp` | GCP Recommender, Asset |
| `azure_specialist` | Azure native | `cloud=azure` | Azure Advisor, Cost Mgmt |
| `finops_specialist` | Multi-cloud cost | `category=pricing` | Cost tools (all) |
| `security_specialist` | Security | `category=security` | Advisor Security |
| `sre_specialist` | Reliability | `framework=well-architected` | Advisor HA |
| `k8s_specialist` | Kubernetes | category `compute` + service=k8s | Inspection K8s |
| `terraform_specialist` | IaC | category `governance` | Inspection TF |

#### Tasks

| # | Task | Effort |
|---|---|---|
| 4.1 | Intelligent routing (1-3 specialists per query, not all) | 8h |
| 4.2 | Cross-domain findings merge/dedupe | 6h |
| 4.3 | Consolidated prioritization (severity × $ × effort) | 4h |
| 4.4 | ReAct/function-calling mode (LlamaIndex AgentRunner) | 12h |
| 4.5 | Context window management (truncate if budget exceeded) | 4h |
| 4.6 | Multi-specialist integration tests | 8h |

**Total effort:** ~42h | **Duration:** 2-3 weeks

#### Acceptance Criteria

- [ ] Multi-domain query → report with findings from 2+ specialists
- [ ] Standard format maintained (summary → risks → plan → roadmap → refs)
- [ ] Latency p95 < 8s even with 3 specialists triggered

---

### 🔴 PHASE 5 — Quality Gate (2 weeks)

**Objective:** Measurable quality before production.

#### Tasks

| # | Task | Effort |
|---|---|---|
| 5.1 | Expand `eval/test_cases.json` to 60 real scenarios (20/cloud) | 8h |
| 5.2 | Automated eval with rubric: accuracy, grounding, format, citation | 8h |
| 5.3 | Human review: 5 architects × 20 scenarios each | 16h |
| 5.4 | Cost/query metric tracked | 4h |
| 5.5 | Fix regressions found in evaluation | 12h |
| 5.6 | Final report with average score and breakdown | 4h |

**Total effort:** ~52h | **Duration:** 2 weeks

#### Acceptance Criteria (production gate)

- [ ] Average score ≥ 4.0 on **all** criteria
- [ ] Cost per query < $0.05
- [ ] **Zero** inferred price (100% via tool or "not found")
- [ ] No scenario with score < 3.0 on factual correctness

---

### 🔴 PHASE 6 — Production Hardening (2 weeks)

**Objective:** Deployable, observable, secure.

#### Tasks

| # | Task | Effort |
|---|---|---|
| 6.1 | Authentication (API key + OAuth2) | 8h |
| 6.2 | Rate limiting + validated tenant isolation | 6h |
| 6.3 | Langfuse integration (RAG tracing + cost/query) | 8h |
| 6.4 | Structured logs → CloudWatch/Datadog | 4h |
| 6.5 | CI/CD pipeline (build + test + lint + deploy < 5min) | 8h |
| 6.6 | Monthly re-ingestion cron (drift via changelog diff) | 4h |
| 6.7 | Advanced health checks + alerts (P0/P1) | 4h |
| 6.8 | Staging deploy + smoke tests | 4h |
| 6.9 | Production deploy (with flags OFF initially) | 4h |
| 6.10 | Incident runbook | 4h |

**Total effort:** ~52h | **Duration:** 2 weeks

#### Acceptance Criteria

- [ ] Automated deploy in < 5min after merge
- [ ] Dashboard with latency, cost, grounding rate, error rate
- [ ] Tenant A does not see Tenant B data (validated in test)
- [ ] Monthly re-ingestion running without manual intervention

---

### 🟢 PHASE 7 — Persona Fine-tuning (OPTIONAL, 1-2 months)

**⚠️ Only run if RAG validated ≥ 4.0.** Objective: refine format/tone, **NEVER** write facts.

#### Tasks

| # | Task | Effort |
|---|---|---|
| 7.1 | Generate synthetic dataset (5–10k question/reasoning/answer pairs) | 16h |
| 7.2 | Human review of 30% of examples (discard factual hallucinations) | 24h |
| 7.3 | LoRA/QLoRA training setup (PEFT + TRL `SFTTrainer`) | 8h |
| 7.4 | Hyperparameters: `r=64`, `alpha=128`, `dropout=0.05`, lr=2e-4, 3 epochs | 4h |
| 7.5 | Train on Llama 3.3 70B (or 8B for a cheap prototype) | 24h GPU |
| 7.6 | Merge LoRA + deploy (vLLM/TGI or SageMaker/Vertex/Azure ML) | 8h |
| 7.7 | A/B eval (fine-tuned vs base) — only promote if it improves without regressing | 8h |

**Effort:** ~92h + 24h GPU | **Duration:** 1-2 months

#### Acceptance Criteria

- [ ] Measurable improvement in format consistency (style rubric ≥ 4.5)
- [ ] **Zero factual regression** (score ≥ 4.0 maintained)
- [ ] Inference cost < 2× of the base model

---

## 5. ⏱️ Consolidated Schedule

```
Week  1  ▓▓▓▓▓▓▓▓▓▓  Phase 1A (functional MVP) + 1B (ingestion) [parallel]
Week  2  ▓▓▓▓▓▓▓▓▓▓  Phase 1A (conclusion) + 1B (conclusion)
Week  3  ▓▓▓▓▓▓▓▓▓▓  Phase 2 (AWS Tools)
Week  4  ▓▓▓▓▓▓▓▓▓▓  Phase 2 (Azure + GCP Tools + integration)
Week  5  ▓▓▓▓▓▓▓▓▓▓  Phase 3 (Terraform rules)
Week  6  ▓▓▓▓▓▓▓▓▓▓  Phase 3 (Kubernetes rules + integration)
Week  7  ▓▓▓▓▓▓▓▓▓▓  Phase 4 (Specialists)
Week  8  ▓▓▓▓▓▓▓▓▓▓  Phase 4 (ReAct/function-calling)
Week  9  ▓▓▓▓▓▓▓▓▓▓  Phase 5 (Quality gate)
Week 10  ▓▓▓▓▓▓▓▓▓▓  Phase 5 (Architect review)
Week 11  ▓▓▓▓▓▓▓▓▓▓  Phase 6 (Auth + observability)
Week 12  ▓▓▓▓▓▓▓▓▓▓  Phase 6 (CI/CD + production deploy)
Week 13+ ░░░░░░░░░░  Phase 7 (Optional fine-tuning, 4-8 weeks)
```

**Total to production live:** 10-14 weeks (1 full-time senior dev).

---

## 6. 💰 Estimated Costs

| Phase | Monthly infra | Dev hours | Dev cost |
|---|---|---|---|
| 1A + 1B | ~$80 (local RDS pgvector) | 44h | ~$3k |
| 2 | ~$150 (+ sandbox accounts) | 50h | ~$3.5k |
| 3 | ~$80 | 50h | ~$3.5k |
| 4 | ~$500–2000 (Bedrock) | 42h | ~$3k |
| 5 | ~$200 (eval runs) | 52h | ~$3.5k |
| 6 | ~$300 (CI/CD + obs) | 52h | ~$3.5k |
| 7 | ~$2000–5000 (GPU training) | 92h + GPU | ~$8k+ |
| **Production total** | **$1300–2800/month** | **~290h** | **~$20k** |

---

## 7. ⚠️ Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Bedrock unavailable / quota exceeded** | Medium | High | Fallback `LLM_PROVIDER=local` (vLLM/Ollama) already implemented |
| **Ingestion fails due to rate limit** | High | Medium | Exponential retry + header cache + `--dry-run` mode |
| **Price hallucination from tool returning stale cache** | Medium | Critical | Short TTL (1h) + "live data from DD/MM" header |
| **Latency p95 > 5s** | Medium | High | HNSW index + `top_k=8` + tool response cache |
| **Eval score < 4.0** | Medium | Critical | Production gate: blocks release until ≥ 4.0 |
| **Cost/query > $0.05** | Low | Medium | Reduce `max_tokens` (default 2048), `top_k=6`, prompt caching |
| **AWS/Azure/GCP tools without credentials in sandbox** | High | Medium | Graceful degradation → answers via pure RAG (without 500) |
| **Fine-tuning regressing factually** | Medium | Critical | Only promote if A/B eval maintains factual score ≥ 4.0 |

---

## 8. 🎯 Validation Milestones (Gates)

| Milestone | Definition | Blocks production? |
|---|---|---|
| **M1** — MVP answers 20 questions | Phase 1A complete | Yes |
| **M2** — Idempotent re-ingestion | Phase 1B complete | Yes |
| **M3** — Tools return real $ | Phase 2 complete | Yes |
| **M4** — Inspection detects 5+ categories | Phase 3 complete | Yes |
| **M5** — Orchestrated multi-specialist | Phase 4 complete | Yes |
| **M6** — Eval score ≥ 4.0 | Phase 5 complete | **CRITICAL BLOCK** |
| **M7** — Observable production deploy | Phase 6 complete | Go-live |

---

## 9. 📌 Immediate Next Actions (This Week)

### 🟢 Action 1 — Populate `sources.yaml` (CRITICAL, 4h)

Add prioritized official URLs to `ingestion/sources.yaml`:

**AWS (Well-Architected Framework):**
- https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/sustainability-pillar/welcome.html

**GCP (Architecture Framework):**
- https://cloud.google.com/architecture/framework
- https://cloud.google.com/architecture/framework/system-design
- https://cloud.google.com/architecture/framework/security
- https://cloud.google.com/architecture/framework/reliability
- https://cloud.google.com/architecture/framework/cost-optimization
- https://cloud.google.com/architecture/framework/operational-excellence
- https://cloud.google.com/architecture/framework/performance-optimization

**Azure (Well-Architected Framework):**
- https://learn.microsoft.com/en-us/azure/well-architected/
- https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization
- https://learn.microsoft.com/en-us/azure/well-architected/security
- https://learn.microsoft.com/en-us/azure/well-architected/reliability
- https://learn.microsoft.com/en-us/azure/well-architected/operational-excellence
- https://learn.microsoft.com/en-us/azure/well-architected/performance-efficiency

### 🟢 Action 2 — Bring up Postgres+pgvector (2h)

```bash
cd C:\Projetos\cip
docker compose up -d postgres
docker exec -it cip-postgres psql -U cip -d cip -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker exec -i cip-postgres psql -U cip -d cip < db/schema.sql
```

### 🟢 Action 3 — Configure Bedrock (2h)

Create `.env`:
```env
CIP_ENV=dev
CIP_READONLY=true
LLM_PROVIDER=bedrock
LLM_MODEL=anthropic.claude-sonnet-4-5-20250929-v1:0
EMBED_PROVIDER=local
EMBED_MODEL=intfloat/multilingual-e5-small
EMBED_DIM=384
DATABASE_URL=postgresql://cip:cip@localhost:5432/cip
```

### 🟢 Action 4 — Run first ingestion (4h)

```bash
python -m cip.ingestion.ingest --catalog mvp
```

### 🟢 Action 5 — Smoke test 20 questions (4h)

```bash
pytest tests/test_router.py -v
# Add tests/test_smoke_ask.py with 20 cases
```

---

## 10. 📚 Reference Documents

| Doc | Purpose |
|---|---|
| `docs/01-analise-recomendacoes.md` | Architectural justification |
| `docs/02-arquitetura.md` | Diagram + components |
| `docs/03-roadmap.md` | Original roadmap (high level) |
| `docs/04-modelo-de-dados.md` | SQL schema + tables |
| `docs/05-fine-tuning.md` | Phase 7 in detail |
| `docs/06-planejamento-proximas-fases.md` | Assessment + critical path |
| `docs/adr/0001-rag-first-em-vez-de-fine-tuning.md` | ADR-0001 |
| `docs/adr/0002-pgvector-como-vector-db.md` | ADR-0002 |
| `docs/adr/0003-tools-read-only-para-dados-ao-vivo.md` | ADR-0003 |
| `docs/adr/0004-llm-base-e-embeddings.md` | ADR-0004 |

---

## 11. ✅ Executive Summary

| Question | Answer |
|---|---|
| What needs to be done? | **Execute the 6 mandatory phases (10–14 weeks).** |
| How much does it cost? | **~$20k dev + $1.3k–2.8k/month infra.** |
| When does it go to production? | **Week 12** (without Phase 7). |
| Main risk? | **Eval score < 4.0** — blocks go-live. |
| Immediate next action? | **Populate `sources.yaml` with 50+ real URLs (4h).** |
| Is fine-tuning worth it? | **Only after RAG ≥ 4.0.** It is optional, not mandatory. |

**The plan is approved for execution. Start with Phase 1A.**
