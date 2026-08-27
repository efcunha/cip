# Planning for the Next Phases — Cloud Intelligence Platform

> Based on the analysis of the current state of the code and on the original roadmap (`03-roadmap.md`).
> Last updated: July 2026.

---

## Current State (Assessment)

| Component | Status |
|---|---|
| Config + Settings (pydantic-settings) | Implemented |
| FastAPI API (`/ask`, `/analyze`, `/health`) | Implemented |
| RAG Engine (retriever + filters + anti-hallucination) | Implemented |
| Ingestion pipeline (ingest.py, chunking, sources.yaml) | Structure ready, sources to populate |
| Router/Classifier (heuristic by keywords) | Implemented |
| Orchestrator (RAG + tools + inspection) | Implemented |
| Cloud Tools (registry + AWS/Azure/GCP wrappers) | Structure ready, real calls pending |
| Inspection Engine (TF + K8s dispatch) | Structure ready, rules pending |
| Domain models (Finding, Plan, Result) | Implemented |
| SQL schema (pgvector + HNSW) | Implemented |
| IAC (read-only policies) | Implemented |
| Tests | 2 files, basic coverage |
| Eval suite | Structure ready (60 placeholder scenarios) |

**Summary:** the architecture is assembled end-to-end. The next step is to make each
component functional with real data and integrations.

---

## Critical Path

```
1A (functional MVP) ──► 2 (live Tools) ──► 3 (Inspection Rules) ──► 4 (Specialists) ──► 5 (Eval) ──► 6 (Production)
       │
       └── 1B (Ingestion hardening, in parallel)
```

**Estimated total timeline:** 10-14 weeks to production-ready (excluding Phase 7).

---

## Phase 1A — Functional MVP (end-to-end running)

**Timeline:** 1-2 weeks  
**Goal:** `/ask` returns grounded answers for the 3 clouds.

### Tasks

1. Populate `sources.yaml` with real URLs (Well-Architected AWS, Architecture Framework GCP, Well-Architected Azure).
2. Run ingestion against real docs — validate chunking + embeddings.
3. Validate pgvector + HNSW index with ~5k chunks.
4. End-to-end test: question → retrieval → LLM → answer with citation.
5. Verified Bedrock integration (or OpenAI fallback).
6. `docker compose up` → complete local demo working.

### Acceptance Criteria

- 20 questions answered with cited source.
- p95 latency < 5s.
- Zero answers without grounding (returns "not found" when there is no context).

---

## Phase 1B — Ingestion Pipeline Hardening

**Timeline:** 1 week (in parallel with 1A)  
**Goal:** Reliable and repeatable ingestion.

### Tasks

1. Implement dedupe by `content_hash` in the upsert.
2. Markdown-aware chunking (headers as boundaries, not arbitrary split).
3. Progress tracking + resume on failure.
4. Test with real crawling (handle rate limits, broken links).
5. Add a `--dry-run` mode for validation before persisting.

### Acceptance Criteria

- Idempotent re-ingestion (no duplicates).
- Partial failure does not corrupt the existing index.
- Structured logs with chunk counts per source.

---

## Phase 2 — Read-Only Cloud Tools (live data)

**Timeline:** 2 weeks  
**Goal:** Real cost/inventory data from AWS/Azure/GCP accounts.

### Tasks

1. `AWSCostTools.summarize()` → real call to Cost Explorer (last 30 days, top services).
2. `AzureAdvisorTools.summarize()` → real Advisor recommendations.
3. `GCPRecommenderTools.summarize()` → real Recommender API.
4. Validated IAM sandbox setup (use the policies from `iac/`).
5. Graceful degradation: missing credentials → skip, not crash.
6. Integration test with a real account (sandbox).

### Acceptance Criteria

- The question "where can I save?" returns real numbers in $.
- No credentials → pure RAG response (no 500 error).
- Tools run in < 3s (timeout + cache if needed).

---

## Phase 3 — Inspection Engine Rules

**Timeline:** 2 weeks  
**Goal:** Useful findings from Terraform/K8s files.

### Tasks

1. **Terraform rules:**
   - Public resources (S3, SG ingress 0.0.0.0/0)
   - No encryption (EBS, RDS, S3)
   - No required tags
   - Oversized instances (heuristic by type)
   - No lifecycle/prevent_destroy on critical resources
2. **Kubernetes rules:**
   - Privileged containers
   - No resource limits/requests
   - hostNetwork enabled
   - Broad RBAC (ClusterRoleBinding with `*`)
   - No liveness/readiness probes
3. Severity + financial impact estimation per rule.
4. `/analyze` with IaC payload → prioritized findings.
5. Test with real manifests (10+ TF scenarios, 10+ K8s).

### Acceptance Criteria

- Given a `.tf`, returns findings with severity + $ impact.
- Given a K8s manifest, identifies at least 5 risk categories.
- Zero false positives in secure baseline scenarios.

---

## Phase 4 — Specialists + Advanced Orchestration

**Timeline:** 2-3 weeks  
**Goal:** Deep per-domain analysis with multiple specialists.

### Tasks

1. Specialist prompts: `finops`, `security`, `sre`, `kubernetes`, `terraform`.
2. Each specialist = focused system prompt + retrieval filter + optional tools.
3. Orchestrator routes to 1-3 specialists per query (not all).
4. Consolidation logic: merge findings, dedupe, cross-domain prioritization.
5. ReAct/function-calling agent mode (LlamaIndex AgentRunner) for complex queries.
6. Context window management (truncate if it exceeds the LLM budget).

### Acceptance Criteria

- Multi-domain query produces a structured report with findings from 2+ specialists.
- Standard format maintained (executive summary → risks → plan → roadmap → references).
- p95 latency < 8s even with 3 specialists triggered.

---

## Phase 5 — Quality Gate + Validation

**Timeline:** 2 weeks  
**Goal:** Measurable quality before production.

### Tasks

1. Expand `eval/test_cases.json` to 60 scenarios (20 per cloud).
2. Automated eval: `run_eval.py` with scores for accuracy, grounding, format, citation.
3. 1-5 rubric: factual correctness, actionability, citation quality, format.
4. Human review: 5 architects evaluate 20 scenarios each.
5. Cost/query metric tracked.
6. Fix regressions found in evaluation.

### Acceptance Criteria

- Average score ≥ 4.0 across all criteria.
- Cost per query < $0.05.
- Zero inferred pricing (100% via tool or "not found" response).
- No scenario scoring < 3.0 in factual correctness.

---

## Phase 6 — Production Hardening

**Timeline:** 2 weeks  
**Goal:** Deployable, observable, secure.

### Tasks

1. Authentication on the endpoints (API key or OAuth2).
2. Rate limiting + per-tenant isolation.
3. Langfuse integration for tracing (cost per query, latency breakdown).
4. Structured logging → export to CloudWatch/Datadog.
5. CI/CD pipeline (build, test, lint, deploy).
6. Monthly re-ingestion cron (drift detection via changelog diff).
7. Advanced health checks + alerts (retrieval degradation, LLM timeout, tool failure rate).

### Acceptance Criteria

- Automated deploy in < 5min after merge.
- Observability: dashboard with latency, cost, grounding rate, error rate.
- Tenant isolation validated (tenant A does not see tenant B's data).
- Monthly re-ingestion running without manual intervention.

---

## Phase 7 (Optional) — Persona Fine-tuning

**Timeline:** 1-2 months  
**Goal:** Format/tone consistency without changing the factual layer.

### Tasks

1. Generate synthetic dataset (5-10k examples of real queries + ideal answers).
2. Human review of 30% of the examples.
3. LoRA/QLoRA over Llama 3.3 70B (or an equivalent of the time).
4. A/B eval: fine-tuned vs base → improvement in format/consistency without factual regression.
5. Deploy as an alternative model option.

### Acceptance Criteria

- Measurable improvement in format consistency (style rubric ≥ 4.5).
- Zero regression in factual correctness (factual score ≥ 4.0 maintained).
- Inference cost < 2x the base model.

---

## Cost Estimate per Phase

| Phase | Monthly infra (estimated) | Dev hours |
|---|---|---|
| 1A + 1B | ~$80 (RDS pgvector + local dev) | 40-60h |
| 2 | ~$150 (+ sandbox accounts) | 30-40h |
| 3 | ~$80 (no extra infra) | 30-40h |
| 4 | ~$500-2000 (LLM inference Bedrock) | 40-60h |
| 5 | ~$200 (eval runs + LLM) | 20-30h |
| 6 | ~$300 (CI/CD + observability) | 30-40h |
| 7 | ~$2000-5000 (GPU for training) | 60-80h |

---

## Next Immediate Action

**Phase 1A, Task 1:** Populate `ingestion/sources.yaml` with real URLs from the
Well-Architected documentation of the 3 clouds and run the first test ingestion.
