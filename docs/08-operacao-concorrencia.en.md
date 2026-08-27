# Operation: robustness, concurrency and non-hallucination

How to operate the platform stably under load (e.g.: ~100 simultaneous
users), keeping responses anchored (without hallucinating) and without hanging/looping.

## No-loop (by design)

The pipeline **is not a looping ReAct agent**: `heuristic router → tools
(best-effort, with try/except) → single-shot RAG → consolidation`. There is no
re-planning nor recursive tool-calling, so there is no risk of an infinite loop.
Calls to the provider have a **timeout** and a **low `max_retries`** (avoids retry
storms). If agentic tool-calling is ever introduced, add an iteration cap.

## Non-hallucination

- RAG with cutoff by `RETRIEVAL_MIN_SCORE` (nodes below the score are discarded).
- **Explicit refusal** when there is no context above the score (`has_grounding=False`).
- System prompt: answer **only** based on the context, cite sources, do not
  invent prices/limits.
- `LLM_TEMPERATURE=0.1`.
- Reminder: `RETRIEVAL_MIN_SCORE` depends on the embeddings model
  (e5-small ≈ 0.80; bge-large ≈ 0.35). Revalidate with `eval/run_eval.py`.

## Robustness under load (block 1 — implemented)

Controls added to avoid "melting" on spikes:

| Config | Default | Effect |
|--------|--------|--------|
| `MAX_CONCURRENT_REQUESTS` | 200 | Above this the API returns **429** (backpressure) instead of piling up |
| `REQUEST_TIMEOUT_S` | 90 | Request that exceeds the time → **504** (frees resources) |
| `LLM_TIMEOUT_S` | 60 | LLM call timeout |
| `LLM_MAX_RETRIES` | 2 | Avoids retry storms |
| `LLM_MAX_TOKENS` | 2048 | Output cap (SDK default is 512 = truncates) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 20 / 20 | pgvector connection pool sized for concurrency |

`/health` does not go through the control (liveness always responds).

## Reference configuration for ~100 simultaneous users

The bottleneck is the **LLM** (managed API), not the app server. Since the LLM is
managed, the application tier remains **small and cheap**; it scales out
horizontally.

- **LLM (Bedrock)**: route by complexity — `/ask` → Claude Haiku (cheap,
  fast); `/analyze` → Claude Sonnet. Ensure **quota** for ~100-150
  concurrent requests (RPM/TPM) or use Provisioned Throughput / cross-region
  inference. Prefer **streaming** to reduce perceived latency.
- **Embeddings**: for high concurrency, `EMBED_PROVIDER=bedrock` (Titan) takes the
  CPU off the critical path. Alternative: `local` (e5-small) with 3-4 replicas
  (the model is GIL-bound; the query embed is 1 short vector, ~10-30ms).
- **App**: stateless → `gunicorn` + uvicorn workers (2-4 replicas × 2-4 workers)
  behind a load balancer. Each replica ~2 vCPU / 2-4 GB.
- **pgvector** (managed): 2-4 vCPU; pool 20-40; `hnsw_ef_search` 40-64
  (recall × latency).
- **Redis** (block 2): semantic response cache (avoids calling the LLM on
  repeated questions), multi-turn chat state and per-user rate limiting.
- **Observability**: Langfuse + queue/latency/error metrics and of the 429/504.

## Roadmap of the next blocks

- **Block 2 — Redis**: semantic cache + multi-turn chat memory + rate limit.
- **Block 3 — LLM**: Haiku/Sonnet routing by complexity + streaming endpoint.
- **Block 4 — Managed embeddings**: high-concurrency profile (config only).
