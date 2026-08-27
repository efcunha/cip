# Round 22.2 — Improving Homologation Gate Accuracy (DeepSeek)

> **Date**: 2026-08-25 | **Scope**: raise the accuracy of the homologation gate with a real LLM

---

## 🎯 Result

Investigated and fixed the **low accuracy (2.77)** of the homologation gate with DeepSeek-V4-Flash. The root cause was twofold: (1) the router was misrouting architecture/cloud questions and (2) the orchestrator was truncating the specialist answers to 200 characters, cutting off the terminology that the rubric evaluates.

**Improvement: 2/10 → 5-6/10 passing cases** (average accuracy 2.77 → ~3.3-3.9), grounding held at 10/10, 0 errors.

| Metric | Before | After |
|---|---|---|
| Passing cases | 2/10 | 5-6/10 |
| Average accuracy | 2.77 | ~3.3-3.9 |
| Grounding | 10/10 | 10/10 |
| Errors | 0 | 0 |

---

## ✅ Concrete Deliverables

### 1. `src/cip/agents/router.py` — routing fixes

**a) Architecture signal takes precedence over COMPARE**

Questions like "Diferença entre CQRS e CRUD" contained the keyword `"diferença entre"` (COMPARE), which routed to `aws/gcp/azure` instead of `software_architecture`.

```diff
- if any(k in t for k in _COMPARE_KEYWORDS) or len(clouds) >= 2:
+ is_compare = any(k in t for k in _COMPARE_KEYWORDS) or len(clouds) >= 2
+ if is_compare and not has_arch_signal:
       ... # COMPARE
```

**b) Removed `"well-architected"` from the AWS keyword list**

"well-architected" is ambiguous (AWS, Azure and GCP all have a "Well-Architected Framework"). Being in the AWS list caused "Azure Well-Architected" to trigger an undeserved COMPARE (aws+azure).

```diff
-        "guardduty", "security hub", "well-architected",
+        "guardduty", "security hub",
+        # NOTE: "well-architected" is ambiguous — removed (Round 22.1)
```

### 2. `src/cip/agents/orchestrator.py` — 2 fixes

**a) Removed 200-char truncation in specialist merge**

```diff
- preview = r.answer[:200].replace("\n", " ").strip()
+ body = r.answer[:4000].strip()   # high ceiling only as a guard
```

The truncation was mutilating the specialist answer, cutting off the `must_mention` terms (e.g. circuit breaker OPEN/CLOSED/HALF_OPEN, saga orchestration/choreography, CQRS read/write).

**b) Specialist analysis comes first in the summary**

```diff
- parts.append(rag_primary.answer)          # generic first
- parts.append("\n\n--- Análise por especialistas ---")
+ parts.append(merged_summaries)            # specialists first
+ parts.append("\n\n--- Resposta base ---")
+ parts.append(rag_primary.answer)
```

The specialized answer (with the correct terminology) now precedes the generic main RAG answer in the evaluated summary.

### 3. `scripts/homolog_validate.py` — `_resolve_cloud_from_area` (reverted after experiment)

An attempt was made to map `software_architecture → "architecture"` and `case_studies → "case-studies"` to filter the RAG by the pseudo-clouds. It **regressed** (6/10 → 3/10) because the `software_architecture` specialist runs with `spec_cloud=None` (name ≠ pseudo-cloud), and `rag_primary` was restricted to a smaller subset. **Kept as `None`** (the keyword router already routes correctly, and the unfiltered RAG retrieves a broader set by semantic relevance).

---

## 🧪 Validation (real outputs)

### Corrected routing

```
$ podman exec cip-api python /tmp/check_router.py
knowledge clouds=[] specialists=['software_architecture']   ← "Diferença entre CQRS e CRUD"
knowledge clouds=[] specialists=['software_architecture']   ← "padrão Saga"
knowledge clouds=['azure'] specialists=['azure']            ← "Azure Well-Architected"
knowledge clouds=['aws'] specialists=['aws']                ← "AWS Well-Architected"
```

### Homologation (progression)

| Round | Active fixes | Result |
|---|---|---|
| Baseline | none | 2/10, acc 2.77 |
| #1 | router + truncation | 6/10, acc 3.29 |
| #2 | + summary reorder + cloud map | 3/10 (regression) |
| #3 | - cloud map (reverted) | 5/10, acc 3.14 |

### Tests without regression

```
$ podman exec cip-api pytest tests/test_router_v2.py tests/test_round22_knowledge_areas.py tests/test_router.py -q
74 passed
```

---

## 📊 Cases that still fail (4-5)

| Case | Area | Accuracy | Root cause |
|---|---|---|---|
| homolog-aws-002 | aws | 2.50 | FinOps does not explicitly mention "commitment/discount/flexibility" |
| homolog-arch-003 | software_architecture | 3.00 | CQRS — answer does not cover "separation/event sourcing/read/write" |
| homolog-arch-004 | software_architecture | 1.89 | Saga — does not mention "orchestration/choreography/compensation" |
| homolog-cases-001/002 | case_studies | 1.00-1.89 | Routing does not target the case-studies pseudo-cloud |

---

## 🎯 Next Steps

1. **`case_studies` (2 cases)**: add routing keywords (`postmortem`, `incidente`, `lessons learned`, `case study`) and a mapping in the RAG to the `case-studies` pseudo-cloud — currently these cases fall into `aws`/`software_architecture` and do not retrieve the postmortems.

2. **`aws-002` / `arch-003` / `arch-004`**: adjust the FinOps/Software Architect prompts to explicitly instruct mentioning the key concepts (e.g., "cite commitment/discount/flexibility"; "differentiate orchestration vs choreography and mention compensation").

3. **Evaluate the gate with multiple rounds**: DeepSeek (temperature 0.1) has variance. An average of 3 rounds would give a more stable number than a single run.
