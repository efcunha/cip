# Provider DeepSeek (fallback do MiniMax M3) — Round 22.1

> **Data**: 2026-08-25 | **Escopo**: adicionar DeepSeek-V4-Flash como LLM alternativo

---

## 🎯 Resultado

Adicionado o provider **`deepseek`** (DeepSeek-V4-Flash) como alternativa ao MiniMax M3. O provider é OpenAI-compatible e usa o mesmo padrão de instanciação do MiniMax (`llama_index.llms.openai_like` com fallback via `openai.OpenAI`).

A chave DeepSeek fornecida **funciona** — a homologação real com LLM foi **desbloqueada** (antes estava BLOQUEADA por chave MiniMax placeholder).

| Item | Status |
|---|---|
| Provider `deepseek` no `llm_provider` Literal | ✅ |
| Campo `deepseek_api_key` (alias `DEEPSEEK_API_KEY`) | ✅ |
| Campo `deepseek_base_url` (isolado do `LLM_BASE_URL` global) | ✅ |
| `build_llm()` instancia DeepSeek corretamente | ✅ (OpenAILike) |
| Inferência real (chave fornecida) | ✅ `RESPONSE: OK` |
| Homolog real com DeepSeek | ✅ 2/10 passed, grounding 10/10, 0 erros |

---

## ✅ Entregas Concretas

### 1. `src/cip/config.py`

- `llm_provider` agora aceita `"deepseek"`.
- Novo campo `deepseek_api_key` (`validation_alias="DEEPSEEK_API_KEY"`).
- Novo campo `deepseek_base_url` (`validation_alias="DEEPSEEK_BASE_URL"`).

```diff
- llm_provider: Literal["bedrock", "openai", "local", "stub", "minimax"] = "bedrock"
+ llm_provider: Literal["bedrock", "openai", "local", "stub", "minimax", "deepseek"] = "bedrock"
+ deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
+ deepseek_base_url: str = Field(default="", validation_alias="DEEPSEEK_BASE_URL")
```

### 2. `src/cip/rag/llm.py`

Novo branch `if provider == "deepseek"` no `build_llm()`, espelhando o MiniMax (OpenAILike + shim fallback). Ordem de credencial: `LLM_API_KEY` → `DEEPSEEK_API_KEY` → env `DEEPSEEK_API_KEY`.

```diff
+ if provider == "deepseek":
+     api_key = (settings.llm_api_key or settings.deepseek_api_key
+                or os.environ.get("DEEPSEEK_API_KEY", "") or "not-set")
+     base_url = settings.deepseek_base_url or "https://api.deepseek.com/v1"
+     ... # OpenAILike + _DeepSeekShimLLM fallback
```

### 3. `scripts/homolog_validate.py`

- `require_real_provider()` aceita `deepseek` como provider real.
- `estimate_cost()` adiciona taxa DeepSeek `(0.28, 0.42)` USD/1M tokens.

### 4. `.env` (gitignored) + `.env.example` (versionado com placeholder)

```env
DEEPSEEK_API_KEY=sk-...            # .env — valor real (gitignored)
# .env.example:
# LLM_PROVIDER=deepseek
# LLM_MODEL=deepseek-v4-flash
# LLM_API_KEY=sk-SEU-TOKEN-AQUI
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1   (opcional; já é o default)
```

---

## 🧪 Validação (saídas reais)

### Instanciação

```
$ podman exec cip-api python /tmp/check_deepseek.py
provider = deepseek
model    = deepseek-v4-flash
deepseek_api_key set = True
deepseek key prefix  = sk-22f9c...
deepseek_llm_active  api_base=https://api.deepseek.com/v1 api_key_prefix=sk-22f9cca... model=deepseek-v4-flash
llm type = OpenAILike
```

### Inferência real

```
$ podman exec cip-api python /tmp/check_deepseek_infer.py
RESPONSE: OK
```

### Homologação real (10 casos)

```
$ podman exec cip-api sh -lc "cd /app && LLM_PROVIDER=deepseek LLM_MODEL=deepseek-v4-flash python scripts/homolog_validate.py --strict"

Provider LLM: deepseek
2/10 passaram   |   Grounding: 10/10   |   Erros: 0
Accuracy média: 2.77   |   Latência média: 20678 ms   |   Custo: $0.0059
```

| Area | Pass | Accuracy |
|---|---|---|
| aws | 1/2 | 3.75 |
| gcp | 1/1 | 4.00 |
| azure | 0/1 | 2.67 |
| software_architecture | 0/4 | 2.66 |
| case_studies | 0/2 | 1.44 |

---

## ⚠️ Observações / Próximos Passos

1. **Nome do modelo na API**: a API DeepSeek aceita `deepseek-v4-flash` (lowercase), **não** `DeepSeek-V4-Flash`. Usar o nome exato `deepseek-v4-flash`.

2. **Base URL isolado por provider**: o `deepseek_base_url` foi separado do `LLM_BASE_URL` global porque o `.env` local aponta `LLM_BASE_URL=https://api.minimax.io/v1` (MiniMax). Sem o isolamento, a chave DeepSeek era enviada para a API do MiniMax → `401 login fail`. O DeepSeek agora usa `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com/v1`).

3. **Gate de accuracy baixo (2.77)**: o DeepSeek responde com grounding válido (10/10) mas não menciona todos os termos da rubrica `must_mention` bilíngue. Para melhorar o score, é preciso **ajustar os prompts dos especialistas** (instrução explícita de cobrir os tópicos da rubrica) ou **relaxar o gate** para o modo de évaluation real. Isso é um problema de qualidade de resposta, não de infraestrutura.

4. **Chave exposta no chat**: a chave `sk-<REDACTED>` foi colada no prompt. Ela foi gravada apenas no `.env` (gitignored). Recomenda-se **rotacionar** a chave caso o chat seja compartilhado/versionado.
