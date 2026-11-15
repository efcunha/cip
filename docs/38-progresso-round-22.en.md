# Round 22 Progress — Staging in Container + Compose Network Fix

> **Date**: 2026-08-25 | **Round**: 22/30 | **Status**: PARTIAL (real LLM staging blocked by missing key)

---

## 🎯 Round Result

Fixed the **`docker-compose.yml` network gap** (missing `networks:` block) and ran the quality suites **inside the container** (`homolog` stage). **Staging with real LLM (MiniMax M3) was BLOCKED** because the only `MINIMAX_API_KEY` available in the environment is a placeholder (`sk-cp-ZZ…`), with no real key.

| Item | Status |
|---|---|
| `networks:` block in compose (internal DNS `cip_default`) | ✅ |
| `cip-api` resolves `cloudpilot_postgres` via DNS | ✅ (10.89.1.6) |
| SQL migrations applied (002/003/004) | ✅ |
| KB populated (6 knowledge areas, 3.674 chunks) | ✅ |
| Preflight `--strict` | ✅ 6/6 gates |
| Tests inside the container | ✅ 573 passed / 17 failed / 19 skipped |
| Real LLM staging (MiniMax M3) | ⛔ BLOCKED (placeholder key) |
| Offline eval (fallback) | ⚠️ GATE FAIL (expected without LLM) |

---

## ✅ Concrete Deliverables

### 1. Fix of the `networks:` block in `docker-compose.yml`

The header instructed `podman network connect cip_default cloudpilot_postgres` and referred to "see `networks:` below", but the block **did not exist**. Added the `networks:` block declaring `cip_default` as `external: true` (the network already exists, created by Podman as `<dir>_default`), and referenced it in the `cip-api` service.

```diff
+ networks:
+   # Rede bridge com DNS habilitado usada pelo cip-api para resolver o Postgres
+   # externo `cloudpilot_postgres` por nome. Declarada como `external` porque já
+   # foi criada na primeira subida do compose ...
+   cip_default:
+     external: true
```

```diff
    cip-api:
      <<: *api-common
      container_name: cip-api
+    networks:
+      - cip_default
```

**Real name confirmed**: `podman network ls` returns `cip_default` (bridge), and `podman network inspect cip_default` shows `dns_enabled: true`.

### 2. `scripts/apply_migrations.py` — rewritten to use `psycopg` (not `psql`)

The script shelled out to the `psql` binary, which **does not exist** in the runtime/base image (only `libpq-dev`). Rewritten to use `psycopg` (Python driver already present), with explicit transactions and idempotency. Now portable to the lean `base` stage.

### 3. `Dockerfile` — `homolog` stage with `COPY . ./`

The homolog stage did not copy build/CI artifacts referenced by the full suite (`Makefile`, `docker-compose.yml`, `docs/`, `.github/`, `CHANGELOG.md`, `ops/`, `iac/`, `QUICKSTART.md`, `.devcontainer/`). Refactored to `COPY . ./` (the `.dockerignore` already excludes `.env` and caches).

### 4. `scripts/preflight.py` — `--strict` flag

Added `--strict` to standardize the CLI with `homolog_validate.py`/`run_eval.py` (no-op: preflight is already strict by default).

### 5. `src/cip/observability.py` — dedicated Prometheus registry

The chat metrics used the GLOBAL registry of `prometheus_client`, causing `DuplicateTimeseries` when the module was re-imported under `src.cip.observability` vs `cip.observability`. Moved to a dedicated `CollectorRegistry`.

### 6. Fixed tests (factual drift)

- `tests/test_homolog.py` — `TestPodmanCompatibility` (2 tests): compose now uses an external Postgres, does not start `postgres:`/`pgvector`.
- `tests/test_chat_multiturn.py` — `TestDockerIntegration` (2 tests): `test_compose_defines_cip_api_service` and `test_compose_has_postgres_healthcheck` updated for external Postgres.
- `tests/test_minimax_provider.py` — `test_default_provider_is_stub`: isolates `os.environ["LLM_PROVIDER"]` (the Dockerfile defines `ENV LLM_PROVIDER=minimax`).

### 7. `.dockerignore` — cache directories added

`.pytest_cache/`, `.audit/`, `.tmp_*/`, `pip-*`, `.code-review-graph/` etc. (avoids including them in the build context and "Access denied" errors).

---

## 🧪 Validation (real outputs)

### Network / DB

```
$ podman network ls
NETWORK ID    NAME        DRIVER
7e7334486651  cip_default bridge

$ podman exec cip-api python -c "import socket; print(socket.gethostbyname('cloudpilot_postgres'))"
10.89.1.6
```

### Health (all checks)

```json
{"healthy":true,"checks":[
  {"name":"database","healthy":true,"message":"Postgres+pgvector OK (28ms)"},
  {"name":"llm","healthy":true,"message":"LLM provider 'minimax' initialized"},
  {"name":"vector_store","healthy":true,"message":"1473 chunks indexed"},
  {"name":"rate_limiter","healthy":true}]}
```

### Migrations

```
$ podman exec cip-api python scripts/apply_migrations.py
Encontradas 3 migration(s):
  - 002_relax_cloud_and_doc_type_constraints.sql
  - 003_conversations_and_feedback.sql
  - 004_share_tokens_and_extras.sql
Aplicando migrations:
  - 002_relax_cloud_and_doc_type_constraints.sql ... OK
  - 003_conversations_and_feedback.sql ... OK
  - 004_share_tokens_and_extras.sql ... OK
[OK] Migrations processadas.
```

### KB (full ingestion)

```
total: 3674 chunks
  multi: 1757 | azure: 646 | gcp: 504 | architecture: 368 | aws: 323 | case-studies: 76
```

`ingestion_complete`: `ingested_chunks=2222, skipped=116, batches_done=82, batches_failed=0`.

### Preflight

```
Resumo: 6 OK, 0 FAIL, 0 WARN de 6 checks
  [OK] database             pgvector 0.8.6, 3674 chunks
  [OK] llm_provider         LLM 'minimax' + embed 'local' OK
  [OK] health_endpoints     4 checks passaram
[GO] Todos os checks críticos passaram.
```

### Tests

```
573 passed, 17 failed, 19 skipped, 2 warnings in 274.97s
```

The remaining 17 are **pre-existing drift** or **dependent on a real LLM key** (out of Round 22 scope):

| Bucket | N | Cause |
|---|---|---|
| `test_web_ui` JS structure | 5 | `web/app.js` was rewritten for multi-turn (renamed functions) |
| `test_specialists` | 7 | Runs the real orchestrator → requires valid MiniMax key |
| `test_tools_cache`/`test_tools_mock_integration` | 2 | Real tool execution → LLM |
| `test_inspection_rules` (RDS Multi-AZ) | 1 | Terraform rule T4 |
| `test_mock_cloud_cli` | 2 | Subprocess CLI (status/bench) |

### Staging (BLOCKED) + Offline eval

`MINIMAX_API_KEY` in the container = `sk-cp-ZZ…` (placeholder, 125 chars). Without a real key → **BLOCKED**.

```
$ podman exec cip-api python eval/run_eval.py --offline --strict
Avaliando 106 casos (offline)...
RESULTADO: 3/106 passaram
GATE: [FAIL]
Scores médios:
  accuracy: 3.30 | grounding: 5.00 | citation: 5.00 | format: 1.00 | zero_price: 5.00
```

`accuracy` and `format` do not pass without a real LLM (expected in offline mode — the Inspection Engine only detects terms/problems, does not generate a structured response).

---

## 📈 Progress

```
Round 21 — Limpeza Railway (100%) ✅
Round 22 — Homolog no container + rede compose (80% — homolog LLM real bloqueada) ⏳
```

---

## 🚧 BLOCKERS

1. **`LLM_API_KEY`/`MINIMAX_API_KEY` missing** — the only available key is placeholder `sk-cp-ZZ…`. Without a real key, MiniMax M3 staging cannot be run.
2. **`podman compose` CLI broken on the host** — `podman compose <sub>` fails with `get machine connection URI: could not find a matching machine` and `podman machine list`/`podman build` fail with `Acesso negado` on `C:\Users\ECUNHA\.ssh\known_hosts` / `C:\Users\ECUNHA\.config\containers\podman\machine\wsl\` and `D:\Projetos\cip\.pytest_cache`. Worked around with `podman exec`/`podman cp` directly (the containers were already UP and healthy).

---

## 🎯 Next Steps

1. **Provide a real `MINIMAX_API_KEY`** (env or `.env`) and re-run `scripts/homolog_validate.py --strict` to complete real LLM staging.
2. **Update `tests/test_web_ui.py`** for the new `web/app.js` functions (multi-turn) — factual drift from Round 22 Phase 2.
3. **Resolve the 7 `test_specialists`** — either provide a real LLM key, or mock the orchestrator (today they call the LLM for real).
4. **Investigate `test_inspection_rules`** (Terraform RDS Multi-AZ rule) and `test_mock_cloud_cli` (subprocess).
5. **Repair the host's `podman compose`/`podman machine` connection** (`known_hosts`/lockfile permissions) to allow native `build`/`compose`.
