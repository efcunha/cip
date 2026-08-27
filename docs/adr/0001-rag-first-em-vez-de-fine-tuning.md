# ADR 0001 — RAG-first em vez de fine-tuning para conhecimento

- **Status:** Aceito
- **Data:** 2026-07-23

## Contexto
O produto exige uma LLM não-genérica que "entenda totalmente" AWS, GCP e Azure. Esse
conhecimento é factual e volátil (preços, quotas, novos serviços mudam quase toda semana).

## Decisão
Usar **RAG** como fonte primária de conhecimento. Fine-tuning fica reservado para
persona/formato (fase 6, opcional), nunca para fatos voláteis.

## Consequências
- (+) Atualização por re-ingestão mensal (barata) em vez de retreino.
- (+) Menor risco de alucinação factual; citações auditáveis.
- (+) Resultado útil em semanas.
- (−) Dependência de qualidade da ingestão e do retriever.
- (−) Latência adicional de retrieval (mitigada com HNSW + top_k moderado).
