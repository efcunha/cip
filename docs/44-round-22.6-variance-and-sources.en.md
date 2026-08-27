# Round 22.6 — Eliminating azure-001 variance and curating uber/gitlab

> **Date**: 2026-08-26 | **Scope**: 3 residual gaps from Round 22.5 WITHOUT regressing the
> homolog gate (10/10) nor the 587 tests. No change to routing/retrieval — `router.py` and
> `_resolve_cloud_from_area` were NOT touched (lesson from Round 22).

---

## 🎯 Result

| GAP | Before | After |
|---|---|---|
| `azure-001` variance (5.00/3.00/4.33) | oscillated due to omitted pillars | **3/3 runs acc=5.00** (prompt enumerates the 6 pillars) |
| `uber-engineering` with no chunks | 0 chunks (thin/JS fetch) | **18 chunks** (curated Schemaless) |
| `gitlab-incidents` with no chunks | 0 chunks (thin/JS fetch) | **18 chunks** (curated 2017 postmortem) |
| False-negative from temp variance | single-run gate | **`--runs N` by majority** (default 1 intact) |

- Full homolog: Run 1 = **10/10**, Run 2 = **10/10** (stable; no 9/10 like Round 22.5).
- Regression: **587 passed / 8 failed / 19 skipped** — identical to baseline (no regression).

---

## ✅ STEP 1 — Eliminate azure-001 variance

### Diagnosis (ROOT CAUSE)

`homolog-azure-001` asks "What are the pillars of the Azure Well-Architected Framework?". The
rubric requires 6 concepts: `reliability`, `security`, `cost optimization`,
`operational excellence`, `performance efficiency` + `sustainability`. The `azure` specialist
(in `src/cip/prompts/specialists.py`) described the WAF as "(5 pillars + Sustainability)"
WITHOUT instructing explicit enumeration, so the LLM (DeepSeek, temp 0.1) sometimes omitted
the *Sustainability* pillar — acc oscillated 5.00/3.00/4.33.

### Fix

`AZURE` in `src/cip/prompts/specialists.py` now instructs to **ALWAYS** explicitly enumerate,
one by one, ALL the WAF pillars, citing the terms in English:

1. Reliability (Confiabilidade)
2. Security (Segurança)
3. Cost Optimization (Otimização de Custos)
4. Operational Excellence (Excelência Operacional)
5. Performance Efficiency (Eficiência de Performance)
6. Sustainability (Sustentabilidade) — cross-cutting pillar

> These are the official pillars of the Microsoft Azure Well-Architected Framework
> (<https://learn.microsoft.com/en-us/azure/well-architected/>) — no invented pillars.

### Proof (homolog azure, deepseek, 3 runs)

| Run | acc azure-001 | gate |
|---|---|---|
| 1 | 5.00 | PASS |
| 2 | 5.00 | PASS |
| 3 | 5.00 | PASS |

Goal (acc ≥ 4.0 on 3/3 runs) met comfortably: **5.00 on every run**.

---

## ✅ STEP 2 — Curate uber and gitlab (thin/JS fetch)

### Diagnosis

`uber-engineering` (`https://www.uber.com/blog/engineering/`) and `gitlab-incidents`
(`https://about.gitlab.com/handbook/engineering/postmortems/`) are SPA/JS-blocked for the
`SimpleWebPageReader` fetcher — they returned 14/41 chars (thin), discarded by
`MIN_CONTENT_CHARS`. Result: 0 chunks for both sources (gap inherited from 22.4).

### Fix (same pattern as `s3-2017-postmortem.md`)

Two curated files with verifiable factual content, citing official URLs as provenance:

- `db/curated/uber-schemaless-mysql.md` — the **Schemaless** case (scalable datastore based on
  MySQL) and the Postgres→MySQL migration. Sources:
  <https://www.uber.com/blog/schemaless-part-one-mysql-datastore/> and
  <https://www.uber.com/blog/postgres-to-mysql-migration/>.
- `db/curated/gitlab-2017-db-postmortem.md` — postmortem of the database outage of
  01/31/2017 (destructive command against the primary PostgreSQL). Source:
  <https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/>.

Registered as `local_files` in the `uber-engineering` and `gitlab-incidents` entries of
`src/cip/ingestion/sources_advanced.yaml` (case-studies), with `urls: []` (remote fetch is
infeasible; the canonical provenance lives in the `url` field of the `local_files`).

### Re-ingestion + proof

```
$ podman exec cip-api python -m cip.ingestion.ingest --scope mvp
# ingestion_complete: ingested_chunks=473, skipped=201, batches_done=83, batches_failed=0
# ingest_local_files: uber-engineering n_local=1; gitlab-incidents n_local=1
```

Query in Postgres (`data_cloud_docs` by canonical URL):

| source | chunks before | chunks after | min_len/avg_len |
|---|---|---|---|
| uber (schemaless) | 0 | **18** | 123 / 480 chars |
| gitlab (postmortem 2017) | 0 | **18** | 128 / 380 chars |

**Before: 0 + 0 = 0 chunks → After: 18 + 18 = 36 chunks** with substantive (non-thin)
content.

---

## ✅ STEP 3 — Gate robustness: `--runs N` by majority (implemented)

### Motivation

The only historical 9/10 on the gate came from one-off LLM variance (temp 0.1) in an omitted
mention. A single-run gate is sensitive to that false-negative.

### Implementation (`scripts/homolog_validate.py`)

- New `--runs N` argument (default `1` — **single-run behavior intact**).
- New `_majority_result(runs)` consolidates N executions of ONE case into a **MAJORITY**
  decision (`passed = n_pass >= ceil(N/2)`). For `N == 1` it returns the single run with no
  change whatsoever (no change to the default path).
- The aggregated result exposes the union of concepts found across the runs (visibility),
  average latency, and summed cost; `passed` is the only gate decision.
- Docstring updated (Usage + Round 22.6 improvements list).

### Proof (smoke)

```
$ python scripts/homolog_validate.py --area azure --runs 2
run1/2=PASS(acc=5.00) run2/2=PASS(acc=5.00) => PASS (maioria) acc=5.00
```

---

## ✅ STEP 4 — Regression

```
$ podman exec cip-api sh -lc "IS_TESTING=1 pytest -q --ignore=test_smoke_ask --ignore=test_ingest_delta"
8 failed, 587 passed, 19 skipped, 4 warnings in 263.64s
```

**No regression**: the 8 failures are the SAME pre-existing ones from Round 22.5 (no new):

| Test | Classification |
|---|---|
| test_inspection_rules.py::test_detects_prod_rds_without_multi_az | PRE-EXISTING (rule T4 RDS Multi-AZ) |
| test_mock_cloud_cli.py::test_subcommand_status_runs | PRE-EXISTING (cip_cli status returns 2) |
| test_tools_cache.py::test_azure_tools_degrade_gracefully | PRE-EXISTING (missing AZURE creds) |
| test_web_ui.py::TestJavaScriptStructure (5) | PRE-EXISTING drift (Web shell app.js) |

The tests covering the changed files (`test_specialists.py`, `test_knowledge_expansion.py`,
`test_round22_knowledge_areas.py`) keep passing.

Full homolog 2x:

- Run 1 = **10/10** (az-001 acc 5.00)
- Run 2 = **10/10** (az-001 acc 5.00)

---

## 📁 Changed artifacts

| File | Change |
|---|---|
| `src/cip/prompts/specialists.py` | `AZURE` prompt: mandatory enumeration of the 6 WAF pillars |
| `db/curated/uber-schemaless-mysql.md` | NEW — curated Schemaless case (official provenance) |
| `db/curated/gitlab-2017-db-postmortem.md` | NEW — curated GitLab 2017 postmortem (official provenance) |
| `src/cip/ingestion/sources_advanced.yaml` | `local_files` in uber-engineering and gitlab-incidents |
| `scripts/homolog_validate.py` | `--runs N` by majority; `_majority_result`; docstring |

---

## 🎯 Gaps for review (KIRO)

1. The 8 residual test failures (web_ui JS structure, azure tools creds, `cip_cli` status,
   rule T4) remain out of scope for this round — still documented as pre-existing.
2. The `--runs N` mode is available but the CI gate still uses 1 run by default; decide
   whether the pipeline should switch to `--runs 3` as policy.
