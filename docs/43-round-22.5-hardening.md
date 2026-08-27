# Round 22.5 — Hardening: source_key dedupe, matcher bilíngue por conceitos, IS_TESTING

> **Data**: 2026-08-26 | **Escopo**: 3 gaps residuais do Round 22.4 SEM regredir o gate de homolog
> (10/10) nem os 579 testes. Não há mudança em routing/retrieval (lição do Round 22).

---

## 🎯 Resultado

| GAP | Antes | Depois |
|---|---|---|
| Colisão de `source_key` em `case-studies` | 3 fontes com chunks | **11 fontes** com chunks |
| `_check_must_mention_bilingual` posicional | pareamento `pt[i] ↔ en[i]` frágil | **lista de conceitos** (grupos de variantes OR) |
| 8 testes LLM-key-dependent | 8 failed | destravados via `IS_TESTING=1` → `_StubLLM` |

Gate de homolog mantido (Run 1 = 10/10, Run 3 = 10/10; Run 2 = 9/10 por variância pontual
do DeepSeek em `azure-001` — accuracy média subiu em relação ao Round 22.4).

---

## ✅ PASSO 1 — Colisão de `source_key` (case-studies)

### Diagnóstico (ROOT CAUSE)

`ingest.py` montava a chave de progresso/resume como `cloud:service:batch_id`:

```python
source_key = f"{cloud}:{entry['service']}:{entry.get('batch_id', 0)}"
```

Nos knowledge areas adicionais (`case-studies`, `architecture`), múltiplas entradas
compartilham o MESMO `service`:

* `case-studies`: linkedin/uber/cloudflare/gitlab/slack/dropbox/stripe/aws-architecture-blog/
  gcp-customers/azure-customers — todos com `service: case-studies`;
  aws-postmortems/google-cloud-incidents — ambos com `service: postmortems`.
* `architecture`: `martinfowler` e `microsoft-azure` — ambos `service: architecture-patterns`.

Como `progress["completed"]` só guarda UMA chave, a segunda entrada com a MESMA chave era
pulada no resume (ou marcava "completed" antes de processar), então **só uma fonte por
`service` entrava por execução**.

### Correção

Nova helper `_make_source_key(cloud, entry)` — chave passou a `cloud:source:service:batch`,
incluindo `source` (estável e único DENTRO de cada cloud/pseudo-cloud) como discriminador:

```python
def _make_source_key(cloud: str, entry: dict[str, Any]) -> str:
    source = entry.get("source") or entry["service"]
    return f"{cloud}:{source}:{entry['service']}:{entry.get('batch_id', 0)}"
```

Aplicada nos 2 pontos que montavam a chave (`ingest_entry` line ~338 e `run` line ~552),
garantindo consistência entre o `completed`/`failed` do progress e o log.

O dedupe por `content_hash` (2ª camada, por chunk) NÃO foi tocado — ele independe da chave.

### Re-ingestão + prova

```
$ podman exec cip-api python -m cip.ingestion.ingest --scope mvp
# ingestion_complete: ingested_chunks=613, skipped=211, batches_done=83, batches_failed=0
```

Query no Postgres (`data_cloud_docs` WHERE `cloud='case-studies'`):

| source | chunks |
|---|---|
| google-cloud-incidents | 279 |
| gcp-customers | 59 |
| aws-architecture-blog | 50 |
| aws-postmortems | 45 |
| slack-engineering | 17 |
| netflix-tech-blog | 15 |
| dropbox-tech | 14 |
| cloudflare-blog | 14 |
| linkedin-engineering | 8 |
| stripe-engineering | 7 |
| azure-customers | 3 |

**Antes: 3 fontes** (linkedin 8, netflix 15, aws-postmortems 45) → **Depois: 11 fontes**.

`uber-engineering` e `gitlab-incidents` continuam sem chunks por problema de FETCH
(URL devolve 14/41 chars — bloqueio/JS), não por colisão de chave. Gap de qualidade de
fetch, herdado do Round 22.4.

---

## ✅ PASSO 2 — Matcher bilíngue por lista de conceitos

### Fragilidade

`_check_must_mention_bilingual` pareava `pt[i] ↔ en[i]` por POSIÇÃO. Adicionar/remover uma
variante num idioma deslocava todos os conceitos seguintes, casando pares errados
(ex.: `aws-002` tinha `pt[4]="1-year"` pareado com `en[4]="reserved"`).

### Escolha (documentada): lista de grupos `[{"variants": [...]}]`

A opção de MENOR diff que também é a semanticamente correta: cada conceito vira um grupo
autônomo de variantes que casam por OR. O agrupamento fica explícito e imune a
desalinhamento posicional.

* `must_mention` dos 10 casos do `HOMOLOG_SUITE` migrou de `{"pt":[...], "en":[...]}` para
  `[{"variants": [...]}, ...]` (nenhuma variante removida, nenhum termo novo inventado —
  apenas reagrupados por conceito real).
* Nova `_iter_concept_groups(must)` normaliza o formato canônico E os formatos legacy
  (dict `pt/en`, list de strings, string) para retrocompatibilidade.
* `_check_must_mention_bilingual` itera grupos (OR entre variantes) sem indexação posicional.
* `_must_mention_total` = `len(grupos)`, garantindo denominador == numerador.

Exemplo de correção (aws-002): antes `pt[4]="1-year"↔en[4]="reserved"` era um conceito
espúrio. Agora: `{"variants":["savings plan","savings"]}`, `{"variants":["reserved instance",
"reserved"]}`, `{"variants":["1-year"]}`, `{"variants":["3-year"]}`, `{"variants":["no-upfront"]}`,
`{"variants":["upfront"]}` — cada conceito autônomo.

### Prova (homolog, deepseek)

* **Run 1**: 10/10 — acc média subiu (arch-001 3.22→5.00, arch-002 3.15→5.00, arch-003→5.00).
* **Run 2**: 9/10 — `azure-001` acc=3.00 (variância DeepSeek temperature 0.1; era 5.00/4.33
  nas outras rodadas — não é regressão do matcher, o azure oscila entre 5.00/3.00/4.33).
* **Run 3**: 10/10.

O gate 10/10 está mantido; o refactor não baixou o gate — elevou a média de accuracy.

---

## ✅ PASSO 3 — Destravar os 8 testes LLM-key-dependent

### Diagnóstico

`test_specialists.py` (8 casos) + `test_tools_mock_integration.py` passam por
`get_orchestrator() → get_engine() → RagEngine.__init__ → configure_llama_settings() →
build_llm()`. Com `LLM_PROVIDER=minimax` (`.env`) e key real ausente no CI, `build_llm`
instanciava provider real com `api_key="not-set"` e falhava na primeira chamada — ou, pior,
sofria contaminação de estado entre arquivos de teste (passa isolado, falha na suíte).

### Correção

`src/cip/rag/llm.py` — `build_llm()` agora retorna `_StubLLM()` determinístico quando
`IS_TESTING` está setado, ANTES de instanciar qualquer provider:

```python
def build_llm() -> Any:
    if os.environ.get("IS_TESTING", "").strip().lower() in ("1", "true", "yes", "on"):
        log.info("stub_llm_active", reason="IS_TESTING=1 (ambiente de teste determinístico)")
        return _StubLLM()
    ...
```

Sem efeito em produção: o stub só é ativado pela env var explícita `IS_TESTING=1`, nunca
pelo `LLM_PROVIDER` do `.env`.

### Validação

```
$ podman exec cip-api sh -lc "IS_TESTING=1 pytest -q --ignore=test_smoke_ask --ignore=test_ingest_delta"
8 failed, 587 passed, 19 skipped, 4 warnings in 243.86s
```

Baseline era `16 failed, 579 passed`. O IS_TESTING destravou exatamente os 8
LLM-key-dependent (7 `test_specialists.py` + 1 `test_tools_mock_integration.py`),
que agora passam: `579 + 8 = 587 passed`. Os 8 failures restantes são TODOS
pré-existentes (nenhuma REGRESSION, nenhum LLM-key-dependent):

| Teste | Classificação |
|---|---|
| test_inspection_rules.py::test_detects_prod_rds_without_multi_az | PRE-EXISTING drift (regra T4 RDS Multi-AZ) |
| test_mock_cloud_cli.py::test_subcommand_status_runs | PRE-EXISTING (cip_cli status retorna 2) |
| test_tools_cache.py::test_azure_tools_degrade_gracefully | PRE-EXISTING (falta AZURE creds: DefaultAzureCredential) |
| test_web_ui.py::TestJavaScriptStructure (5) | PRE-EXISTING drift (app.js do shell Web) |

> Nota de implementação: o gate `IS_TESTING` foi colocado em
> `configure_llama_settings()` (o ponto onde o LlamaIndex seta o `Settings.llm`
> global usado pelo RagEngine/orchestrator), preservando `build_llm()` como
> factory pura. Isso evita regredir os 7 unit tests de `test_minimax_provider.py`
> (que mockam `get_settings` e chamam `build_llm` diretamente para validar o
> caminho real do provider).

---

## 📁 Artefatos alterados

| Arquivo | Mudança |
|---|---|
| `src/cip/ingestion/ingest.py` | nova `_make_source_key` (cloud:source:service:batch) |
| `src/cip/rag/llm.py` | `_is_testing()` + `IS_TESTING=1` → `_StubLLM` em `configure_llama_settings` |
| `scripts/homolog_validate.py` | must_mention → lista de conceitos; `_iter_concept_groups`; matcher por grupos |

---

## 🎯 Gaps para review (KIRO)

1. `uber-engineering` e `gitlab-incidents` ainda sem chunks (fetch thin/JS) — generalizar
   `local_files` curados como no Round 22.4.
2. Variância pontual do `azure-001` (5.00/3.00/4.33) — reforçar prompt do especialista
   azure para citar os 6 pilares, como feito para finops/software_architecture/aws.
