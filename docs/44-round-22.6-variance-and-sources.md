# Round 22.6 — Eliminação de variância do azure-001 e cura de uber/gitlab

> **Data**: 2026-08-26 | **Escopo**: 3 gaps residuais do Round 22.5 SEM regredir o gate de
> homolog (10/10) nem os 587 testes. Sem mudança em routing/retrieval — `router.py` e
> `_resolve_cloud_from_area` NÃO foram tocados (lição do Round 22).

---

## 🎯 Resultado

| GAP | Antes | Depois |
|---|---|---|
| Variância do `azure-001` (5.00/3.00/4.33) | oscilava por omissão de pilares | **3/3 runs acc=5.00** (prompt enumera os 6 pilares) |
| `uber-engineering` sem chunks | 0 chunks (fetch thin/JS) | **18 chunks** (Schemaless curado) |
| `gitlab-incidents` sem chunks | 0 chunks (fetch thin/JS) | **18 chunks** (postmortem 2017 curado) |
| Falso-negativo por variância temp | gate single-run | **`--runs N` por maioria** (default 1 intacto) |

- Homolog full: Run 1 = **10/10**, Run 2 = **10/10** (estável; sem o 9/10 do Round 22.5).
- Regressão: **587 passed / 8 failed / 19 skipped** — idêntico ao baseline (sem regressão).

---

## ✅ PASSO 1 — Eliminar variância do azure-001

### Diagnóstico (ROOT CAUSE)

`homolog-azure-001` pergunta "Quais os pilares do Azure Well-Architected Framework?". A
rubrica exige 6 conceitos: `reliability`, `security`, `cost optimization`,
`operational excellence`, `performance efficiency` + `sustainability`. O especialista
`azure` (em `src/cip/prompts/specialists.py`) descrevia o WAF como "(5 pilares +
Sustainability)" SEM instruir a enumeração explícita, então o LLM (DeepSeek, temp 0.1)
às vezes omitia o pilar *Sustainability* — acc oscilava 5.00/3.00/4.33.

### Correção

`AZURE` em `src/cip/prompts/specialists.py` agora instrui a **SEMPRE** enumerar
explicitamente, um a um, TODOS os pilares do WAF, citando os termos em inglês:

1. Reliability (Confiabilidade)
2. Security (Segurança)
3. Cost Optimization (Otimização de Custos)
4. Operational Excellence (Excelência Operacional)
5. Performance Efficiency (Eficiência de Performance)
6. Sustainability (Sustentabilidade) — pilar transversal

> São os pilares oficiais do Microsoft Azure Well-Architected Framework
> (<https://learn.microsoft.com/en-us/azure/well-architected/>) — nenhum pilar inventado.

### Prova (homolog azure, deepseek, 3 runs)

| Run | acc azure-001 | gate |
|---|---|---|
| 1 | 5.00 | PASS |
| 2 | 5.00 | PASS |
| 3 | 5.00 | PASS |

Meta (acc ≥ 4.0 em 3/3 runs) atingida com folga: **5.00 em todas as runs**.

---

## ✅ PASSO 2 — Curar uber e gitlab (fetch thin/JS)

### Diagnóstico

`uber-engineering` (`https://www.uber.com/blog/engineering/`) e `gitlab-incidents`
(`https://about.gitlab.com/handbook/engineering/postmortems/`) são SPA/JS-blocked para o
fetcher `SimpleWebPageReader` — devolviam 14/41 chars (thin), descartados pelo
`MIN_CONTENT_CHARS`. Resultado: 0 chunks para ambas as fontes (gap herdado do 22.4).

### Correção (mesmo padrão do `s3-2017-postmortem.md`)

Dois arquivos curados com conteúdo factual verificável, citando URLs oficiais como
provenance:

- `db/curated/uber-schemaless-mysql.md` — caso **Schemaless** (datastore escalável baseado
  em MySQL) e a migração Postgres→MySQL. Fontes:
  <https://www.uber.com/blog/schemaless-part-one-mysql-datastore/> e
  <https://www.uber.com/blog/postgres-to-mysql-migration/>.
- `db/curated/gitlab-2017-db-postmortem.md` — postmortem do database outage de
  31/01/2017 (comando destrutivo contra o PostgreSQL primário). Fonte:
  <https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/>.

Registrados como `local_files` nas entradas `uber-engineering` e `gitlab-incidents` de
`src/cip/ingestion/sources_advanced.yaml` (case-studies), com `urls: []` (o fetch remoto
é inviável; a provenance canónica fica no campo `url` do `local_files`).

### Re-ingestão + prova

```
$ podman exec cip-api python -m cip.ingestion.ingest --scope mvp
# ingestion_complete: ingested_chunks=473, skipped=201, batches_done=83, batches_failed=0
# ingest_local_files: uber-engineering n_local=1; gitlab-incidents n_local=1
```

Query no Postgres (`data_cloud_docs` por URL canónica):

| fonte | chunks antes | chunks depois | min_len/avg_len |
|---|---|---|---|
| uber (schemaless) | 0 | **18** | 123 / 480 chars |
| gitlab (postmortem 2017) | 0 | **18** | 128 / 380 chars |

**Antes: 0 + 0 = 0 chunks → Depois: 18 + 18 = 36 chunks** com conteúdo substantivo
(não thin).

---

## ✅ PASSO 3 — Robustez do gate: `--runs N` por maioria (implementado)

### Motivação

O único 9/10 histórico do gate veio de variância pontual do LLM (temp 0.1) numa menção
omitida. Um gate single-run é sensível a esse falso-negativo.

### Implementação (`scripts/homolog_validate.py`)

- Novo argumento `--runs N` (default `1` — **comportamento single-run intacto**).
- Nova `_majority_result(runs)` consolida N execuções de UM caso numa decisão por
  **MAIORIA** (`passed = n_pass >= ceil(N/2)`). Para `N == 1` retorna o run único sem
  qualquer alteração (sem mudança no path default).
- O resultado agregado expõe a união de conceitos encontrados através dos runs
  (visibilidade), latência média e custo somado; `passed` é a única decisão de gate.
- Docstring atualizado (Uso + lista de melhorias Round 22.6).

### Prova (smoke)

```
$ python scripts/homolog_validate.py --area azure --runs 2
run1/2=PASS(acc=5.00) run2/2=PASS(acc=5.00) => PASS (maioria) acc=5.00
```

---

## ✅ PASSO 4 — Regressão

```
$ podman exec cip-api sh -lc "IS_TESTING=1 pytest -q --ignore=test_smoke_ask --ignore=test_ingest_delta"
8 failed, 587 passed, 19 skipped, 4 warnings in 263.64s
```

**Sem regressão**: os 8 failures são os MESMOS pré-existentes do Round 22.5 (nenhum novo):

| Teste | Classificação |
|---|---|
| test_inspection_rules.py::test_detects_prod_rds_without_multi_az | PRE-EXISTING (regra T4 RDS Multi-AZ) |
| test_mock_cloud_cli.py::test_subcommand_status_runs | PRE-EXISTING (cip_cli status retorna 2) |
| test_tools_cache.py::test_azure_tools_degrade_gracefully | PRE-EXISTING (falta AZURE creds) |
| test_web_ui.py::TestJavaScriptStructure (5) | PRE-EXISTING drift (app.js do shell Web) |

Os testes que cobrem os arquivos alterados (`test_specialists.py`,
`test_knowledge_expansion.py`, `test_round22_knowledge_areas.py`) seguem passando.

Homolog full 2x:

- Run 1 = **10/10** (az-001 acc 5.00)
- Run 2 = **10/10** (az-001 acc 5.00)

---

## 📁 Artefatos alterados

| Arquivo | Mudança |
|---|---|
| `src/cip/prompts/specialists.py` | prompt `AZURE`: enumeração obrigatória dos 6 pilares do WAF |
| `db/curated/uber-schemaless-mysql.md` | NOVO — caso Schemaless curado (provenance oficial) |
| `db/curated/gitlab-2017-db-postmortem.md` | NOVO — postmortem GitLab 2017 curado (provenance oficial) |
| `src/cip/ingestion/sources_advanced.yaml` | `local_files` em uber-engineering e gitlab-incidents |
| `scripts/homolog_validate.py` | `--runs N` por maioria; `_majority_result`; docstring |

---

## 🎯 Gaps para review (KIRO)

1. Os 8 failures residuais de teste (web_ui JS structure, azure tools creds, `cip_cli`
   status, regra T4) permanecem fora do escopo deste round — continuam documentados como
   pré-existentes.
2. O modo `--runs N` está disponível mas o gate CI ainda usa 1 run por default; decidir
   se o pipeline passa a usar `--runs 3` como politican.
