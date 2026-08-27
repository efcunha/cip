# Round 22.8 — Catalog cleanup: normalize T1..T7 numbering + zero out RuntimeWarnings in test_react.py

> **Date**: 2026-08-26 | **Scope**: cosmetic cleanup — normalize the numbering of the
> terraform rules catalog and eliminate the 3 `RuntimeWarning: coroutine never awaited` in
> `test_react.py`. WITHOUT lowering the gate (10/10) nor regressing the suite (590 passing).
> Without touching `router.py` nor `_resolve_cloud_from_area`; without changing the
> detection LOGIC of any inspection rule (only labels/docstrings/test names).

---

## 🎯 Result

| Metric | Before | After |
|---|---|---|
| Tests | 590 passed / 0 failed | **590 passed / 0 failed** (19 skipped) |
| RuntimeWarning (test_react.py) | 3 (`_tool_query_rag._q` ×2 + `Orchestrator.handle`) | **0** |
| Full homolog 1x (real LLM minimax) | 10/10 (baseline) | **10/10** |
| Terraform catalog numbering | docstring diverged from code/test | **consistent** (T4=Multi-AZ, T7=prevent_destroy) |

---

## ✅ STEP 1 — Normalize terraform catalog numbering

### Diagnosis

The catalog docstring (top of `src/cip/inspection/terraform.py`) claimed:

- `T4 - S3 bucket with public ACL/access (block_public_acls = false)`
- `T7 - RDS without Multi-AZ in a production environment`

… but the **inline code** and the **tests** implemented/used:

- `T4 — RDS without Multi-AZ in production` (line 204 of the module; `TestTerraformRuleT4_RDSNoMultiAZ`)
- `T7 — No lifecycle/prevent_destroy` (line 316 of the module; `TestTerraformRuleT7_NoPreventDestroy`)

That is, the docstring was **desynchronized** from the implementation. This was recorded as a
gap in Round 22.7 (gap #2): *"The RDS Multi-AZ rule label oscillates between 'T4'
(code/test) and 'T7' (catalog docstring in terraform.py)"*.

### BEFORE mapping (rule → number)

| # | Docstring (top) | Inline comment | Test class |
|---|---|---|---|
| T1 | S3 without SSE | S3 without SSE | `T1_S3NoEncryption` |
| T2 | SG ingress 0.0.0.0/0 | SG ingress 0.0.0.0/0 | `T2_SecurityGroupPublic` |
| T3 | RDS without storage_encrypted | RDS without storage_encrypted | `T3_RDSNoEncryption` |
| **T4** | **S3 public ACL** ❌ | **RDS without Multi-AZ** | **`T4_RDSNoMultiAZ`** |
| T5 | Compute without tags | Compute without tags | `T5_NoTags` |
| T6 | Oversized instance | Oversized instance | `T6_OversizedInstance` |
| **T7** | **RDS without Multi-AZ** ❌ | **no prevent_destroy** | **`T7_NoPreventDestroy`** |
| extra | remote backend (OPERATIONS) | remote backend (EXTRA) | — |

Real divergences: **T4** and **T7** (3 sources did not agree). The others (T1/T2/T3/T5/T6)
were already aligned.

### AFTER mapping (rule → number)

I chose the convention that **changes tests the least** — that of the code/test (Multi-AZ=T4,
prevent_destroy=T7) — and aligned **only the catalog docstring**:

| # | Domain | Rule | Source |
|---|---|---|---|
| T1 | Security | S3 without server-side encryption | docstring ✅ + inline ✅ + test ✅ |
| T2 | Security | SG ingress 0.0.0.0/0 | ✅ ✅ ✅ |
| T3 | Security | RDS without storage_encrypted | ✅ ✅ ✅ |
| **T4** | **Security** | **RDS without Multi-AZ in production** | **docstring ✅** + inline ✅ + test ✅ |
| T5 | FinOps | Compute without tags/labels | ✅ ✅ ✅ |
| T6 | FinOps | Oversized instance | ✅ ✅ ✅ |
| **T7** | **Operations** | **Critical resource without prevent_destroy** | **docstring ✅** + inline ✅ + test ✅ |
| extra | Reliability | Terraform without remote backend | docstring ✅ + inline ✅ |

> Note: the "extra" has no number (it is a global rule outside the resource loop). The old
> docstring put it under "OPERATIONS" while the inline comment marked it as "EXTRA"; I
> unified it as "RELIABILITY — (extra)". No behavior change.

### Diff (catalog docstring)

```diff
 SEGURANÇA:
   T1 - S3 sem server-side encryption
   T2 - Security Group ingress 0.0.0.0/0
   T3 - RDS sem storage_encrypted
-  T4 - S3 bucket com public ACL/access (block_public_acls = false)
+  T4 - RDS sem Multi-AZ em ambiente de produção
 
 FINOPS:
   T5 - Recurso de compute sem tags/labels (governança/custo)
   T6 - Instância oversized (m5/m4/c5 families sem justification para tamanho)
 
-RELIABILITY:
-  T7 - RDS sem Multi-AZ em ambiente de produção
-
 OPERATIONS:
+  T7 - Recurso crítico sem lifecycle/prevent_destroy
+
+RELIABILITY:
   (extra) - Terraform sem backend remoto de state (state local)
```

No detection changed — only the catalog text (docstring) and the regrouping of categories
(which already matched the real `domain=` of each Finding).

---

## ✅ STEP 2 — Zero out the 3 RuntimeWarning coroutine-never-awaited

### Diagnosis (ROOT CAUSE)

`src/cip/agents/react.py` called `asyncio.run(<coroutine>)` **inside an event loop already
running** (the ReAct `run()` loop, async). `asyncio.run()` cannot be called from a running
loop; when attempted, the coroutine passed as an argument **is never scheduled** and the GC
emits `RuntimeWarning: coroutine ... was never awaited`.

It affected three points:

1. `_tool_query_rag` — `asyncio.run(_q())` → leaked `_tool_query_rag.<locals>._q`.
2. `_tool_invoke_specialist` — `asyncio.run(_q())` → same `_q` coroutine.
3. `_fallback_to_static` — `asyncio.run(static_orch.handle(...))` → leaked `Orchestrator.handle`.

Beyond the warning, this was a **latent production bug**: the `query_rag`/`invoke_specialist`
and the static fallback **never actually ran** when ReAct executed under an async loop (the
normal path via `await orch.handle(react_mode=True)`).

### Fix (without changing the detection contract)

- `_execute_tool` → `async def`; awaits `_tool_query_rag`/`_tool_invoke_specialist`; the
  synchronous tools (`_tool_get_live_data`, `_tool_inspect_iac`) remain synchronous.
- `_tool_query_rag` / `_tool_invoke_specialist` → `async def`; await `self._engine.query(...)`
  directly (no `asyncio.run`, no internal `_q` coroutine). They now use `self._engine`
  (injectable/mockable) instead of the `get_engine()` singleton — consistent with
  `_fallback_to_static`, which already used `self._engine`. In production `self._engine`
  defaults to `get_engine()`, so the **behavior is identical**.
- `_fallback_to_static` → `async def`; `await static_orch.handle(...)` directly.
- `run()` → `await self._execute_tool(...)` (2 calls) and `await self._fallback_to_static(...)` (2 calls).

### Test adjustment (async contract)

`tests/test_react.py` had 3 synchronous calls that now need await:

- `test_unknown_tool_returns_message` → `await orch._execute_tool(...)` + `async def`.
- `test_query_rag_calls_engine` → `await orch._tool_query_rag(...)` + `async def`.
- `test_invoke_specialist_uses_prompt` → `await orch._tool_invoke_specialist(...)` + `async def`.

All three were already `@pytest.mark.asyncio` (or gained the mark), so the change is purely
mechanical await plumbing, without loosening any assertion.

### Beneficial side effect

By using `self._engine` (the mock injected in the loop tests) instead of the real
`get_engine()`, the loop tests stopped instantiating the `PGVectorStore`/psycopg3 pool —
also eliminating the `RuntimeWarning: coroutine 'Connection._cancel' was never awaited`
(async pool teardown of psycopg3) that emerged when the real engine was touched, and reducing
the `test_react.py` time from ~18s to ~3s.

---

## ✅ STEP 3 — Validation

### Main suite

```
$ podman exec cip-api sh -lc "IS_TESTING=1 python -m pytest -q \
    --ignore=tests/test_smoke_ask.py --ignore=tests/test_ingest_delta.py"
590 passed, 19 skipped, 1 warning in 277.51s
```

- **0 failed** (590/590).
- Sole warning: `PytestRemovedIn10Warning` (class-scoped fixture deprecation in
  `test_mock_cloud_cli.py`) — **pre-existing**, not a RuntimeWarning, out of scope.

### test_react.py isolated (with `-W error::RuntimeWarning`)

```
$ podman exec cip-api sh -lc "IS_TESTING=1 python -m pytest tests/test_react.py -W error::RuntimeWarning -q"
19 passed in 2.96s        # 0 warnings
```

Before the fix: `19 passed, 7 warnings` (RuntimeWarning of coroutine never awaited).

### Full homolog 1x (real LLM MiniMax M3)

`python scripts/homolog_validate.py --strict` (without `IS_TESTING=1`, provider `minimax`)
→ **10/10**, acc 5.00 on all cases.

> ⚠️ Process diagnosis: a first attempt with `IS_TESTING=1` dropped the homolog to 0/10
> because `IS_TESTING=1` forces `_StubLLM` (deterministic) in place of the real MiniMax — the
> stub does not generate the `must_mention`, so the acc collapses. Re-run **without**
> `IS_TESTING=1`, it closed at 10/10. The `eval/results/homolog_report.md`/`.json` report was
> re-synced with the real round (10/10). No code change was needed for the gate.

---

## 📁 Changed artifacts

| File | Change |
|---|---|
| `src/cip/inspection/terraform.py` | catalog docstring normalized (T4=Multi-AZ, T7=prevent_destroy + categories) |
| `src/cip/agents/react.py` | async tools/fallback (no `asyncio.run`); `self._engine` instead of `get_engine()` |
| `tests/test_react.py` | 3 tests adjusted to the async contract of the tools |
| `eval/results/homolog_report.md` + `.json` | re-synced with the real 10/10 round (minimax) |
| `docs/46-round-22.8-catalog-cleanup.md` | this document |

---

## 🎯 Gaps for review (KIRO)

1. The `PytestRemovedIn10Warning` (class-scoped fixture as instance method in
   `test_mock_cloud_cli.py`) remains open — pytest 10 deprecation, out of the cosmetic scope
   of this round.
2. The `_tool_get_live_data`/`_tool_inspect_iac` tools remain **synchronous** inside a now
   async `_execute_tool` — if they ever gain async I/O they will need to become async too
   (today they are CPU-bound, so this is correct).
3. The "extra" remote-backend of the terraform catalog still has no number (T8?) — decide
   whether it is worth numbering it to close the catalog at 8 explicit rules.
