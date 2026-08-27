# Round 26 — Finalization of CIP integration in CloudPilot (Mode B primary)

> **Date**: 2026-08-26 | **Scope**: make **Mode B (HTTP)** the PRIMARY RAG path of the CloudPilot
> agent, document the mandatory rule (steering + ADR) and persist the network in compose. Does NOT
> deploy. Does NOT change CIP's `router.py` / `_resolve_cloud_from_area`. Does NOT change
> RAG/embedding logic. Does NOT delete `cip_client.py` (kept as the facade's internal fallback).
> NO push. NO committing `.env`/tokens.
>
> **Respected prohibition**: `router.py` / `_resolve_cloud_from_area` untouched; RAG/embedding
> logic untouched; `cip_client.py` preserved as fallback; no `.env`/token committed.

---

## 🎯 Result

| Metric | Value (measured) |
|---|---|
| Swapped import in the agent | `tools.py`: `cip_client.consult_official_cloud_knowledge` → `cip_http_client.consult_official_cloud_knowledge` |
| `is_http_mode_enabled()` in backend process | **True** (Mode B active) |
| Effective env vars (settings) | `CIP_MASTER_KILL=False`, `CIP_RAG_ENABLED=True`, `CIP_API_URL=http://cip-api:8000`, token set |
| Round-trip via real agent (`ToolExecutor`) | `STATUS=ok`, `GROUNDING=True`, `SOURCES=8`, `ANSWER_LEN=1703`, `REFUSAL=None` |
| CIP dev suite | **590 passed, 19 skipped, 0 failed** |
| CloudPilot `/health` | `{"status":"healthy","database":"ok","redis":"ok"}` |

---

## ✅ STEP 1 — Plug Mode B into the agent (1 import)

In `backend/app/services/ai/tools.py`, method `_consult_official_cloud_knowledge`:

```diff
-        from app.services.ai import cip_audit, cip_metrics
-        from app.services.ai.cip_client import CipMasterKill, consult_official_cloud_knowledge
+        from app.services.ai import cip_audit, cip_metrics
+        from app.services.ai.cip_client import CipMasterKill
+        from app.services.ai.cip_http_client import consult_official_cloud_knowledge
```

- `CipMasterKill` stays imported from `cip_client` (it is the **exception class**, not the function).
- `consult_official_cloud_knowledge` now comes from `cip_http_client` (facade that routes
  Mode B↔A automatically).
- Method docstring updated to reflect Mode B as the primary path.

**Other-import verification**: grep in `backend/app/**` for
`cip_client.consult_official_cloud_knowledge` / `cip_client import` / `cip_http_client import`
found **only**:

- `tools.py` (fixed above);
- `cip_http_client.py` lines 4/219/223/239 — the correct internal fallback (Mode A);
- `tests/` (not touched — they test `cip_client` in-process directly).

There was no other RAG entry point in production. The SINGLE entry point is now the HTTP facade.

---

## ✅ STEP 2 — Restart + round-trip via real agent

```
$ podman restart cloudpilot_backend
$ # wait for healthy (~11 polls x 2s)
```

Confirmation of HTTP mode + effective env vars in the Python process (via `settings`, not
`os.environ`):

```
$ podman exec cloudpilot_backend python -c "from app.services.ai import cip_http_client; ..."
http_mode_enabled: True
CIP_API_URL: 'http://cip-api:8000'
TOKEN_SET: True
MASTER_KILL: False
RAG_ENABLED: True
```

Round-trip exercised by the **real agent** (not isolated script):

```
$ podman exec cloudpilot_backend python -c "
import asyncio
from app.services.ai.tools import ToolExecutor
exe = ToolExecutor(workspace_id='00000000-0000-4000-8000-000000000001', db_session=None, grant_validator=None, single_use_ledger=None)
r = asyncio.run(exe._consult_official_cloud_knowledge(question='Como reduzir custo de EC2 com Savings Plans?', cloud='aws'))
print('STATUS:', r.get('status'))
print('GROUNDING:', r.get('has_grounding'))
print('SOURCES:', len(r.get('sources',[])))
print('ANSWER_LEN:', len(r.get('answer','')))
print('REFUSAL:', r.get('refusal_reason'))
"
STATUS: ok
GROUNDING: True
SOURCES: 8
ANSWER_LEN: 1703
REFUSAL: None
```

**Goal achieved**: STATUS=ok, GROUNDING=True, SOURCES=8, ANSWER_LEN>0, REFUSAL=None.

---

## ✅ STEP 3 — Document the mandatory rule (steering + ADR)

- **Steering**: `.github/instructions/cip-llm-rag-mandatory.instructions.md` — rule that every
  module needing LLM/RAG consumes it via `cip_http_client.consult_official_cloud_knowledge`;
  prohibits direct LLM, pgvector outside `services/ai/cip_*` and direct import of
  `cip_client.consult_official_cloud_knowledge`.
- **ADR**: `docs/ADR/adr-006-cip-mandatory.md` — recorded decision (Accepted): CIP is the
  mandatory LLM/RAG provider, consumed via HTTP (primary) with in-process fallback; context +
  consequences + rollback.

---

## ✅ STEP 4 — Persist the network in CloudPilot's compose

New override `docker-compose.cip.yml` (the main `docker-compose.yml` is managed and stayed
intact):

```yaml
networks:
  cip_default:
    external: true
    name: cip_default

services:
  backend:
    networks:
      - cloudpilot_net
      - cip_default
  celery_worker:
    networks:
      - cloudpilot_net
      - cip_default
```

**Documented ASSUMPTION**: the network to persist is `cip_default` — the "native" CIP network
(created by compose in `D:\cip`, already `external: true`), where `cip-api` already is natively.
By attaching `backend` + `celery_worker` to it, the manual `podman network connect` is no longer
needed. The `cloudpilot-deploy_cloudpilot_net` network (where `cip-api` was manually connected in
Round 25) stays as it is; the override declares the CIP network as an additional dependency and
recreates nothing.

> Syntax validation: `podman compose config` fails on this host (see BLOCKED below), so the YAML
> was validated with PyYAML (`yaml.safe_load` on `docker-compose.yml` +
> `docker-compose.override.yml` + `docker-compose.cip.yml` → "YAML OK").

---

## ✅ STEP 5 — Validation without regression

**CIP**:

```
$ podman exec cip-api sh -lc "IS_TESTING=1 python -m pytest -q --ignore=tests/test_smoke_ask.py --ignore=tests/test_ingest_delta.py"
590 passed, 19 skipped, 1 warning in 211.65s
```

**CloudPilot**:

```
$ podman exec cloudpilot_backend curl -sf http://localhost:8000/health
{"status":"healthy","version":"0.1.0","environment":"development","checks":{"database":"ok","redis":"ok"},"budget_sync":{"status":"unknown","last_run_at":null,"age_seconds":null},"infisical_kms":{"status":"degraded"}}
```

Round-trip (STEP 2) re-executed and **stays green** (STATUS=ok, GROUNDING=True, SOURCES=8,
ANSWER_LEN=1703, REFUSAL=None).

---

## 📁 Changed artifacts

| File | Change |
|---|---|
| `backend/app/services/ai/tools.py` | swapped import: `cip_client.consult_official_cloud_knowledge` → `cip_http_client.consult_official_cloud_knowledge` (+ docstring) |
| `.github/instructions/cip-llm-rag-mandatory.instructions.md` | new — steering of the mandatory rule |
| `docs/ADR/adr-006-cip-mandatory.md` | new — ADR of the decision |
| `docker-compose.cip.yml` | new — override declaring `cip_default` external and attaching backend/celery to it |
| `docs/52-round-26-cip-finalization.md` | new — this document (in `D:\cip\docs`) |

> No CIP file (`D:\cip`) was changed beyond the doc. No commit performed. No `.env`/token
> committed or pasted with real value.

---

## BLOCKED (honestly recorded)

`podman compose config` **does not run on this Windows host** — `get machine connection URI: could
not find a matching machine for connection "ssh://root@127.0.0.1:57498/..."` (same limitation as
Rounds 24/25). Override syntax validation was done via PyYAML. The override is applicable on any
host where compose works; current round-trip viability uses the already-existing network
connection (`cip-api` on `cloudpilot-deploy_cloudpilot_net` + the new override declared for the
future).

---

## 🎯 Gaps for review (KIRO)

1. **Auth in production**: `cip_http_client` sends `Authorization: Bearer`, CIP authenticates via
   `X-API-Key`. In `CIP_ENV=dev` CIP waives it (works); in production the header needs alignment.
2. **grant_validator=None in the test**: the round-trip via `ToolExecutor` uses
   `grant_validator=None`/`single_use_ledger=None` (direct test path), not the full
   stream_response executor with capability grants.
3. **Network override not exercised**: `docker-compose.cip.yml` was validated by YAML, not by
   `podman compose up` (compose broken on this host). Needs a host with working compose to
   confirm the automatic `cip_default` attach.
4. **In-process fallback still exists**: until Mode A is retired, the duplicated `cip_cloud_docs`
   table remains as a divergence risk (tracked in `CIP_INTEGRATION.md`).
