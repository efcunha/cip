# Round 25 — CloudPilot→CIP HTTP Integration (Mode B) end-to-end

> **Date**: 2026-08-26 | **Scope**: wire the CloudPilot→CIP HTTP integration **locally** and prove
> the `POST /consult` round-trip end-to-end via the `cip_http_client.py` facade. Does NOT deploy.
> Does NOT change RAG/routing logic. Does NOT delete Mode A (in-process) — only enables Mode B
> (HTTP) via config. NO push. NO committing `.env`/secrets.
>
> **Respected prohibition**: CIP's `router.py` / `_resolve_cloud_from_area` untouched; RAG logic
> untouched; CloudPilot Mode A preserved (`consult_official_cloud_knowledge` keeps in-process
> fallback).

---

## 🎯 Result

| Metric | Value (measured) |
|---|---|
| Connected network | `cip-api` added to `cloudpilot-deploy_cloudpilot_net` |
| DNS resolution (client→server) | `cloudpilot_backend` → `cip-api` = `10.89.0.145` |
| `CIP_ENV` of `cip-api` container | `dev` (auth waived) |
| Direct `/consult` (via CloudPilot network) | **HTTP 200**, `has_grounding=true`, `sources=8` |
| Round-trip via facade (Mode B) | `HTTP_MODE=True`, `GROUNDING=True`, `SOURCES=8`, `ANSWER_LEN=1338`, `REFUSAL=None` |
| `cloudpilot_backend` health | `/health` → `{"status":"healthy","database":"ok","redis":"ok"}` |

---

## ✅ STEP 1 — Connect the networks

`cip-api` was on the `cip_default` network (with Postgres); `cloudpilot_backend` on
`cloudpilot-deploy_cloudpilot_net`. Since CIP is the **server** and CloudPilot is the **client**,
the client only needed to resolve the server. The chosen option was to connect the server
(`cip-api`) to the client's network:

```
$ podman network connect cloudpilot-deploy_cloudpilot_net cip-api
EXIT=0
```

Resolution proof (from the client):

```
$ podman exec cloudpilot_backend python -c "import socket; print(socket.gethostbyname('cip-api'))"
cip-api -> 10.89.0.145
```

---

## ✅ STEP 2 — Check `CIP_ENV` and auth

```
$ podman exec cip-api sh -lc 'echo CIP_ENV=$CIP_ENV; echo CIP_API_KEYS=${CIP_API_KEYS:-<unset>}'
CIP_ENV=dev
CIP_API_KEYS=<unset>
```

`CIP_ENV=dev` → the `/consult` endpoint **waives auth** (accepts requests without `X-API-Key`). It
was not necessary to set `CIP_API_KEYS`.

> **ASSUMPTION**: the container was already in `CIP_ENV=dev` (local environment, not real
> production), so CloudPilot's token can be a placeholder string `dev-integration-token`. No auth
> reconfiguration was needed.

---

## ✅ STEP 3 — Test direct `/consult` (without CloudPilot)

Proof that the endpoint responds, from a container on the CloudPilot network
(`cloudpilot_backend` was crash-looping at this stage — see ROOT CAUSE below — so the direct test
used `cip-api` locally + `cloudpilot_adminer` via network):

```
# inside cip-api (localhost):
$ podman exec cip-api python -c "import httpx; r=httpx.post('http://localhost:8000/consult', json={'question':'O que é o AWS Well-Architected Framework?','cloud':'aws'}, headers={'X-Tenant-Id':'test'}, timeout=120); j=r.json(); print(r.status_code, j.get('has_grounding'), len(j.get('sources',[])))"
STATUS 200
HAS_GROUNDING True
N_SOURCES 8

# via CloudPilot network (cloudpilot_adminer → cip-api):
$ podman exec cloudpilot_adminer sh -lc 'curl -s -o /tmp/resp.json -w "HTTP_STATUS=%{http_code}\n" -m 120 -X POST http://cip-api:8000/consult ...'
HTTP_STATUS=200
"has_grounding":true
```

**Goal achieved**: status 200, `has_grounding=True`, `sources > 0` (8).

---

## 🐛 ROOT CAUSE (pre-existing) — `cloudpilot_backend` crash-looping

Before the facade round-trip worked, `cloudpilot_backend` was **crash-looping**
(`Up 1 second (starting)`) — pre-existing, not caused by this round. Two-layer cause:

1. **Postgres outside the client's network**: the `cloudpilot_postgres` container was only on
   `cip_default` + `podman`, not on `cloudpilot-deploy_cloudpilot_net`. The backend tries
   `postgres:5432` and got `Connection refused`.

   → **Fix (additive)**: `podman network connect --alias postgres cloudpilot-deploy_cloudpilot_net cloudpilot_postgres`.

2. **Nonexistent CloudPilot databases/roles**: the `cloudpilot_postgres` container is, in fact,
   **CIP's Postgres** (inherited/misleading name — already documented in Round 24). It was
   initialized with `POSTGRES_USER/PASSWORD/DB=cip` and does **not** have the `cloudpilot` nor
   `infisical` databases, nor the `cloudpilot`/`cloudpilot_app` roles. CloudPilot's `init_db.sql`
   never ran on this server.

   → **Fix (additive, non-destructive — the `cip` database remained intact)**:
   ```
   CREATE ROLE cloudpilot      WITH LOGIN PASSWORD 'cloudpilot' SUPERUSER;
   CREATE ROLE cloudpilot_app  WITH LOGIN PASSWORD 'cloudpilot';
   CREATE DATABASE cloudpilot OWNER cloudpilot;
   CREATE DATABASE infisical  OWNER cloudpilot;
   GRANT ALL ON DATABASE cloudpilot TO cloudpilot_app;
   ```

   The backend then completed migrations (→ `092`) and came up `Up (healthy)`, with
   `/health` responding `status=healthy`, `database=ok`, `redis=ok`.

> **Note**: `cloudpilot_infisical` still reports `ProviderUnavailableError: Infisical Universal
> Auth failed: Invalid credentials (401)` (degraded KMS). It is **non-fatal** for the round-trip —
> the backend stays healthy and the CIP→HTTP integration does not depend on Infisical KMS. Left as
> a gap for Kiro (see "Gaps" section).

---

## ✅ STEP 4 — Env vars in CloudPilot + restart

The 4 variables were added to `backend/.env` (a **gitignored**, **not committed** file), in a
dedicated section:

```
CIP_MASTER_KILL=false
CIP_RAG_ENABLED=true
CIP_API_URL=http://cip-api:8000
CIP_API_TOKEN=dev-integration-token
```

**Injection path (documented ASSUMPTION)**: the backend is mounted via **bind mount**
(`/mnt/d/cloudpilot-deploy/backend -> /app`) and pydantic-settings' `Settings` reads
`env_file=".env"` **directly from the filesystem** (cwd=`/app`). Therefore, the `.env` edited on
the host is visible inside the container and `podman restart cloudpilot_backend` was enough for the
process to reload settings — **it was not necessary to recreate the container** (which is also
impossible via `podman compose` on this host, see BLOCKED).

Confirmation via the `settings` object (not `os.environ`, since pydantic reads the file):

```
$ podman exec cloudpilot_backend python -c "from app.config import settings; print(settings.CIP_MASTER_KILL, settings.CIP_RAG_ENABLED, repr(settings.CIP_API_URL), repr(settings.CIP_API_TOKEN))"
False True 'http://cip-api:8000' 'dev-integration-token'
```

Health after restart:

```
$ podman exec cloudpilot_backend curl -fsS http://localhost:8000/health
{"status":"healthy","version":"0.1.0","environment":"development","checks":{"database":"ok","redis":"ok"},"budget_sync":{"status":"unknown","last_run_at":null,"age_seconds":null},"infisical_kms":{"status":"degraded"}}
```

> The compose `healthcheck` endpoint uses `/health`; `/api/health` returns 404 (not the correct
> route in this backend).

---

## ✅ STEP 5 — End-to-end round-trip (CloudPilot → CIP via HTTP)

Execution of the facade's real path, **inside `cloudpilot_backend`**:

```
$ podman exec cloudpilot_backend python -c "
import asyncio
from app.services.ai.cip_http_client import consult_official_cloud_knowledge, is_http_mode_enabled
print('HTTP_MODE:', is_http_mode_enabled())
result = asyncio.run(consult_official_cloud_knowledge(workspace_id='test-workspace', question='Como reduzir custo de EC2 com Savings Plans?', cloud='aws'))
print('GROUNDING:', result.has_grounding)
print('SOURCES:', len(result.sources))
print('ANSWER_LEN:', len(result.answer))
print('REFUSAL:', result.refusal_reason)
"
HTTP_MODE: True
GROUNDING: True
SOURCES: 8
ANSWER_LEN: 1338
REFUSAL: None
```

**Goal achieved in full**: `HTTP_MODE=True` (Mode B active), `GROUNDING=True`,
`SOURCES>0`, `ANSWER_LEN>0`, `REFUSAL=None`.

---

## ✅ STEP 6 — Documentation

- `docs/51-round-25-cloudpilot-integration.md` — this document.

---

## ✅ STEP 7 — Validation without regression

- **CIP** (dev suite): `IS_TESTING=1 python -m pytest -q --ignore=tests/test_smoke_ask.py --ignore=tests/test_ingest_delta.py`
- **CloudPilot**: `python -m pytest tests/ -q --timeout=60 -x`

> See the HANDOFF block at the end for the `passed/skipped/failed` numbers (run and appended
> during the round).

---

## BLOCKED (honestly recorded)

`podman compose ...` **does not run on this Windows host** — `get machine connection URI: could not
find a matching machine for connection "ssh://root@127.0.0.1:57498/..."` (same limitation as Round
24). Env var injection was done by editing `backend/.env` (bind-mount), avoiding the need to
recreate the container via compose.

---

## 📁 Changed artifacts

| File | Change |
|---|---|
| `backend/.env` (CloudPilot, gitignored) | + "CIP Integration (HTTP)" section with the 4 vars (`CIP_MASTER_KILL`, `CIP_RAG_ENABLED`, `CIP_API_URL`, `CIP_API_TOKEN`) |
| `docker network cloudpilot-deploy_cloudpilot_net` | + `cip-api` (network connection, not a file) |
| `docker network cloudpilot-deploy_cloudpilot_net` | + `cloudpilot_postgres` (alias `postgres`) |
| Postgres (`cloudpilot_postgres`) | + roles `cloudpilot`/`cloudpilot_app`, + databases `cloudpilot`/`infisical` (additive) |
| `docs/51-round-25-cloudpilot-integration.md` | new — this document |

> No CIP file (`D:\cip`) was changed beyond the doc. No commit performed. No
> `.env`/secret committed or pasted as real-value text.

---

## 🎯 Gaps for review (KIRO)

1. **Auth in production**: `cip_http_client` sends `Authorization: Bearer {CIP_API_TOKEN}`,
   whereas CIP authenticates via `X-API-Key`. In `CIP_ENV=dev` CIP waives it (works), but in
   production the header contract needs to be aligned (`X-API-Key` vs `Bearer`).
2. **Env var persistence**: the `backend/.env` edit persists because the file is
   gitignored and bind-mounted, but a `podman compose up -d` (on a host where compose works)
   would recreate the backend with `env_file` — confirm it re-reads the same `.env`.
3. **Shared Postgres**: the `cloudpilot_postgres` container is actually CIP's Postgres
   (inherited name). CloudPilot databases/roles were created additively, but if CIP
   re-initializes the `postgres_data` volume from scratch, CloudPilot loses the databases.
   Flagged as infra debt (already signaled in Round 24).
4. **Infisical KMS** reports `degraded` (401 credentials) — does not affect this round, but is a
   pending functional gap of the CloudPilot environment.
5. **Network**: the network connection (`network connect`) is volatile — it does not persist
   unless declared in compose (`networks` of both services). On a redeploy, redo the connect.
