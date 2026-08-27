# ADR 0001 — RAG-first instead of fine-tuning for knowledge

- **Status:** Accepted
- **Date:** 2026-07-23

## Context
The product requires a non-generic LLM that "fully understands" AWS, GCP and Azure. This
knowledge is factual and volatile (prices, quotas, new services change almost every week).

## Decision
Use **RAG** as the primary source of knowledge. Fine-tuning is reserved for
persona/format (phase 6, optional), never for volatile facts.

## Consequences
- (+) Updating via monthly re-ingestion (cheap) instead of retraining.
- (+) Lower risk of factual hallucination; auditable citations.
- (+) Useful result within weeks.
- (−) Dependency on ingestion and retriever quality.
- (−) Additional retrieval latency (mitigated with HNSW + moderate top_k).
