# Release — Cloud Intelligence Platform (CIP)

> Operational release build document. It does **not** deploy to any destination
> (no registry/K8s/Railway defined at this phase). This document covers only:
> building the production image (lean `base` stage), required variables, and
> the pre-release checklist. `db/curated/` is already versioned in this repository
> (there is no separate binary artifact).

---

## 1. Production build (lean image)

The **release** image uses the `base` stage of the Dockerfile (lean runtime: only
`src/` + `db/` + `scripts/`). The `homolog` stage exists **only** to run the
suite/evaluation INSIDE the container (loads `tests/`, `eval/` and dev-deps) and
must **never** be tagged as release.

### Command (local, Podman or Docker)

```bash
podman build --target base -t cip:<version> .
```

Replace `<version>` with the semver tag (e.g., `0.2.0+integration`) or with the
release commit SHA (e.g., `cip:d0e6211`).

> The `build` job of the CI (`.github/workflows/ci.yml`) already builds the release
> with `--target base` and a **separate** `--target homolog` build for explicit
> validation of the suite. `docker build .` **WITHOUT** `--target` would resolve to the
> last stage (`homolog`) and produce the bloated image — never use it without `--target base`.

---

## 2. Environment variables

### Required (the API does not start / readiness fails without them)

| Variable | Purpose | Required |
|---|---|---|
| `DATABASE_URL` | Postgres/pgvector connection (asyncpg). `readiness` and ingestion depend on it. | **Yes** |
| `LLM_PROVIDER` | `minimax` \| `deepseek` \| `bedrock` \| `openai` \| `local` \| `stub`. | **Yes** |
| `LLM_API_KEY` **or** `MINIMAX_API_KEY` **or** `DEEPSEEK_API_KEY` | Provider credential (depends on `LLM_PROVIDER`). | **Yes** (per provider) |
| `EMBED_PROVIDER` | `local` \| `bedrock` \| `openai`. | **Yes** (default `local`) |
| `EMBED_MODEL` | Embeddings model (default `intfloat/multilingual-e5-small`). | **Yes** (default) |
| `EMBED_DIM` | Embedding dimension — **must match** `EMBED_MODEL` (validator blocks mismatch). | **Yes** (default 384) |
| `EMBED_DEVICE` | `cpu` \| `cuda`. | **Yes** (default `cpu`) |

All the variables above are read by `src/cip/config.py` (`Settings` via
pydantic-settings), including the `MINIMAX_API_KEY`/`DEEPSEEK_API_KEY` aliases
(explicit `validation_alias`). Do **not** set values here — use the destination's
secrets manager (Railway/encrypted env/sealed-secrets).

### Other recognized variables (optional, with defaults)

Reference by NAME — never paste real API key values.

- **App**: `CIP_ENV`, `CIP_READONLY`, `LOG_LEVEL`
- **Database**: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- **LLM**: `LLM_MODEL`, `LLM_CONTEXT_SIZE`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`,
  `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES`, `LLM_BASE_URL`, `DEEPSEEK_BASE_URL`
- **Concurrency/robustness**: `MAX_CONCURRENT_REQUESTS`, `REQUEST_TIMEOUT_S`,
  `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_S`, `DB_POOL_RECYCLE_S`
- **Embeddings**: `EMBED_QUERY_INSTRUCTION`, `EMBED_TEXT_INSTRUCTION`
- **Retrieval**: `RETRIEVAL_TOP_K`, `RETRIEVAL_MIN_SCORE`
- **Cloud (read-only tools)**: `AWS_REGION`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AZURE_SUBSCRIPTION_ID`,
  `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
  `GCP_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`
- **Observability**: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- **JWT**: `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_ISSUER`, `JWT_AUDIENCE`

> Rule: `pydantic-settings` with `extra="ignore"` — unknown variables are silently
> ignored. The list above is the **actual** surface area of `config.py`;
> nothing here was invented.

---

## 3. Run command (with healthcheck)

The readiness probe that returns `200 OK` when DB + embeddings + LLM + rate limiter
are ok is `/health/ready` (from `src/cip/api/health.py`):

```bash
podman run --rm -p 8000:8000 \
  -e DATABASE_URL="<your-dsn>" \
  -e LLM_PROVIDER="<provider>" \
  -e LLM_API_KEY="<key-via-secrets>" \
  -e EMBED_PROVIDER="local" \
  -e EMBED_MODEL="intfloat/multilingual-e5-small" \
  -e EMBED_DIM="384" \
  cip:<version>
```

Healthcheck after startup:

```bash
curl -fsS http://localhost:8000/health/ready
```

- `/health/live` — liveness (always 200 if the process is alive; **never** depends
  on DB/LLM).
- `/health/ready` — readiness (200 if DB + vector store + LLM + rate limiter ok;
  **503** otherwise → remove from the load balancer, without restart).
- `/health` — simple public liveness.

> The `Dockerfile` also defines a `HEALTHCHECK` (curl `/health/live`) and exposes
> port 8000. The container is **not** root (user `cip`).

---

## 4. Pre-release checklist

- [ ] Green suite: `590 passed / 0 failed` (closed homologation baseline).
- [ ] Homolog gate `10/10` (strict offline evaluation).
- [ ] Migrations applied: `db/schema.sql` + `db/migrations/*.sql` run on the target database.
- [ ] KB populated: `readiness` reports `chunks > 0` in `data_cloud_docs`
      (ingestion of `db/curated/` completed).
- [ ] `EMBED_DIM` and `EMBED_MODEL` consistent (validator in `config.py` blocks
      mismatch at boot).
- [ ] Release build done with `--target base` (never `homolog` for release).

---

## 5. Standalone deploy (open-source)

Brings up the COMPLETE stack from scratch on a clean Linux server, with CIP's **own**
Postgres (neutral name, without "cloudpilot") + lean API + idempotent bootstrap. This is the
open-source mode: CIP does not share a database with CloudPilot — each consumer talks to the
API **only via HTTP** (`/ask`, `/analyze`) and **never reads CIP's database** (see
`docs/49-cip-integration-contract.md`).

> The `docker-compose.yml` (integrated mode, consumes external `cloudpilot_postgres`,
> `homolog` image, port 8001) **remains unchanged** and continues to be the dev environment.
> The standalone uses `docker-compose.prod.yml`.

### Prerequisites

- Clean Linux server with `podman` (and `podman compose`, or `podman-compose`) installed.
- Port **8000** free on the host (ASSUMPTION: the compose maps `8000:8000`; if busy,
  change the mapping in `docker-compose.prod.yml`).
- Outbound network to download: the `pgvector/pgvector:pg16` image, KB fonts (AWS/GCP/Azure
  documentation URLs) and the HuggingFace embeddings model
  (`intfloat/multilingual-e5-small`, ~450MB) on the 1st ingest.

### Bring up from scratch

```bash
cp .env.prod.example .env.prod      # fill LLM_PROVIDER + LLM_API_KEY (or MINIMAX/DEEPSEEK) and CIP_API_KEYS
podman compose -f docker-compose.prod.yml up -d --build
```

The `cip-init` (ephemeral) runs `scripts/bootstrap_prod.py`: waits for a healthy `cip_postgres`,
applies `db/schema.sql` + `db/migrations/*.sql` (via `scripts/apply_migrations.py`) and ingests the
KB (`python -m cip.ingestion.ingest --scope mvp`, LOCAL embeddings on CPU — zero cost).
The `cip-api` only comes up when `cip-init` exits with exit 0.

### Expected time for the 1st ingest

**Measured in Round 24** (ingest from scratch, local CPU, e5-small): **~22 min** (1322s) for
**4324 chunks** (`batches_failed=0`). It varies with CPU/bandwidth; re-runs do not duplicate
(dedupe by `content_hash`), and the 1st ingest downloads the embeddings model (~450MB) only once.

### Health check

```bash
podman compose -f docker-compose.prod.yml exec cip-api \
  curl -fsS http://localhost:8000/health/ready
```

It should report `"healthy":true` with `vector_store` showing `chunks > 0`. Clean teardown:

```bash
podman compose -f docker-compose.prod.yml down -v    # removes postgres + volume + network
```
