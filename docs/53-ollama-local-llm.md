# LLM local (Ollama) no chat RAG do CIP

> Escopo: respostas geradas **somente** a partir do contexto recuperado do RAG por um modelo
> pequeno em CPU servido pelo Ollama (`LLM_PROVIDER=local`). Não faz deploy; ver
> `ops/ollama/README.md`.

## Fluxo (`LLM_PROVIDER=local`)

1. Retrieval (`retrieval_top_k=8`) e gate de `retrieval_min_score` **antes** do LLM. Nada acima do
   score => recusa, o LLM nunca é chamado.
2. Os melhores `LLM_CONTEXT_TOP_K` (5) trechos, cada um cortado em `LLM_CONTEXT_CHUNK_CHARS`
   (1200), vão numerados `[1]..[k]` com prompt estrito (`rag/grounded.py`): responder só com o
   contexto, citar `[n]`, sem URLs, responder `NAO_ENCONTRADO` quando o contexto não responde.
3. Os tokens saem como eventos SSE `chunk` conforme são gerados. Depois: citações devem estar em
   `1..k` e toda URL deve estar entre os trechos recuperados. Uma lista determinística
   "Fontes:" é anexada.
4. Uma geração por pergunta: especialistas usam síntese extrativa; só a resposta base chama o LLM
   (o Ollama serializa, `OLLAMA_NUM_PARALLEL=1`).

## Fallback para extractive (padrão em qualquer falha do Ollama)

| Gatilho | `done.fallback` |
|---|---|
| erro de conexão/HTTP | `llm_error:<Tipo>` |
| sem 1o token em `LLM_FIRST_TOKEN_TIMEOUT_S` | `timeout_first_token` |
| tempo total acima de `LLM_TIMEOUT_S` | `timeout_total` |
| saída vazia | `empty_output` |
| citação ausente/fora da faixa, URL estranha | `validation:<motivo>` |

Cada fallback registra `llm_fallback_extractive` (reason, model, elapsed_ms). Resultado de
fallback não vai para o cache. Se o modelo responde `NAO_ENCONTRADO`, o resultado é recusa
(`refusal_reason=model_declined`). Texto já enviado não pode ser retirado: se a geração falha no
meio, um aviso e o texto extrativo são anexados e `done.answer` traz o texto extrativo.

## Contrato SSE

Eventos continuam `chunk` / `done` / `error`. Campos novos (aditivos) em `done`: `fallback`
(string ou null) e `ttft_ms`. Os demais providers mantêm o chunking simulado de 50 caracteres.

## Variáveis de ambiente

| Variável | Padrão | Nota |
|---|---|---|
| `LLM_PROVIDER` | `bedrock` | `local` ativa este caminho |
| `LLM_BASE_URL` | vazio | `http://ollama:11434/v1`; vazio mantém `http://localhost:8001/v1` |
| `LLM_API_KEY` | vazio | opcional; envia `not-needed` se vazio |
| `LLM_FIRST_TOKEN_TIMEOUT_S` | 30 | |
| `LLM_CONTEXT_TOP_K` | 5 | trechos enviados ao modelo |
| `LLM_CONTEXT_CHUNK_CHARS` | 1200 | |
| `QUERY_TRANSLATION_ENABLED` | true | traduz PT-BR -> EN antes do retrieval; só com LLM real |
| `QUERY_TRANSLATION_TIMEOUT_S` | 5 | timeout/falha usa a pergunta original |
| `QUERY_TRANSLATION_CACHE_TTL_S` | 86400 | TTL do cache de traduções |

`num_ctx`, `num_thread`, `keep_alive` não podem ser definidos por requisição via `/v1`; ficam
no env do servidor Ollama e no Modelfile derivado (`ops/ollama/`).

## Achados conhecidos

- **Divergência de embeddings**: o corpus vivo é `data_cloud_docs`, 1024 dims
  (`bge-large-en-v1.5`). `docker-compose.prod.yml` e `.env.prod.example` usam
  `multilingual-e5-small` / 384 e não casam. Não alterado (quebraria instalações compose
  existentes); a VPS usa Quadlet + `cip.env`. Sem re-ingestão.
- `EMBED_QUERY_INSTRUCTION="query: "` é convenção E5 aplicada a um modelo BGE. Não alterado;
  medido no passo de eval.

## Pontos em aberto

Limites de CPU/memória e threads da unit do Ollama, e o modelo base (passo de eval).

## Rollback

`LLM_PROVIDER=extractive` no `cip.env`, reiniciar `cip-api`, parar o `ollama`.
