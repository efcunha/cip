# Operação: robustez, concorrência e não-alucinação

Como operar a plataforma de forma estável sob carga (ex.: ~100 usuários
simultâneos), mantendo respostas ancoradas (sem alucinar) e sem travar/loop.

## Não-loop (por design)

O pipeline **não é um agente ReAct em loop**: `router heurístico → tools
(best-effort, com try/except) → RAG single-shot → consolidação`. Não há
re-planejamento nem tool-calling recursivo, logo não há risco de loop infinito.
As chamadas ao provedor têm **timeout** e **`max_retries` baixo** (evita retry
storm). Se um dia for introduzido tool-calling agêntico, adicionar um teto de
iterações.

## Não-alucinação

- RAG com corte por `RETRIEVAL_MIN_SCORE` (nós abaixo do score são descartados).
- **Recusa explícita** quando não há contexto acima do score (`has_grounding=False`).
- System prompt: responder **apenas** com base no contexto, citar fontes, não
  inventar preços/limites.
- `LLM_TEMPERATURE=0.1`.
- Lembrete: `RETRIEVAL_MIN_SCORE` depende do modelo de embeddings
  (e5-small ≈ 0.80; bge-large ≈ 0.35). Revalidar com `eval/run_eval.py`.

## Robustez sob carga (bloco 1 — implementado)

Controles adicionados para não "derreter" em picos:

| Config | Padrão | Efeito |
|--------|--------|--------|
| `MAX_CONCURRENT_REQUESTS` | 200 | Acima disso a API responde **429** (backpressure) em vez de empilhar |
| `REQUEST_TIMEOUT_S` | 90 | Request que estoura o tempo → **504** (libera recursos) |
| `LLM_TIMEOUT_S` | 60 | Timeout da chamada ao LLM |
| `LLM_MAX_RETRIES` | 2 | Evita retry storm |
| `LLM_MAX_TOKENS` | 2048 | Teto de saída (default do SDK é 512 = trunca) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 20 / 20 | Pool de conexões pgvector dimensionado p/ concorrência |

O `/health` não passa pelo controle (liveness sempre responde).

## Configuração de referência para ~100 usuários simultâneos

O gargalo é o **LLM** (API gerenciada), não o servidor de app. Como o LLM é
gerenciado, o tier de aplicação permanece **pequeno e barato**; escala-se
horizontalmente.

- **LLM (Bedrock)**: roteie por complexidade — `/ask` → Claude Haiku (barato,
  rápido); `/analyze` → Claude Sonnet. Garanta **quota** para ~100-150
  requisições concorrentes (RPM/TPM) ou use Provisioned Throughput / inferência
  cross-region. Prefira **streaming** para reduzir latência percebida.
- **Embeddings**: para alta concorrência, `EMBED_PROVIDER=bedrock` (Titan) tira a
  CPU do caminho crítico. Alternativa: `local` (e5-small) com 3-4 réplicas
  (modelo é GIL-bound; o embed de query é 1 vetor curto, ~10-30ms).
- **App**: stateless → `gunicorn` + workers uvicorn (2-4 réplicas × 2-4 workers)
  atrás de um load balancer. Cada réplica ~2 vCPU / 2-4 GB.
- **pgvector** (gerenciado): 2-4 vCPU; pool 20-40; `hnsw_ef_search` 40-64
  (recall × latência).
- **Redis** (bloco 2): cache semântico de respostas (evita chamar o LLM em
  perguntas repetidas), estado de chat multi-turno e rate limiting por usuário.
- **Observabilidade**: Langfuse + métricas de fila/latência/erros e dos 429/504.

## Roadmap dos próximos blocos

- **Bloco 2 — Redis**: cache semântico + memória de chat multi-turno + rate limit.
- **Bloco 3 — LLM**: roteamento Haiku/Sonnet por complexidade + endpoint de streaming.
- **Bloco 4 — Embeddings gerenciados**: perfil de alta concorrência (só config).
