# DeepSeek Provider (fallback of MiniMax M3) — Round 22.1

> **Date**: 2026-08-25 | **Scope**: add DeepSeek-V4-Flash as an alternative LLM

---

## 🎯 Result

Added the **`deepseek`** provider (DeepSeek-V4-Flash) as an alternative to MiniMax M3. The provider is OpenAI-compatible and uses the same instantiation pattern as MiniMax (`llama_index.llms.openai_like` with fallback via `openai.OpenAI`).

The provided DeepSeek key **works** — real-LLM homologation was **unblocked** (it was previously BLOCKED by a placeholder MiniMax key).

| Item | Status |
|---|---|
| `deepseek` provider in the `llm_provider` Literal | ✅ |
| `deepseek_api_key` field (alias `DEEPSEEK_API_KEY`) | ✅ |
| `deepseek_base_url` field (isolated from the global `LLM_BASE_URL`) | ✅ |
| `build_llm()` instantiates DeepSeek correctly | ✅ (OpenAILike) |
| Real inference (provided key) | ✅ `RESPONSE: OK` |
| Real homologation with DeepSeek | ✅ 2/10 passed, grounding 10/10, 0 errors |

---

## ✅ Concrete Deliverables

### 1. `src/cip/config.py`

- `llm_provider` now accepts `"deepseek"`.
- New field `deepseek_api_key` (`validation_alias="DEEPSEEK_API_KEY"`).
- New field `deepseek_base_url` (`validation_alias="DEEPSEEK_BASE_URL"`).

```diff
- llm_provider: Literal["bedrock", "openai", "local", "stub", "minimax"] = "bedrock"
+ llm_provider: Literal["bedrock", "openai", "local", "stub", "minimax", "deepseek"] = "bedrock"
+ deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
+ deepseek_base_url: str = Field(default="", validation_alias="DEEPSEEK_BASE_URL")
```

### 2. `src/cip/rag/llm.py`

New branch `if provider == "deepseek"` in `build_llm()`, mirroring MiniMax (OpenAILike + shim fallback). Credential order: `LLM_API_KEY` → `DEEPSEEK_API_KEY` → `DEEPSEEK_API_KEY` env.

```diff
+ if provider == "deepseek":
+     api_key = (settings.llm_api_key or settings.deepseek_api_key
+                or os.environ.get("DEEPSEEK_API_KEY", "") or "not-set")
+     base_url = settings.deepseek_base_url or "https://api.deepseek.com/v1"
+     ... # OpenAILike + _DeepSeekShimLLM fallback
```

### 3. `scripts/homolog_validate.py`

- `require_real_provider()` accepts `deepseek` as a real provider.
- `estimate_cost()` adds the DeepSeek rate `(0.28, 0.42)` USD/1M tokens.

### 4. `.env` (gitignored) + `.env.example` (versioned with placeholder)

```env
DEEPSEEK_API_KEY=sk-...            # .env — real value (gitignored)
# .env.example:
# LLM_PROVIDER=deepseek
# LLM_MODEL=deepseek-v4-flash
# LLM_API_KEY=sk-YOUR-TOKEN-HERE
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1   (optional; already the default)
```

---

## 🧪 Validation (real outputs)

### Instantiation

```
$ podman exec cip-api python /tmp/check_deepseek.py
provider = deepseek
model    = deepseek-v4-flash
deepseek_api_key set = True
deepseek key prefix  = sk-22f9c...
deepseek_llm_active  api_base=https://api.deepseek.com/v1 api_key_prefix=sk-22f9cca... model=deepseek-v4-flash
llm type = OpenAILike
```

### Real inference

```
$ podman exec cip-api python /tmp/check_deepseek_infer.py
RESPONSE: OK
```

### Real homologation (10 cases)

```
$ podman exec cip-api sh -lc "cd /app && LLM_PROVIDER=deepseek LLM_MODEL=deepseek-v4-flash python scripts/homolog_validate.py --strict"

Provider LLM: deepseek
2/10 passed   |   Grounding: 10/10   |   Errors: 0
Average accuracy: 2.77   |   Average latency: 20678 ms   |   Cost: $0.0059
```

| Area | Pass | Accuracy |
|---|---|---|
| aws | 1/2 | 3.75 |
| gcp | 1/1 | 4.00 |
| azure | 0/1 | 2.67 |
| software_architecture | 0/4 | 2.66 |
| case_studies | 0/2 | 1.44 |

---

## ⚠️ Observations / Next Steps

1. **Model name in the API**: the DeepSeek API accepts `deepseek-v4-flash` (lowercase), **not** `DeepSeek-V4-Flash`. Use the exact name `deepseek-v4-flash`.

2. **Base URL isolated per provider**: `deepseek_base_url` was separated from the global `LLM_BASE_URL` because the local `.env` points `LLM_BASE_URL=https://api.minimax.io/v1` (MiniMax). Without the isolation, the DeepSeek key was sent to the MiniMax API → `401 login fail`. DeepSeek now uses `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com/v1`).

3. **Low accuracy gate (2.77)**: DeepSeek responds with valid grounding (10/10) but does not mention all terms of the bilingual `must_mention` rubric. To improve the score, you need to **adjust the specialist prompts** (explicit instruction to cover the rubric topics) or **relax the gate** for the real-evaluation mode. This is a response-quality problem, not an infrastructure problem.

4. **Key exposed in chat**: the key `sk-<REDACTED>` was pasted into the prompt. It was only written to `.env` (gitignored). It is recommended to **rotate** the key in case the chat is shared/versioned.
