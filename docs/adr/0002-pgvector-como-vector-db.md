# ADR 0002 — pgvector como banco vetorial

- **Status:** Aceito
- **Data:** 2026-07-23

## Contexto
Precisamos de armazenamento vetorial para o RAG. Opções avaliadas: Pinecone, Qdrant,
Weaviate, Milvus, pgvector.

## Decisão
Usar **pgvector** sobre PostgreSQL 16.

## Justificativa
- Um único banco para dados vetoriais **e** relacionais (`environments`, `analyses`, `findings`).
- Barato e simples de operar; disponível como serviço gerenciado nas 3 clouds (RDS/Cloud SQL/Azure DB).
- Índice HNSW atende latência do MVP e de produção inicial.

## Consequências
- (+) Menos peças móveis; JOIN entre docs e histórico operacional.
- (−) Em escala muito alta (>50M vetores) pode exigir migração para Qdrant/Milvus.
  Reavaliar quando o volume justificar (gatilho: p95 de busca > 300ms).
