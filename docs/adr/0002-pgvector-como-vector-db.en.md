# ADR 0002 — pgvector as the vector database

- **Status:** Accepted
- **Date:** 2026-07-23

## Context
We need vector storage for the RAG. Options evaluated: Pinecone, Qdrant,
Weaviate, Milvus, pgvector.

## Decision
Use **pgvector** on PostgreSQL 16.

## Justification
- A single database for vector **and** relational data (`environments`, `analyses`, `findings`).
- Cheap and simple to operate; available as a managed service on the 3 clouds (RDS/Cloud SQL/Azure DB).
- The HNSW index meets MVP and initial production latency.

## Consequences
- (+) Fewer moving pieces; JOIN between docs and operational history.
- (−) At very high scale (>50M vectors) it may require migrating to Qdrant/Milvus.
  Reassess when the volume justifies it (trigger: search p95 > 300ms).
