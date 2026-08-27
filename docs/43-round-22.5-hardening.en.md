# Round 22.5 — Hardening: source_key dedupe, bilingual matcher by concepts, IS_TESTING

> **Date**: 2026-08-26 | **Scope**: 3 residual gaps from Round 22.4 WITHOUT regressing the homolog gate
> (10/10) nor the 579 tests. No change in routing/retrieval (the Round 22 lesson).

---

## 🎯 Result

| GAP | Before | After |
|---|---|---|
| `source_key` collision in `case-studies` | 3 sources with chunks | **11 sources** with chunks |
| Positional `_check_must_mention_bilingual` | fragile `pt[i] ↔ en[i]` pairing | **concept list** (groups of OR variants) |
| 8 LLM-key-dependent tests | 8 failed | unblocked via `IS_TESTING=1` → `_StubLLM` |

The homolog gate was maintained (Run 1 = 10/10, Run 3 = 10/10; Run 2 = 9/10 due to a one-off
DeepSeek variance in `azure-001` — average accuracy rose relative to Round 22.4).

---

## ✅ STEP 1 — `source_key` collision (case-studies)

### Diagnosis (ROOT CAUSE)

`ingest.py` built the progress/resume key as `cloud:service:batch_id`:

```python
source_key = f"{cloud}:{entry['service']}:{entry.get('batch_id', 0)}"
```

In the additional knowledge areas (`case-studies`, `architecture`), multiple entries
share the SAME `service`:

* `case-studies`: linkedin/uber/cloudflare/gitlab/slack/dropbox/stripe/aws-architecture-blog/
  gcp-customers/azure-customers — all with `service: case-studies`;
  aws-postmortems/google-cloud-incidents — both with `service: postmortems`.
* `architecture`: `martinfowler` and `microsoft-azure` — both `service: architecture-patterns`.

Since `progress["completed"]` only stores ONE key, the second entry with the SAME key was
skipped on resume (or marked "completed" before processing), so **only one source per
`service` entered per run**.

### Fix

New helper `_make_source_key(cloud, entry)` — the key became `cloud:source:service:batch`,
including `source` (stable and unique WITHIN each cloud/pseudo-cloud) as the discriminator:

```python
def _make_source_key(cloud: str, entry: dict[str, Any]) -> str:
    source = entry.get("source") or entry["service"]
    return f"{cloud}:{source}:{entry['service']}:{entry.get('batch_id', 0)}"
```

Applied at the 2 points that built the key (`ingest_entry` line ~338 and `run` line ~552),
ensuring consistency between the progress `completed`/`failed` and the log.

The `content_hash` dedup (2nd layer, per chunk) was NOT touched — it is independent of the key.

### Re-ingestion + proof

```
$ podman exec cip-api python -m cip.ingestion.ingest --scope mvp
# ingestion_complete: ingested_chunks=613, skipped=211, batches_done=83, batches_failed=0
```

Postgres query (`data_cloud_docs` WHERE `cloud='case-studies'`):

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

**Before: 3 sources** (linkedin 8, netflix 15, aws-postmortems 45) → **After: 11 sources**.

`uber-engineering` and `gitlab-incidents` remain without chunks due to a FETCH problem
(URL returns 14/41 chars — blocking/JS), not a key collision. A fetch-quality gap,
inherited from Round 22.4.

---

## ✅ STEP 2 — Bilingual matcher by concept list

### Fragility

`_check_must_mention_bilingual` paired `pt[i] ↔ en[i]` by POSITION. Adding/removing a
variant in one language shifted all subsequent concepts, matching wrong pairs
(e.g.: `aws-002` had `pt[4]="1-year"` paired with `en[4]="reserved"`).

### Choice (documented): list of `[{"variants": [...]}]` groups

The MINIMAL-diff option that is also the semantically correct one: each concept becomes an
autonomous group of variants that match by OR. The grouping becomes explicit and immune to
positional misalignment.

* The 10 cases' `must_mention` in `HOMOLOG_SUITE` migrated from `{"pt":[...], "en":[...]}` to
  `[{"variants": [...]}, ...]` (no variant removed, no new term invented —
  only regrouped by real concept).
* New `_iter_concept_groups(must)` normalizes the canonical format AND the legacy formats
  (dict `pt/en`, list of strings, string) for backward compatibility.
* `_check_must_mention_bilingual` iterates groups (OR between variants) without positional indexing.
* `_must_mention_total` = `len(groups)`, ensuring denominator == numerator.

Example fix (aws-002): before `pt[4]="1-year"↔en[4]="reserved"` was a spurious concept.
Now: `{"variants":["savings plan","savings"]}`, `{"variants":["reserved instance",
"reserved"]}`, `{"variants":["1-year"]}`, `{"variants":["3-year"]}`, `{"variants":["no-upfront"]}`,
`{"variants":["upfront"]}` — each an autonomous concept.

### Proof (homolog, deepseek)

* **Run 1**: 10/10 — average acc rose (arch-001 3.22→5.00, arch-002 3.15→5.00, arch-003→5.00).
* **Run 2**: 9/10 — `azure-001` acc=3.00 (DeepSeek temperature 0.1 variance; it was 5.00/4.33
  in the other rounds — not a matcher regression; azure oscillates between 5.00/3.00/4.33).
* **Run 3**: 10/10.

The 10/10 gate is maintained; the refactor did not lower the gate — it raised the average accuracy.

---

## ✅ STEP 3 — Unblock the 8 LLM-key-dependent tests

### Diagnosis

`test_specialists.py` (8 cases) + `test_tools_mock_integration.py` pass through
`get_orchestrator() → get_engine() → RagEngine.__init__ → configure_llama_settings() →
build_llm()`. With `LLM_PROVIDER=minimax` (`.env`) and no real key in CI, `build_llm`
instantiated a real provider with `api_key="not-set"` and failed on the first call — or, worse,
suffered state contamination between test files (passes in isolation, fails in the suite).

### Fix

`src/cip/rag/llm.py` — `build_llm()` now returns a deterministic `_StubLLM()` when
`IS_TESTING` is set, BEFORE instantiating any provider:

```python
def build_llm() -> Any:
    if os.environ.get("IS_TESTING", "").strip().lower() in ("1", "true", "yes", "on"):
        log.info("stub_llm_active", reason="IS_TESTING=1 (deterministic test environment)")
        return _StubLLM()
    ...
```

No effect in production: the stub is only activated by the explicit env var `IS_TESTING=1`, never
by the `LLM_PROVIDER` from `.env`.

### Validation

```
$ podman exec cip-api sh -lc "IS_TESTING=1 pytest -q --ignore=test_smoke_ask --ignore=test_ingest_delta"
8 failed, 587 passed, 19 skipped, 4 warnings in 243.86s
```

The baseline was `16 failed, 579 passed`. IS_TESTING unblocked exactly the 8
LLM-key-dependent (7 `test_specialists.py` + 1 `test_tools_mock_integration.py`),
which now pass: `579 + 8 = 587 passed`. The 8 remaining failures are ALL
pre-existing (no REGRESSION, no LLM-key-dependent):

| Test | Classification |
|---|---|
| test_inspection_rules.py::test_detects_prod_rds_without_multi_az | PRE-EXISTING drift (rule T4 RDS Multi-AZ) |
| test_mock_cloud_cli.py::test_subcommand_status_runs | PRE-EXISTING (cip_cli status returns 2) |
| test_tools_cache.py::test_azure_tools_degrade_gracefully | PRE-EXISTING (missing AZURE creds: DefaultAzureCredential) |
| test_web_ui.py::TestJavaScriptStructure (5) | PRE-EXISTING drift (Web shell app.js) |

> Implementation note: the `IS_TESTING` gate was placed in
> `configure_llama_settings()` (the point where LlamaIndex sets the global
> `Settings.llm` used by the RagEngine/orchestrator), preserving `build_llm()` as a
> pure factory. This avoids regressing the 7 unit tests of `test_minimax_provider.py`
> (which mock `get_settings` and call `build_llm` directly to validate the real
> provider path).

---

## 📁 Changed artifacts

| File | Change |
|---|---|
| `src/cip/ingestion/ingest.py` | new `_make_source_key` (cloud:source:service:batch) |
| `src/cip/rag/llm.py` | `_is_testing()` + `IS_TESTING=1` → `_StubLLM` in `configure_llama_settings` |
| `scripts/homolog_validate.py` | must_mention → concept list; `_iter_concept_groups`; group-based matcher |

---

## 🎯 Gaps for review (KIRO)

1. `uber-engineering` and `gitlab-incidents` still without chunks (thin/JS fetch) — generalize
   curated `local_files` as in Round 22.4.
2. One-off `azure-001` variance (5.00/3.00/4.33) — reinforce the azure specialist prompt to
   cite the 6 pillars, like done for finops/software_architecture/aws.
