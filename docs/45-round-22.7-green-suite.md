# Round 22.7 — Green suite: zerar os 8 testes pré-existentes

> **Data**: 2026-08-26 | **Escopo**: zerar os 8 testes que falhavam desde o Round 22.4
> SEM regredir o gate de homolog (10/10) nem os 587 passing. Sem tocar em `router.py`
> nem `_resolve_cloud_from_area` (restrição herdada do Round 22).

---

## 🎯 Resultado

| Métrica | Antes | Depois |
|---|---|---|
| Testes | 8 failed / 587 passed | **0 failed / 595 passed** |
| Homolog full run 1 | 10/10 (baseline) | **10/10** (acc 5.00 em todos) |
| Homolog full run 2 | 10/10 (baseline) | **10/10** (acc 5.00 em todos) |

Os 8 failures eram todos **pré-existentes** (documentados no Round 22.6 como fora de
escopo). Nenhuma regressão introduzida — os 587 passing subiram para 595 (os 8 que
falhavam agora passam).

---

## ✅ PASSO 1 — Diagnóstico dos 8

`IS_TESTING=1 pytest -q --ignore=test_smoke_ask --ignore=test_ingest_delta -rf` → 8 failed:

| Teste | Causa raiz (ROOT CAUSE) |
|---|---|
| `test_web_ui.py::TestJavaScriptStructure` (5) | `web/app.js` foi legitimamente refatorado no Round 22 (chat multi-turn, SSE, feedback, sidebar). As asserções referenciam nomes de função antigos que não existem mais. |
| `test_tools_cache.py::test_azure_tools_degrade_gracefully` (1) | `AzureAdvisorTools.__init__` chamava `DefaultAzureCredential()` que **lança em __init__** quando não há credenciais (dev/CI) — não degradava. |
| `test_mock_cloud_cli.py::test_subcommand_status_runs` (1) | `cmd_status` chamava o `run_all_checks()` **async** SEM `await/asyncio.run()` → retornava um coroutine → `AttributeError` → exit 2. |
| `test_inspection_rules.py::test_detects_prod_rds_without_multi_az` (1) | hcl2 retorna `tags` como **dict com valores entre aspas** (`{"Environment": '"prod"'}`); a regra não removia as aspas, então `env` nunca casava com `prod`. |

---

## ✅ PASSO 2 — web_ui (5 testes), asserções factualmente desatualizadas

### Diagnóstico

`web/app.js` (Round 22+) evoluiu e **enriqueceu** — a funcionalidade que as asserções
guardavam continua presente, sob novos nomes:

| Asserção antiga | Realidade no app.js atual |
|---|---|
| `async function callAnalyzeStream` | removida — consolidada no chat multi-turn (`sendConversationMessage`, `createConversation`, `listConversations`) |
| `consumeSSE` | renomeada → `parseSSE` |
| `function addMessage` | renomeada → `appendMessage` (+ `addUserMessage`/`appendAssistantMessage`) |
| `function addStreamingMessage` | renomeada → `appendStreamingAssistant` |
| ` ``` ` (fenced code blocks) | `formatAnswer()` usa `**`→`<strong>` e `` ` ``→`<code>`; fenced blocks removidos |
| `finding`/`severity`/`recommendation` | conceito migrou para Inspection Engine (backend) + `.finding` CSS; o cliente agora renderiza metadata (grounding/latência) + feedback |

### Correção (ajuste de **teste**, não de web/)

O JS está correto e mais rico — atualizei as asserções para refletir a estrutura real,
mantendo a INTENÇÃO de cobertura (API client, streaming SSE, UI, markdown, metadata):

- `test_js_has_api_client_functions` → verifica `callHealth`/`callAsk`/`callAskStream` +
  as funções de conversa multi-turn (`sendConversationMessage`/`createConversation`/`listConversations`).
- `test_js_has_streaming_support` → `parseSSE` + `event:`/`data:` + eventos `chunk`/`done`.
- `test_js_has_ui_functions` → `setStatus`/`appendMessage`/`appendStreamingAssistant`/`sendMessage`/`formatAnswer`.
- `test_js_handles_markdown` → `**`→`<strong>` e `` ` ``→`<code>` (renderização real).
- `test_js_handles_findings` → metadata real (`has_grounding`/`sources_count`/`latency_ms`) +
  `feedback` + `.finding` em `style.css`.

> Justificativa: asserção factualmente desatualizada, NÃO afrouxada — cada linha nova
> corresponde a código real do `app.js`/`style.css` atual.

---

## ✅ PASSO 3 — Azure creds + cip_cli status + RDS Multi-AZ

### Azure tools creds (`azure_advisor.py`)

`DefaultAzureCredential()` lança `ValueError` em `__init__` quando as env vars de
credencial são vazias. Envolvi a construção da credencial em `try/except`: sem credenciais,
`self.advisor = None` e um warn é logado; os métodos `get_*_recommendations()` retornam
`[]` e `summarize()` retorna a mensagem amigável — **degradação graciosa** em vez de
exceção.

### cip_cli status (`scripts/cip_cli.py`)

`cmd_status` chamava `run_all_checks()` (async, awai­ta conexões DB direto) sem await.
Adicionei `import asyncio` + `asyncio.run(run_all_checks())` (fora de event loop, correto).
Resultado: `status` agora imprime os 4 checks e retorna 0 (HEALTHY).

### RDS Multi-AZ (`terraform.py`)

A regra T4/T7 comparava `env` contra `{"prod","production","prd"}`, mas hcl2 devolve
`tags={"Environment": '"prod"'}` (valor **com aspas literais**). Normalizei via `_unq`
(que já faz `strip('"')`) antes do `.lower()` → detecção de prod RDS sem Multi-AZ volta a
funcionar (finding `high`/`reliability`).

---

## ✅ PASSO 4 — Regressão completa

```
$ podman exec cip-api sh -lc "IS_TESTING=1 pytest -q --ignore=test_smoke_ask --ignore=test_ingest_delta"
595 passed, 19 skipped, 4 warnings in 257.18s
```

**0 failed** — os 8 foram zerados e os 587 anteriores preservados.

Homolog full 2x (LLM real MiniMax M3):

- Run 1 = **10/10** (acc 5.00 em todos os casos)
- Run 2 = **10/10** (acc 5.00 em todos os casos)

> Entre as runs, o gateway upstream MiniMax passou por uma janela transiente de
> `502 Bad Gateway`/`503 Service Temporarily Unavailable` (nginx). Identifiquei dois
> pontos de robustez no `homolog_validate.py` e corrigi (ver PASSO 4b abaixo). Após a
> recuperação do upstream, a Run 2 fechou limpa em 10/10.

Report re-sincronizado com a rodada final: `eval/results/homolog_report.md` +
`eval/results/homolog_results.json` (provider `minimax`, 10/10, acc 5.00, grounding 10/10,
0 erros).

---

## ✅ PASSO 4b — Robustez do homolog diante de erro transiente upstream

Durante a Run 2, os 3 últimos casos (`arch-004`, `cases-001`, `cases-002`) falharam com
`InternalServerError: 502/503` do gateway nginx do MiniMax — **não** era regressão de
qualidade (a acc das menções continuava 5.0 nas runs saudáveis). Dois pontos foram
corrigidos em `scripts/homolog_validate.py`:

1. **Retry de transiente** — `TRANSIENT_ERRORS` em `_build_orchestrator_sync_runner` não
   reconhecia `InternalServerError`/`502 Bad Gateway`/`503 Service Temporarily
   Unavailable`. Adicionados os tokens, o retry (2x com backoff) agora cobre o 502/503
   upstream.
2. **`StatisticsError` no report parcial** — `render_report()` e os `summary` JSON
   calculavam `statistics.mean([... if not r.error])` sem guardar lista vazia; quando o
   PRIMEIRO caso errava (todos com `error`), `statistics.mean([])` lançava
   `StatisticsError` e derrubava o `_write_partial_report`. Agora usam
   `if [r for r in results if not r.error] else 0`.

---

## ✅ PASSO 5 — Decisão do gate CI (`--runs`)

- O `ci-eval` (Makefile) e o job CI `eval-gate` rodam `run_eval.py --offline --strict` —
  eval **offline/determinístico** (Inspection Engine, sem LLM). `--runs N` não faz sentido
  aí (não há variância de temperatura).
- O gate com variância é o homolog com LLM real (`homolog_validate.py`). Apliquei
  `--runs 3` no target `homolog-real` do Makefile (por maioria, reduz falso-negativo),
  mantendo o `ci-eval` sem `--runs` (determinístico).

### Diff (Makefile)

```diff
-homolog-real:  ## Homolog end-to-end com LLM real (LLM_PROVIDER=minimax padrao)
+homolog-real:  ## Homolog ... (LLM_PROVIDER=minimax padrao, --runs 3 por maioria)
- python scripts/homolog_validate.py --strict
+ python scripts/homolog_validate.py --strict --runs 3
```

> `--runs 3` foi implementado no gate de homolog (onde a variância importa), não no
> `ci-eval` offline. Nenhum `--runs` no CI offline — documentado acima.

---

## 📁 Artefatos alterados

| Arquivo | Mudança |
|---|---|
| `src/cip/tools/azure_advisor.py` | degradação graciosa sem credenciais (`advisor=None`, guard `[]`) |
| `scripts/cip_cli.py` | `cmd_status` usa `asyncio.run(run_all_checks())` |
| `src/cip/inspection/terraform.py` | regra RDS Multi-AZ normaliza tags via `_unq` |
| `tests/test_web_ui.py` | 5 asserções atualizadas para a estrutura real do `app.js` |
| `scripts/homolog_validate.py` | retry de transiente 502/503 + guard `StatisticsError` |
| `Makefile` | `homolog-real` com `--runs 3`; comentário no `ci-eval` |
| `eval/results/homolog_report.md` + `.json` | re-sincronizados com a rodada final |

---

## 🎯 Gaps para review (KIRO)

1. Os 3 warnings de `RuntimeWarning: coroutine ... never awaited` em `test_react.py` são
   pré-existentes (fora deste escopo) — oportunidades futuras de correção de await.
2. A label da regra RDS Multi-AZ oscila entre "T4" (código/teste) e "T7" (docstring do
   catálogo em `terraform.py`) — inconsistência cosmética a normalizar.
3. `ci-eval` (offline) permanece sem `--runs`; o `homolog-real` agora usa `--runs 3` —
   confirmar se o pipeline de release deve adotar `--runs 3` também no homolog.
