# ADR 0004 — Escolha de LLM base e embeddings

- **Status:** Aceito (revisado 2026-07-23)
- **Data:** 2026-07-23

## Contexto
Precisamos de um LLM com bom raciocínio técnico e de um modelo de embeddings
adequado a documentação técnica — **mas o sistema é focal (não genérico) e deve
rodar em servidor barato, com pouca ingestão e pouca leitura**. Logo, o custo de
infraestrutura precisa ser mínimo.

## Decisão

### LLM base (gerenciado, sem infra local)
- **Padrão:** Claude via **AWS Bedrock** (API gerenciada). O servidor da aplicação
  **não hospeda LLM** — apenas faz chamadas de API. Abstraído por `LLM_PROVIDER`
  (`bedrock | openai | local | stub`) para trocar sem reescrever.
- `local` (vLLM/Ollama) fica como opção para quem quiser self-host — **não** é o
  padrão, justamente para não exigir GPU/infra grande.

### Embeddings (perfil minimalista)
- **Padrão:** `intfloat/multilingual-e5-small` (**384d**), local em CPU.
  - Pequeno (~0.5 GB RAM) → cabe em servidor barato.
  - **Multilíngue**: lida bem com perguntas em PT sobre documentação em EN
    (validado: similaridade PT→EN relevante 0.85 vs irrelevante 0.77).
- Abstraído por `EMBED_PROVIDER` (`local | bedrock | openai`): dá para **remover
  todo ML local** usando Titan (Bedrock) ou `text-embedding-3-small` (OpenAI) —
  o servidor passa a só chamar API.
- `EMBED_DIM` deve casar com o modelo (e5-small=384, Titan=1024, OpenAI 3-small=1536).

### Corpus
- **Produção = catálogo curado** (`sources.yaml`, ~245 páginas verificadas).
  Pequeno, focal, barato de embedar e servir.
- A **ingestão exaustiva** (`--expand`, ~51k páginas após filtro de ruído) é
  **opcional**, para quem precisar de profundidade — não é o default.

## Consequências
- (+) Servidor de produção barato: sem GPU, sem LLM local, embeddings pequenos.
- (+) Flexibilidade total de provider (LLM e embeddings) via config.
- (+) Multilíngue por padrão (PT↔EN) sem custo variável.
- (−) `RETRIEVAL_MIN_SCORE` depende do modelo de embeddings (e5 ~0.80, bge ~0.35)
  → revalidar com `eval/run_eval.py` ao trocar o modelo.
- (−) Trocar o modelo/dimensão de embeddings exige **re-ingestão** e ajustar
  `EMBED_DIM` + `db/schema.sql` (`vector(N)`).
- (−) e5 recomenda prefixos `query:`/`passage:` (já configurados).

## Comparativo rápido de embeddings

| Modelo | Dim | RAM local | PT↔EN | Custo |
|--------|-----|-----------|-------|-------|
| multilingual-e5-small (padrão) | 384 | ~0.5 GB | sim | zero |
| bge-large-en-v1.5 (anterior) | 1024 | ~2 GB | não (EN) | zero |
| Titan Embeddings (Bedrock) | 1024 | 0 (API) | sim | ~US$0,02/1M tok |
| OpenAI text-embedding-3-small | 1536 | 0 (API) | sim | ~US$0,02/1M tok |
