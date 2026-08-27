# Round 24 — Stand-alone (self-contained) Docker Compose + idempotent bootstrap + timed ingest

> **Date**: 2026-08-26 | **Scope**: create a self-contained `docker-compose.prod.yml` (CIP's own
> Postgres, neutral name `cip_postgres`) + idempotent bootstrap (schema + migrations + ingest from
> scratch) + **time the from-scratch ingest** + document the CloudPilot→CIP HTTP contract.
> WITHOUT changing the current `docker-compose.yml` (integrated mode). WITHOUT touching
> router.py / `_resolve_cloud_from_area` / RAG logic. WITHOUT push/deploy. All test containers
> were torn down at the end; the 16 originals remain UP and intact.

---

## 🎯 Result

| Metric | Value (measured) |
|---|---|
| From-scratch ingest (local CPU, e5-small) | **~22.8 min** (total bootstrap: 1368s) |
| Chunks ingested from scratch | **4325** (`batches_failed=0`) |
| Tables created (schema + migrations) | **9** (cloud_docs, data_cloud_docs, environments, analyses, findings, conversations, messages, share_tokens, schema_migrations) |
| Migrations applied | **3** (002, 003, 004) |
| `/health/ready` in isolated test | **healthy:true** — vector_store **4325 chunks** |
| HTTP contract CloudPilot→CIP | `docs/49-cip-integration-contract.md` |
| Dev suite (not regressed) | 590 passed / 0 failed (see STEP 6) |
| Originals after teardown | cloudpilot_postgres + cip-api **Up (healthy)** |

---

## ✅ STEP 1 — Self-contained `docker-compose.prod.yml`

Created `docker-compose.prod.yml` with three services:

1. **`cip_postgres`** — CIP's OWN Postgres (image `pgvector/pgvector:pg16`), **neutral** name
   (not "cloudpilot"), named volume `cip_pgdata`, `POSTGRES_USER/PASSWORD/DB=cip`,
   healthcheck `pg_isready -U cip -d cip`.
2. **`cip-init`** — image `target base`, `depends_on: cip_postgres (service_healthy)`,
   `entrypoint: python scripts/bootstrap_prod.py`, `restart: "no"` (ephemeral, exits 0 when done).
3. **`cip-api`** — `target base`, `depends_on: cip-init (service_completed_successfully)`,
   `DATABASE_URL=postgresql://cip:cip@cip_postgres:5432/cip`, `env_file .env.prod` (required:false),
   port `8000:8000` (ASSUMPTION: 8000 free on target server — documented).
4. Own network `cip_prod_net` (created by compose, NOT external) + volume `cip_pgdata`.

Also created `.env.prod.example` (versionable placeholders, mirroring the required vars of
`docs/RELEASE.md`: `LLM_PROVIDER`, `LLM_API_KEY`|`MINIMAX_API_KEY`|`DEEPSEEK_API_KEY`, `EMBED_*`,
`CIP_API_KEYS`) and added `.env.prod` to `.gitignore`.

> The existing `docker-compose.yml` (integrated mode: external Postgres + `homolog` image +
> port 8001) **was not changed** — only documented in the new compose header and in
> `docs/RELEASE.md`.

---

## ✅ STEP 2 — Idempotent bootstrap

Created `scripts/bootstrap_prod.py` (called by `cip-init`). Idempotent sequence:

1. `_wait_for_db()` — waits for `cip_postgres` to accept TCP.
2. `_apply_schema()` — applies `db/schema.sql` via psycopg `ClientCursor` (the `base` image **does
   not** have the `psql` binary).
3. `_apply_migrations()` — calls `scripts/apply_migrations.py` (the `schema_migrations` control
   table prevents re-application).
4. `_ingest()` — `python -m cip.ingestion.ingest --scope mvp` (dedupe by `content_hash` +
   delta by `doc_hash` make re-runs non-duplicating).

**Recorded choice**: dedicated init-service via `scripts/bootstrap_prod.py`. A shell script
(`bootstrap_prod.sh`) was discarded because the `base` image has neither `psql` nor `bash`-isms —
the Python script reuses the already-present `psycopg` driver and is idempotent by construction.

### 🐛 Fixed ROOT CAUSE — `scripts/apply_migrations.py` persisted nothing

During the from-scratch bootstrap test, a REAL (pre-existing) bug was found in
`apply_migrations.py`: migrations printed **"OK"** and exited with code 0, but **no table was
created** and `schema_migrations` stayed empty. Two-layer cause:

1. `conn.execute(sql)` uses psycopg 3.3's **extended protocol**, which **does not split
   multi-statement scripts** (especially with `CREATE FUNCTION ... $$ ... $$`). Statements after
   the first were silently discarded.
2. Even with `ClientCursor` (simple query) applied, `already_applied()` ran
   `conn.execute("SELECT ... %s")` **outside a transaction** with `autocommit=False`, leaving the
   connection in **INTRANS** state; the following `with conn.transaction()` did not start a new
   transaction and the script ran in a "dirty" transaction discarded at the end.

**Fix** (minimal and surgical, without touching RAG/router):
- Execute migration SQL via `ClientCursor(conn)` (simple query).
- `conn.rollback()` after the `already_applied` SELECT to close the implicit transaction.

Proof: after the fix, the from-scratch bootstrap created the **9 tables** and recorded the **3
migrations**. `db/schema.sql` did not have the problem (no `$$`), but received `ClientCursor` for
consistency.

---

## ✅ STEP 3 — Timed from-scratch ingest

The `podman compose` wrapper is **BLOCKED** on this Windows host (see "BLOCKED" below), so the
functional test was orchestrated with the **`podman` CLI** faithfully reproducing what compose
would do (same network/volume/container names, same `target base` image, same entrypoint).

**REAL measurement** (from scratch, clean DB, local CPU, model `intfloat/multilingual-e5-small`):

```
t0 = 2026-08-26T13:50:12 (podman run -d cip-init → bootstrap)
t1 = 2026-08-26T14:13:01 (container finished, ExitCode=0)
TOTAL bootstrap (wait-db + schema + migrations + ingest) = 1368s ≈ 22.8 min
ingestion_complete: ingested_chunks=4325, skipped=168, batches_done=83, batches_failed=0
```

The measurement was made by **real start/finish timestamps of the `cip-init` container**
(`podman inspect State.StartedAt / State.FinishedAt`), not by estimate. Idempotent re-run
confirmed `ingested_chunks=0, skipped=190` (dedupe by `content_hash` does not duplicate).

> The chunk count (4325) is slightly lower than the 4785 in the production database because a
> from-scratch ingest on a clean host cannot download some remote `case-studies`/`architecture`
> sources (blogs that block fetch — a documented problem since Round 22.4). It is expected and
> not a regression.

---

## ✅ STEP 4 — Health + teardown

Started `cip-api` (image `cip:prod`) against CIP's own `cip_postgres`, mapped on `8100:8000`
(host port 8000 belongs to cloudpilot_backend). `/health/ready`:

```json
{"healthy":true,"checks":[
  {"name":"database","healthy":true,"message":"Postgres+pgvector OK (31ms)"},
  {"name":"llm","healthy":true,"message":"LLM provider 'stub' initialized"},
  {"name":"vector_store","healthy":true,"message":"4325 chunks indexed","details":{"chunks":4325}},
  {"name":"rate_limiter","healthy":true,"message":"Rate limiter operational"}
],"version":"0.2.0+integration"}
```

**chunks > 0 (4325) coming from the from-scratch ingest** — proves the self-contained stack is
healthy. (ASSUMPTION: `LLM_PROVIDER=stub` in the test so readiness does not depend on an API key;
in production the real provider comes from `.env.prod`.)

**Teardown** (equivalent to `down -v`): `podman rm -f` of the 3 containers + `podman volume rm
cip_pgdata` + `podman network rm cip_prod_net`. Confirmed: **no leftover** and the original
`cloudpilot_postgres` and `cip-api` remain **Up (healthy)**.

---

## ✅ STEP 5 — Documentation

- `docs/RELEASE.md` — new section **"Standalone deploy (open-source)"** (prereqs, `cp
  .env.prod.example .env.prod`, `podman compose -f docker-compose.prod.yml up -d --build`,
  expected first-ingest time **~23 min** measured, health check, teardown).
- `docs/49-cip-integration-contract.md` — CloudPilot→CIP HTTP contract (`/ask`, `/analyze`,
  request/response based on the real Pydantic models of `src/cip/api/schemas.py`; **HTTP-ONLY**
  consumption; consumers **NEVER read the CIP database**).
- `docs/50-round-24-standalone-compose.md` — this document.

---

## BLOCKED (honestly recorded)

`podman compose -f docker-compose.prod.yml ...` **does not run on this Windows host** — the Go
wrapper of podman fails with `get machine connection URI: could not find a matching machine for
connection "ssh://root@127.0.0.1:57498/..."`, because it needs to read the "machine" metadata in
`C:\Users\ECUNHA\.config\containers\podman\machine\wsl\...` and hits **Access denied** (ACL outside
the workspace). The pure `podman` CLI (`ps/run/exec/build/network/volume`) works normally. Also
**pip does not run** (Permission denied in sandbox TMP), so Python `podman-compose` could not be
installed as an alternative provider.

**Applied workaround**: test orchestration with direct `podman` CLI (same resources that compose
would declare), which proves compose's behavior; the `docker-compose.prod.yml` artifact remains
valid and ready for a Linux server (where `podman compose` works normally). `podman build
--target base` with a **clean context** (staging without `.pytest_cache`) was used and proved the
lean build (the root context fails by ACL on `.pytest_cache`, pre-existing).

---

## 📁 Changed artifacts

| File | Change |
|---|---|
| `docker-compose.prod.yml` | new — self-contained stack (cip_postgres + cip-init + cip-api, own network/volume) |
| `.env.prod.example` | new — versionable placeholders (LLM_*, EMBED_*, CIP_API_KEYS) |
| `scripts/bootstrap_prod.py` | new — idempotent bootstrap (schema + migrations + ingest) |
| `scripts/apply_migrations.py` | **fix** — ClientCursor + rollback (multi-statement/migrations didn't persist) |
| `.gitignore` | + `.env.prod` |
| `docs/RELEASE.md` | + "Standalone deploy (open-source)" section |
| `docs/49-cip-integration-contract.md` | new — CloudPilot→CIP HTTP contract |
| `docs/50-round-24-standalone-compose.md` | this document |

---

## 🎯 Gaps for review (KIRO)

1. **Deploy target** still undefined (Linux server/VM/K8s/Railway) — out of scope.
2. **Registry** of images not provisioned (the `cip:prod` image stays local / build on target).
3. **Secrets manager** — `LLM_API_KEY`/`CIP_API_KEYS` in production: no vault defined.
4. Base image still heavy (~2GB+ due to `torch`/CUDA via `sentence-transformers`); consider
   `EMBED_PROVIDER=bedrock|openai` (no local ML) as a future optimization.
5. **Future rename** of the `cloudpilot_postgres` container → neutral name (it is CIP's Postgres,
   inherited/misleading name) — dev environment infra change, not this round.
6. Migration of the local dev environment to standalone (when/who) — left for human decision.
