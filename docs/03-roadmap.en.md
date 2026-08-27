# Implementation roadmap

Based on the RAG-first backbone (MiniMax) with a structure of specialists (CIP) and
persona fine-tuning (Deep) as the final optional phase.

## Phase 1 — RAG MVP (2-3 weeks)
**Goal:** an assistant that answers questions about the 3 clouds with source citation.
- Provision Postgres+pgvector, create the schema.
- Ingest Well-Architected (AWS), Architecture Framework (GCP), Well-Architected (Azure).
- Stand up the `/ask` API with cloud/service filtering.
- **Acceptance:** answers 20 knowledge questions with cited source; p95 latency < 5s.

## Phase 2 — Complete ingestion pipeline (1-2 weeks, in parallel)
**Goal:** coverage of the top 50 services per cloud.
- `sources.yaml` with prioritized sources; markdown-aware + semantic chunking.
- Scheduled monthly re-ingestion + drift detection (changelog diff).
- **Acceptance:** ~30k pages indexed; dedupe by `content_hash` working.

## Phase 3 — Read-only cloud tools (1-2 weeks)
**Goal:** live cost/inventory data.
- AWS/Azure/GCP wrappers (Cost Explorer, Advisor, Recommender).
- Read-only IAM applied in a sandbox (see `iac/`).
- **Acceptance:** the question "where can I save?" returns real cost numbers, not inference.

## Phase 4 — Specialists + Inspection Engine (2-3 weeks)
**Goal:** deep analysis by domain and of IaC/K8s files.
- Orchestrator + routing; FinOps, Security, K8s, Terraform specialists.
- Inspection Engine: Terraform/HCL and Kubernetes rules.
- **Acceptance:** given a `.tf`, returns prioritized findings with severity + $ impact.

## Phase 5 — Validation with architects (2 weeks)
**Goal:** ensure quality before production.
- Suite of 60 scenarios; 1-5 rubric; 5 architects review.
- **Acceptance:** average score ≥ 4.0 across all criteria; cost/query < $0.05.

## Phase 6 — Persona fine-tuning (1-2 months, OPTIONAL)
**Goal:** refine format/persona (NOT knowledge).
- Curated synthetic dataset (5-10k examples, 30% human review).
- LoRA/QLoRA over Llama 3.3 70B or an equivalent model.
- **Acceptance:** measurable improvement in format/consistency without factual regression.

## Global "production-ready" criteria
- Rubric score ≥ 4.0 (all criteria).
- p95 latency < 5s.
- Cost per query < $0.05.
- Zero inferred pricing (100% via live tool, verified in audit).
- Active monthly re-ingestion coverage.

## Timeline and cost (reference)

| Component | MVP (managed) | Production (self-hosted 70B) |
|---|---|---|
| Vector DB (RDS pgvector) | ~$80/mo | ~$400/mo |
| Embeddings (CPU/GPU) | ~$50/mo | ~$200/mo |
| LLM inference | ~$500-2000/mo (Bedrock) | ~$1500-3000/mo (2×A100) |
| Storage + observability + tools | ~$80/mo | ~$250/mo |
| **Approx. total** | **$700-2200/mo** | **$2300-3800/mo** |

> Start managed (Bedrock + RDS); migrate to self-hosted when volume justifies it.
