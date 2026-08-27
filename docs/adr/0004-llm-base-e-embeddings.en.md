# ADR 0004 — Base LLM and embeddings choice

- **Status:** Accepted (revised 2026-07-23)
- **Date:** 2026-07-23

## Context
We need an LLM with good technical reasoning and an embeddings model
suited to technical documentation — **but the system is focused (not generic) and must
run on a cheap server, with low ingestion and low read volume**. Therefore the
infrastructure cost needs to be minimal.

## Decision

### Base LLM (managed, no local infra)
- **Default:** Claude via **AWS Bedrock** (managed API). The application server
  **does not host an LLM** — it only makes API calls. Abstracted by `LLM_PROVIDER`
  (`bedrock | openai | local | stub`) so it can be swapped without rewriting.
- `local` (vLLM/Ollama) remains an option for those who want self-hosting — it is **not** the
  default, precisely to avoid requiring a GPU/large infra.

### Embeddings (minimalist profile)
- **Default:** `intfloat/multilingual-e5-small` (**384d**), local on CPU.
  - Small (~0.5 GB RAM) → fits in a cheap server.
  - **Multilingual**: handles PT questions about EN documentation well
    (validated: PT→EN similarity relevant 0.85 vs irrelevant 0.77).
- Abstracted by `EMBED_PROVIDER` (`local | bedrock | openai`): you can **remove
  all local ML** using Titan (Bedrock) or `text-embedding-3-small` (OpenAI) —
  the server then only calls APIs.
- `EMBED_DIM` must match the model (e5-small=384, Titan=1024, OpenAI 3-small=1536).

### Corpus
- **Production = curated catalog** (`sources.yaml`, ~245 verified pages).
  Small, focused, cheap to embed and serve.
- The **exhaustive ingestion** (`--expand`, ~51k pages after noise filtering) is
  **optional**, for those who need depth — it is not the default.

## Consequences
- (+) Cheap production server: no GPU, no local LLM, small embeddings.
- (+) Total provider flexibility (LLM and embeddings) via config.
- (+) Multilingual by default (PT↔EN) at no variable cost.
- (−) `RETRIEVAL_MIN_SCORE` depends on the embeddings model (e5 ~0.80, bge ~0.35)
  → revalidate with `eval/run_eval.py` when switching the model.
- (−) Switching the embeddings model/dimension requires **re-ingestion** and adjusting
  `EMBED_DIM` + `db/schema.sql` (`vector(N)`).
- (−) e5 recommends `query:`/`passage:` prefixes (already configured).

## Quick embeddings comparison

| Model | Dim | Local RAM | PT↔EN | Cost |
|--------|-----|-----------|-------|-------|
| multilingual-e5-small (default) | 384 | ~0.5 GB | yes | zero |
| bge-large-en-v1.5 (previous) | 1024 | ~2 GB | no (EN) | zero |
| Titan Embeddings (Bedrock) | 1024 | 0 (API) | yes | ~US$0.02/1M tok |
| OpenAI text-embedding-3-small | 1536 | 0 (API) | yes | ~US$0.02/1M tok |
