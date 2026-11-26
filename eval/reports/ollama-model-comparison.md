# Ollama model comparison for the CIP grounded chat path

Run on 2026-11-26 with `eval/ollama_compare.py` and `eval/ollama_questions.json` (36 PT-BR questions: 16 in-RAG, 12 out-of-RAG, 8 ambiguous). Raw data: `ollama-retrieval-raw.json`, `ollama-generation-raw.json` (full set), `ollama-generation-cpu-raw.json` (CPU-only subset).

## 1. Recommendation and summary

**Recommended model: `gemma3:4b`.**

- It is the only candidate with a usable balance: it answers 65% of in-RAG runs with valid `[n]` citations and real content (7b: 56%, 3b: 0%), refuses 100% of out-of-RAG questions, gives acceptable answers on 100% of ambiguous ones, and leaks no off-topic terms.
- `qwen2.5:7b-instruct` has the best content scores (100% citation validity, 100% `must_mention`) but refuses 44% of in-RAG runs. In 29 of 108 runs it replies `NAO_ENCONTRADO [1]` (sentinel plus markers). The engine's exact-match `is_decline` would not catch that, so the raw text would reach the user. It is also about 1.5x slower per answer (median total 12.7 s vs 8.5 s, 6.8 vs 12.3 tok/s).
- `qwen2.5:3b-instruct` is the fastest (41 tok/s) but unusable with the current prompt: in 29 of its 30 non-refusal in-RAG runs it emitted only the citation marker (e.g. `[2]`) and no text. Valid-with-content answers: 0.
- Out-of-RAG refusal is 100% for all three, but this comes from the model alone. The `min_score=0.50` gate never fires: 100% of out-of-RAG and ambiguous questions have a top-1 score >= 0.50 (PT, `query: ` prefix). Refusal correctness therefore depends entirely on the model following `NAO_ENCONTRADO`.
- Caveats for gemma3:4b: 10% of in-RAG runs fall back to extractive (multi-citation `[1, 2, 3]` is not matched by `validate_answer`, which only accepts `[n]`), and `must_mention` median is 50% on the full set. Both are prompt/validator tuning items, not reasons to change the model.

Latency caveat: these numbers come from a laptop (Intel Core Ultra 7 155H, 16 cores, 63 GB RAM, RTX 500 Ada 4 GB, Ollama 0.40.18), not from the VPS. They rank the models but are not VPS absolutes. The CPU-only table is closer to the VPS situation (no GPU) but this CPU is much faster than a typical Contabo vCPU.
TTFT in runs 2 and 3 is optimistic because Ollama reuses the cached prompt prefix; the "cold, run 1" column is the realistic first-token figure.

### Findings beyond the model choice

1. **PT-BR retrieval is weaker than EN with the English-only embedding model.** With the production prefix (`query: `), expected-service recall@1 is 81% for PT vs 100% for EN, and recall@8 is 94% vs 100%. PT top-1 score median is 0.72 vs 0.79 (PT min 0.61 vs EN 0.70). Misses: in-01 (S3 versioning) returned `s3-postmortem`, in-04 (IAM policies) returned `case-studies` (0.607), in-14 (Azure Policy) returned `arm-templates`. The embedding model was not changed and nothing was re-ingested.
2. **The `query: ` prefix (an E5 convention) does not help BGE.** PT recall@1 is 81% with no prefix, 81% with `query: `, and 88% with the official BGE instruction (16 questions, so one question is 6 points; treat as a hint, not proof).
3. **The `min_score=0.50` gate does not separate in-corpus from out-of-corpus questions.** Out-of-RAG top-1 >= 0.50: 100% (PT, `query: `), 92% (EN). Every in-RAG question is also above 0.50. A threshold near 0.75-0.80 would be needed to separate, and that must be validated on a larger set before use.
4. **Prompt weakness.** The user message ends with "Responda só com o contexto, citando [n]". Both Qwen models read this as "reply only with the markers" in many runs (3b: 29 marker-only runs, 7b: 29 sentinel-plus-marker runs). Reword so the answer text is required and the marker is an inline suffix.
5. **Corpus coverage.** The remote `data_cloud_docs` (2,928 chunks) contains only one GCP service entry (`architecture-framework`); GKE, BigQuery and most of the `know-*` GCP cases in `eval/test_cases.json` have no matching documents.
6. **`eval/run_eval.py`.** `--offline` runs only the Inspection Engine without an LLM, so it does not discriminate models (3/106 pass, gate FAIL: accuracy 3.30, format 1.00). The API mode needs a `cip-api` running the new local path; that is not deployed (no VPS change was allowed), so the per-model API run is pending. It was not committed.

### Method

- Retrieval: same chunks for all models. Queries embedded locally with `BAAI/bge-large-en-v1.5` and run read-only against the remote pgvector table (`ssh cloudpilot` + `psql`, `default_transaction_read_only=on`, no write, no re-ingest). Top-k 8, `min_score` 0.50 gate, top 4 chunks of 1200 chars to the LLM (same as `src/cip/config.py`). Production prefix `query: `.
- Generation: `build_grounded_messages` and `validate_answer` from `src/cip/rag/grounded.py`, Ollama `/api/chat` with streaming, `num_ctx=4096`, `temperature=0.1`, `num_predict=512`, one discarded warm-up per model, 3 runs per question (in-RAG 16, out-of-RAG 12, ambiguous 8). Chunk metadata has no `title` in the DB, so context headers show "documento" plus URL, as the engine would.
- Scoring: `valid` = `validate_answer` passes and the text has at least 40 characters besides `[n]` markers; `declined` = exact `NAO_ENCONTRADO` (or sentinel plus markers, counted separately as "loose decline"); `invalid` = would fall back to extractive. Out-of-RAG refusal = declined or gated. Ambiguous acceptable = declined, or valid with no forbidden terms.


## 2. Results

### Latency and groundedness (full set, 3 runs, GPU allowed)

Substantive answers = valid citations plus real content. Declines such as `NAO_ENCONTRADO` are short, so they are excluded from the answer columns. `no_content` = only `[n]` markers; `loose decline` = sentinel plus markers (refusal intent, but the engine's exact-match `is_decline` would show it to the user as text); both counted over all runs.

| Model | Answers | Answer TTFT cold, run 1 (s) | Answer TTFT med (s) | Answer TTFT p95 (s) | Answer total med (s) | Answer total p95 (s) | All-calls TTFT med (s) | All-calls total med (s) | tok/s | Citation-valid | In-RAG valid | In-RAG false refusal | In-RAG fallback | no_content | loose decline | must_mention |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b-instruct | 0 | n/a | n/a | n/a | n/a | n/a | 0.06 | 0.23 | 41.3 | 0% | 0% | 38% | 62% | 29 | 0 | n/a |
| gemma3:4b | 37 | 1.41 | 0.39 | 1.57 | 8.47 | 17.40 | 0.48 | 1.81 | 12.3 | 88% | 65% | 25% | 10% | 0 | 0 | 50% |
| qwen2.5:7b-instruct | 27 | 1.69 | 0.24 | 1.92 | 12.68 | 23.29 | 0.28 | 2.38 | 6.8 | 100% | 56% | 44% | 0% | 0 | 29 | 100% |

### Refusal correctness (full set, 3 runs)

| Model | Out-of-RAG refused (total) | by model | gated by min_score | answered with citation | fallback | off-topic terms leaked | Ambiguous acceptable | Ambiguous fallback | Ambiguous leaks |
|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b-instruct | 100% | 100% | 0% | 0% | 0% | 0/36 | 100% | 0% | 0/24 |
| gemma3:4b | 100% | 100% | 0% | 0% | 0% | 0/36 | 100% | 0% | 0/24 |
| qwen2.5:7b-instruct | 100% | 100% | 0% | 0% | 0% | 0/36 | 100% | 0% | 0/24 |

Question counts: in_rag=48, out_of_rag=36, ambiguous=24. Latency rows only count calls that reached the LLM (questions gated by min_score never call it).

### CPU-only datapoint (`num_gpu=0`, 7 questions x 2 runs; small sample)

Substantive answers = valid citations plus real content. Declines such as `NAO_ENCONTRADO` are short, so they are excluded from the answer columns. `no_content` = only `[n]` markers; `loose decline` = sentinel plus markers (refusal intent, but the engine's exact-match `is_decline` would show it to the user as text); both counted over all runs.

| Model | Answers | Answer TTFT cold, run 1 (s) | Answer TTFT med (s) | Answer TTFT p95 (s) | Answer total med (s) | Answer total p95 (s) | All-calls TTFT med (s) | All-calls total med (s) | tok/s | Citation-valid | In-RAG valid | In-RAG false refusal | In-RAG fallback | no_content | loose decline | must_mention |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b-instruct | 0 | n/a | n/a | n/a | n/a | n/a | 3.87 | 4.34 | 17.8 | 0% | 0% | 0% | 100% | 10 | 0 | n/a |
| gemma3:4b | 7 | 23.20 | 0.49 | 24.41 | 8.17 | 32.18 | 6.19 | 12.14 | 12.2 | 70% | 70% | 0% | 30% | 0 | 0 | 100% |
| qwen2.5:7b-instruct | 8 | 31.93 | 9.09 | 34.02 | 18.96 | 43.39 | 9.09 | 18.96 | 7.9 | 100% | 80% | 20% | 0% | 0 | 2 | 100% |

## 3. PT-BR vs EN retrieval (bge-large-en-v1.5, read-only, no re-ingest)

Top-k=8, min_score=0.5. In-RAG questions (n=16). Variant `e5` = `query: ` prefix (current CIP config), `none` = no prefix, `bge` = official BGE retrieval instruction.

| Lang | Prefix | recall@1 | recall@k | top-1 median | top-1 min | top-1 max | top-1 < min_score | chunks >= min_score (mean) | out-of-RAG top-1 >= min_score | ambiguous top-1 >= min_score |
|---|---|---|---|---|---|---|---|---|---|---|
| pt | none | 81% | 94% | 0.71 | 0.57 | 0.74 | 0% | 8.0 | 92% | 100% |
| pt | e5 | 81% | 94% | 0.72 | 0.61 | 0.75 | 0% | 8.0 | 100% | 100% |
| pt | bge | 88% | 94% | 0.72 | 0.57 | 0.76 | 0% | 8.0 | 100% | 100% |
| en | none | 100% | 100% | 0.78 | 0.70 | 0.81 | 0% | 8.0 | 58% | 100% |
| en | e5 | 100% | 100% | 0.79 | 0.70 | 0.82 | 0% | 8.0 | 92% | 100% |
| en | bge | 100% | 100% | 0.79 | 0.69 | 0.82 | 0% | 8.0 | 75% | 100% |

Per-question top-1 (prefix `e5`, as in production):

| id | PT top-1 score | PT top-1 service | EN top-1 score | EN top-1 service | expected |
|---|---|---|---|---|---|
| in-01 | 0.703 | s3-postmortem | 0.785 | s3 | s3 |
| in-02 | 0.727 | architecture-framework | 0.798 | architecture-framework | architecture-framework |
| in-03 | 0.748 | eks | 0.801 | eks | eks |
| in-04 | 0.607 | case-studies | 0.798 | iam | iam |
| in-05 | 0.716 | lambda | 0.810 | lambda | lambda |
| in-06 | 0.748 | rds | 0.808 | rds | rds,aurora |
| in-07 | 0.741 | dynamodb | 0.789 | dynamodb | dynamodb |
| in-08 | 0.659 | kms | 0.822 | kms | kms |
| in-09 | 0.728 | vpc | 0.780 | vpc | vpc |
| in-10 | 0.693 | aks | 0.721 | aks | aks |
| in-11 | 0.717 | entra-id | 0.754 | entra-id | entra-id |
| in-12 | 0.740 | key-vault | 0.792 | key-vault | key-vault |
| in-13 | 0.747 | cosmos-db | 0.747 | cosmos-db | cosmos-db |
| in-14 | 0.713 | arm-templates | 0.791 | policy | policy |
| in-15 | 0.674 | kubernetes | 0.700 | kubernetes | kubernetes |
| in-16 | 0.735 | terraform | 0.769 | terraform | terraform |
