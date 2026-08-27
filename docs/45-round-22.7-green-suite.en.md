# Round 22.7 — Green suite: zero out the 8 pre-existing tests

> **Date**: 2026-08-26 | **Scope**: zero out the 8 tests that had been failing since Round
> 22.4 WITHOUT regressing the homolog gate (10/10) nor the 587 passing. Without touching
> `router.py` nor `_resolve_cloud_from_area` (constraint inherited from Round 22).

---

## 🎯 Result

| Metric | Before | After |
|---|---|---|
| Tests | 8 failed / 587 passed | **0 failed / 595 passed** |
| Full homolog run 1 | 10/10 (baseline) | **10/10** (acc 5.00 on all) |
| Full homolog run 2 | 10/10 (baseline) | **10/10** (acc 5.00 on all) |

All 8 failures were **pre-existing** (documented in Round 22.6 as out of scope). No
regression introduced — the 587 passing rose to 595 (the 8 that failed now pass).

---

## ✅ STEP 1 — Diagnosis of the 8

`IS_TESTING=1 pytest -q --ignore=test_smoke_ask --ignore=test_ingest_delta -rf` → 8 failed:

| Test | Root cause (ROOT CAUSE) |
|---|---|
| `test_web_ui.py::TestJavaScriptStructure` (5) | `web/app.js` was legitimately refactored in Round 22 (multi-turn chat, SSE, feedback, sidebar). The assertions reference old function names that no longer exist. |
| `test_tools_cache.py::test_azure_tools_degrade_gracefully` (1) | `AzureAdvisorTools.__init__` called `DefaultAzureCredential()` which **throws in __init__** when there are no credentials (dev/CI) — it did not degrade. |
| `test_mock_cloud_cli.py::test_subcommand_status_runs` (1) | `cmd_status` called the **async** `run_all_checks()` WITHOUT `await/asyncio.run()` → returned a coroutine → `AttributeError` → exit 2. |
| `test_inspection_rules.py::test_detects_prod_rds_without_multi_az` (1) | hcl2 returns `tags` as a **dict with quoted values** (`{"Environment": '"prod"'}`); the rule did not strip the quotes, so `env` never matched `prod`. |

---

## ✅ STEP 2 — web_ui (5 tests), factually outdated assertions

### Diagnosis

`web/app.js` (Round 22+) evolved and **got richer** — the functionality the assertions
guarded is still present, under new names:

| Old assertion | Reality in current app.js |
|---|---|
| `async function callAnalyzeStream` | removed — consolidated into multi-turn chat (`sendConversationMessage`, `createConversation`, `listConversations`) |
| `consumeSSE` | renamed → `parseSSE` |
| `function addMessage` | renamed → `appendMessage` (+ `addUserMessage`/`appendAssistantMessage`) |
| `function addStreamingMessage` | renamed → `appendStreamingAssistant` |
| ` ``` ` (fenced code blocks) | `formatAnswer()` uses `**`→`<strong>` and `` ` ``→`<code>`; fenced blocks removed |
| `finding`/`severity`/`recommendation` | concept migrated to Inspection Engine (backend) + `.finding` CSS; the client now renders metadata (grounding/latency) + feedback |

### Fix (adjustment of the **test**, not of web/)

The JS is correct and richer — I updated the assertions to reflect the real structure, while
keeping the INTENT of coverage (API client, SSE streaming, UI, markdown, metadata):

- `test_js_has_api_client_functions` → checks `callHealth`/`callAsk`/`callAskStream` + the
  multi-turn conversation functions
  (`sendConversationMessage`/`createConversation`/`listConversations`).
- `test_js_has_streaming_support` → `parseSSE` + `event:`/`data:` + `chunk`/`done` events.
- `test_js_has_ui_functions` → `setStatus`/`appendMessage`/`appendStreamingAssistant`/`sendMessage`/`formatAnswer`.
- `test_js_handles_markdown` → `**`→`<strong>` and `` ` ``→`<code>` (real rendering).
- `test_js_handles_findings` → real metadata (`has_grounding`/`sources_count`/`latency_ms`) +
  `feedback` + `.finding` in `style.css`.

> Justification: factually outdated assertion, NOT loosened — each new line corresponds to
> real code in the current `app.js`/`style.css`.

---

## ✅ STEP 3 — Azure creds + cip_cli status + RDS Multi-AZ

### Azure tools creds (`azure_advisor.py`)

`DefaultAzureCredential()` raises `ValueError` in `__init__` when the credential env vars are
empty. I wrapped the credential construction in `try/except`: without credentials,
`self.advisor = None` and a warning is logged; the `get_*_recommendations()` methods return
`[]` and `summarize()` returns the friendly message — **graceful degradation** instead of an
exception.

### cip_cli status (`scripts/cip_cli.py`)

`cmd_status` called `run_all_checks()` (async, awaits DB connections directly) without await.
I added `import asyncio` + `asyncio.run(run_all_checks())` (outside an event loop, correct).
Result: `status` now prints the 4 checks and returns 0 (HEALTHY).

### RDS Multi-AZ (`terraform.py`)

The T4/T7 rule compared `env` against `{"prod","production","prd"}`, but hcl2 returns
`tags={"Environment": '"prod"'}` (value **with literal quotes**). I normalized it via `_unq`
(which already does `strip('"')`) before `.lower()` → detection of prod RDS without Multi-AZ
works again (finding `high`/`reliability`).

---

## ✅ STEP 4 — Full regression

```
$ podman exec cip-api sh -lc "IS_TESTING=1 pytest -q --ignore=test_smoke_ask --ignore=test_ingest_delta"
595 passed, 19 skipped, 4 warnings in 257.18s
```

**0 failed** — the 8 were zeroed and the previous 587 preserved.

Full homolog 2x (real LLM MiniMax M3):

- Run 1 = **10/10** (acc 5.00 on all cases)
- Run 2 = **10/10** (acc 5.00 on all cases)

> Between the runs, the upstream MiniMax gateway went through a transient window of
> `502 Bad Gateway`/`503 Service Temporarily Unavailable` (nginx). I identified two
> robustness points in `homolog_validate.py` and fixed them (see STEP 4b below). After the
> upstream recovered, Run 2 closed clean at 10/10.

Report re-synced with the final round: `eval/results/homolog_report.md` +
`eval/results/homolog_results.json` (provider `minimax`, 10/10, acc 5.00, grounding 10/10, 0
errors).

---

## ✅ STEP 4b — Homolog robustness against transient upstream errors

During Run 2, the last 3 cases (`arch-004`, `cases-001`, `cases-002`) failed with
`InternalServerError: 502/503` from the MiniMax nginx gateway — that was **not** a quality
regression (mention acc remained 5.0 on healthy runs). Two points were fixed in
`scripts/homolog_validate.py`:

1. **Transient retry** — `TRANSIENT_ERRORS` in `_build_orchestrator_sync_runner` did not
   recognize `InternalServerError`/`502 Bad Gateway`/`503 Service Temporarily Unavailable`.
   With those tokens added, the retry (2x with backoff) now covers the upstream 502/503.
2. **`StatisticsError` in the partial report** — `render_report()` and the JSON `summary`
   computed `statistics.mean([... if not r.error])` without guarding the empty list; when the
   FIRST case errored (all with `error`), `statistics.mean([])` raised `StatisticsError` and
   knocked down `_write_partial_report`. They now use `if [r for r in results if not r.error]
   else 0`.

---

## ✅ STEP 5 — CI gate decision (`--runs`)

- The `ci-eval` (Makefile) and the CI job `eval-gate` run `run_eval.py --offline --strict` —
  eval **offline/deterministic** (Inspection Engine, no LLM). `--runs N` makes no sense there
  (no temperature variance).
- The gate with variance is the homolog with a real LLM (`homolog_validate.py`). I applied
  `--runs 3` to the `homolog-real` Makefile target (by majority, reduces false-negatives),
  keeping `ci-eval` without `--runs` (deterministic).

### Diff (Makefile)

```diff
-homolog-real:  ## Homolog end-to-end com LLM real (LLM_PROVIDER=minimax padrao)
+homolog-real:  ## Homolog ... (LLM_PROVIDER=minimax padrao, --runs 3 por maioria)
- python scripts/homolog_validate.py --strict
+ python scripts/homolog_validate.py --strict --runs 3
```

> `--runs 3` was implemented on the homolog gate (where variance matters), not on the offline
> `ci-eval`. No `--runs` in offline CI — documented above.

---

## 📁 Changed artifacts

| File | Change |
|---|---|
| `src/cip/tools/azure_advisor.py` | graceful degradation without credentials (`advisor=None`, `[]` guard) |
| `scripts/cip_cli.py` | `cmd_status` uses `asyncio.run(run_all_checks())` |
| `src/cip/inspection/terraform.py` | RDS Multi-AZ rule normalizes tags via `_unq` |
| `tests/test_web_ui.py` | 5 assertions updated to the real `app.js` structure |
| `scripts/homolog_validate.py` | 502/503 transient retry + `StatisticsError` guard |
| `Makefile` | `homolog-real` with `--runs 3`; comment in `ci-eval` |
| `eval/results/homolog_report.md` + `.json` | re-synced with the final round |

---

## 🎯 Gaps for review (KIRO)

1. The 3 `RuntimeWarning: coroutine ... never awaited` warnings in `test_react.py` are
   pre-existing (out of this scope) — future await-fix opportunities.
2. The RDS Multi-AZ rule label oscillates between "T4" (code/test) and "T7" (catalog
   docstring in `terraform.py`) — a cosmetic inconsistency to normalize.
3. `ci-eval` (offline) remains without `--runs`; `homolog-real` now uses `--runs 3` —
   confirm whether the release pipeline should also adopt `--runs 3` on homolog.
