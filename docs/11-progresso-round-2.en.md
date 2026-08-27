# Round 2 Progress — Phase 1B Complete + Phase 2 Started

> **Date**: 2026-08-24 | **Round**: 2/30 | **Status**: PHASE 1B ✅ 100% + PHASE 2 (5/9 items)

---

## 🎯 Round Result

**Phase 1B (Ingestion Hardening) was 100% completed** with a critical bug discovered/fixed in the drift detector. **Phase 2 (Live Tools) was started** with TTL cache + tool expansion + 14 passing tests.

---

## ✅ Concrete Deliverables

### Phase 1B — Ingestion Hardening

| Task | Status |
|---|---|
| 1B.1 — Idempotency validated (MVP re-run → 0 duplicates) | ✅ |
| 1B.2 — Monthly cron + drift detection (`scripts/monthly_reingest.py`) | ✅ |
| 1B.3 — Critical bug fixed: baseline uses the majority hash (mode) per URL | ✅ |
| 1B.4 — Drift detector validated with simulated change | ✅ |
| 1B.5 — Idempotency confirmed in DB (237 chunks, 0 new insertions on 2nd run) | ✅ |

### Phase 2 — Live Tools (5/9 items)

| Task | Status |
|---|---|
| 2.1 — TTL cache implemented (`cip/tools/cache.py`) | ✅ |
| 2.2 — `@cached(ttl=3600)` applied to AWS/Azure/GCP tools | ✅ |
| 2.3 — Tools expanded (Security/HA/IAM/EIPs/Idle) | ✅ |
| 2.4 — 14 tests created and passing (TTLCache + @cached + integration) | ✅ |
| 2.5 — AWS `summarize()` improved: Top 3 services + idle EIPs | ✅ |
| 2.6 — Real AWS/Azure/GCP credentials in sandbox | ⏳ Pending (no creds) |
| 2.7 — Read-only IAM setup validated on real accounts | ⏳ Pending |
| 2.8 — Cache tested with real load (Cost Explorer rate limit) | ⏳ Pending |
| 2.9 — Tool metrics (latency, hit rate) | ⏳ Pending |

---

## 📂 Files Created/Modified

| File | Lines | Change |
|---|---|---|
| `scripts/monthly_reingest.py` | ~210 | **NEW** — Monthly cron + drift detection |
| `scripts/test_inject_drift.py` | ~50 | **NEW** — Drift test helper |
| `scripts/test_drift_real.py` | ~70 | **NEW** — Real validation of the drift detector |
| `scripts/debug_drift.py` | ~40 | **NEW** — Baseline debug |
| `src/cip/tools/cache.py` | ~95 | **NEW** — TTLCache + @cached decorator |
| `src/cip/tools/aws_cost.py` | +30 | Cache + `list_unused_elastic_ips()` + Top 3 |
| `src/cip/tools/azure_advisor.py` | +50 | Cache + Security/HA recommendations |
| `src/cip/tools/gcp_recommender.py` | +20 | Cache + IAM recommendations |
| `tests/test_tools_cache.py` | ~190 | **NEW** — 14 tests (100% passing) |
| `docs/11-progresso-round-2.md` | (this file) | Round report |

---

## 🧪 Validation Evidence

### 1. Idempotency
```
python -m cip.ingestion.ingest --scope mvp  # 2nd execution
→ ingest_all_unchanged aws (7 unchanged)
→ ingest_all_unchanged gcp (6 unchanged)
→ ingest_all_unchanged azure (7 unchanged)
→ Total: 20 unchanged, 0 duplicate chunks ✅
```

### 2. Drift Detector — Majority Baseline
```
Before the fix: GROUP BY url, dh → multiple hashes per URL
After: ROW_NUMBER() OVER (PARTITION BY url ORDER BY count DESC) WHERE rn=1 → 1 hash (mode)
→ Validation: 1 modified detected on a simulated change ✅
```

### 3. TTL Cache — 14 Tests
```
$ pytest tests/test_tools_cache.py -v
============================= 14 passed in 5.21s ==============================
✅ TTLCache: hit/miss/TTL expiry/invalidate/stats
✅ @cached decorator: cache/different args/TTL/kwargs
✅ Cloud Tools: AWS/Azure/GCP degrade gracefully
✅ Thread safety: 10 threads × 100 ops (no errors)
```

---

## 🐛 Critical Bug Discovered and Fixed

**Symptom**: Drift detector initially reported `changes=20` even without real changes.

**Root cause**: `GROUP BY url, dh` returned multiple hashes per URL (duplicate chunks within a page, navigation, repeated headers). The resulting dict picked an arbitrary hash (depending on order), not the true "main content".

**Fix**: use `ROW_NUMBER() OVER (PARTITION BY url ORDER BY count DESC) WHERE rn=1` to pick the majority hash (mode) per URL. This reflects the main content.

**Impact**: Without the fix, the detector could:
- False positive: report drift when there is none
- False negative: miss real drift if the correct hash happened to match the baseline

**Validated**: real drift (simulated change) is now detected correctly.

---

## 🛣️ Next Steps (Round 3+)

### Short term (next 2-3 rounds)
1. **Phase 2 — complete live tools**:
   - Configure sandbox credentials (AWS, Azure, GCP) for integrated tests
   - Validate real Cost Explorer / Advisor / Recommender calls
   - Add tool metrics (latency, cache hit rate)
2. **Phase 3 — Inspection Engine**:
   - Implement 7 Terraform rules (public resources, encryption, oversized)
   - Implement 7 Kubernetes rules (privileged, missing limits, hostNetwork)
   - Severity + estimated $ impact
3. **Phase 4 — Advanced specialists**:
   - Add 3 new specialists (aws_specialist, gcp_specialist, azure_specialist)
   - Intelligent routing (1-3 per query)
   - ReAct/function-calling mode

### Medium term (rounds 4-8)
4. **Phase 5 — Quality gate**:
   - Expand eval suite to 60 real scenarios (20/cloud)
   - Automated 1-5 rubric + human review

5. **Phase 6 — Production hardening**:
   - API key auth
   - Tenant isolation
   - Langfuse tracing
   - CI/CD < 5min
   - Staging → production deploy

---

## 📊 Multi-Week Objective Progress

```
Phases:
[███████████░] Phase 1A — Functional MVP (100%) ✅
[███████████░] Phase 1B — Hardening (100%) ✅
[█████████░░░] Phase 2 — Live Tools (55%)
[░░░░░░░░░░░] Phase 3 — Inspection Engine (0%)
[░░░░░░░░░░░] Phase 4 — Specialists (0%)
[░░░░░░░░░░░] Phase 5 — Quality Gate (0%)
[░░░░░░░░░░░] Phase 6 — Production Hardening (0%)
[░░░░░░░░░░░] Phase 7 — Fine-tuning (0%, optional)
```

**Total: ~22% of the multi-week objective completed.**

---

## 🎯 Current Status vs. Original Goal

```
Goal: Operationalize CIP as a non-generic specialist LLM for AWS, GCP and Azure
Status: 22% (2 complete phases + 1 partial phase)

Complete components:
- Database: operational pgvector, 237 MVP chunks, validated idempotency
- RAG: tested retrieval, 100% grounding, p95 latency = 1.9s
- Idempotency: validated (delta detection)
- Drift detection: implemented and validated
- Cloud tools: structure + cache + graceful degradation

Pending components:
- Live tools with real credentials (sandbox)
- Inspection Engine (TF + K8s)
- Advanced specialists (multi-specialist, ReAct)
- Quality gate (eval ≥ 4.0)
- Production hardening (auth, CI/CD, deploy)
```

**Goal `goal-e029f7ac-67b4-4801-b89b-bd5e614e7d42` remains ACTIVE** for round 3.
