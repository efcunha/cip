# Ollama local LLM for the CIP RAG chat

> Scope: answers generated **only** from retrieved RAG context by a small CPU model served by
> Ollama (`LLM_PROVIDER=local`). Not deployed by this change; see `ops/ollama/README.md`.

## Flow (`LLM_PROVIDER=local`)

1. Retrieval (`retrieval_top_k=8`) and the `retrieval_min_score` gate **before** the LLM. Nothing
   above the score => refusal, the LLM is never called.
2. The best `LLM_CONTEXT_TOP_K` (4) chunks, each trimmed to `LLM_CONTEXT_CHUNK_CHARS` (1200), are
   sent numbered `[1]..[k]` with a strict prompt (`rag/grounded.py`): answer only from the
   context, cite `[n]`, no URLs, reply `NAO_ENCONTRADO` when the context does not answer.
3. Tokens stream to SSE `chunk` events as produced. After generation: citations must be in
   `1..k` and every URL must be among the retrieved chunks. A deterministic "Fontes:" list is
   appended.
4. One generation per question: specialists use extractive synthesis; only the base answer calls
   the LLM (Ollama is serialized, `OLLAMA_NUM_PARALLEL=1`).

## Fallback to extractive (default on any Ollama failure)

| Trigger | `done.fallback` |
|---|---|
| connection/HTTP error | `llm_error:<Type>` |
| no first token within `LLM_FIRST_TOKEN_TIMEOUT_S` | `timeout_first_token` |
| total time over `LLM_TIMEOUT_S` | `timeout_total` |
| empty output | `empty_output` |
| missing/out-of-range citation, foreign URL | `validation:<reason>` |

Each fallback logs `llm_fallback_extractive` (reason, model, elapsed_ms). Fallback results are
not cached. If the model replies `NAO_ENCONTRADO` the result is a refusal
(`refusal_reason=model_declined`). Streamed text cannot be retracted: when generation fails
mid-stream a notice plus the extractive text is appended and `done.answer` holds the extractive
text.

## SSE contract

Events stay `chunk` / `done` / `error`. Additive `done` fields: `fallback` (string or null) and
`ttft_ms`. Other providers keep the 50-char simulated chunking.

## Environment

| Variable | Default | Note |
|---|---|---|
| `LLM_PROVIDER` | `bedrock` | `local` enables this path |
| `LLM_BASE_URL` | empty | `http://ollama:11434/v1`; empty keeps `http://localhost:8001/v1` |
| `LLM_API_KEY` | empty | optional; `not-needed` is sent when empty |
| `LLM_FIRST_TOKEN_TIMEOUT_S` | 30 | |
| `LLM_CONTEXT_TOP_K` | 4 | chunks sent to the model |
| `LLM_CONTEXT_CHUNK_CHARS` | 1200 | |
| `QUERY_TRANSLATION_ENABLED` | true | translates PT-BR -> EN before retrieval; real LLM only |
| `QUERY_TRANSLATION_TIMEOUT_S` | 5 | on timeout/failure the original question is used |
| `QUERY_TRANSLATION_CACHE_TTL_S` | 86400 | translation cache TTL |

`num_ctx`, `num_thread`, `keep_alive` cannot be set per request through `/v1`; they live in
Ollama server env and the derived Modelfile (`ops/ollama/`).

## Known findings

- **Embedding mismatch**: live data is `data_cloud_docs`, 1024 dims (`bge-large-en-v1.5`).
  `docker-compose.prod.yml` and `.env.prod.example` default to `multilingual-e5-small` / 384 and
  do not match. Not changed (would break existing compose installs); the VPS uses Quadlet +
  `cip.env`. No re-ingest.
- `EMBED_QUERY_INSTRUCTION="query: "` is an E5 convention applied to a BGE model. Not changed;
  measured in the eval step.

## Open points

CPU/memory limits and threads for the Ollama unit, and the base model (eval step).

## Roll back

`LLM_PROVIDER=extractive` in `cip.env`, restart `cip-api`, stop `ollama`.
