# Local Homologation — Complete Guide

> **Audience**: QA engineers, SREs, developers
> **Date**: 2026-08-24
> **Stack**: Podman + Python 3.11+ + CIP

---

## 🎯 What is Homologation?

Homologation is the environment **identical to production**, but with:
- Synthetic or masked data
- Mock of external clouds (`CIP_USE_MOCK_CLOUDS=true`)
- Dev API key (no Bedrock cost if LLM_PROVIDER=stub)
- Smaller data volume

**Objective**: Validate changes before promoting to production (cloud PaaS + real Bedrock).

---

## 🚀 Quick Setup (5 minutes)

### Option A: Fully automated (Recommended)

```bash
# 1. Check prerequisites
podman --version    # expected: podman 4.x+
python --version     # expected: 3.11+

# 2. Complete setup
make homolog
# or
python scripts/setup_homolog.py

# 3. Expected result:
#    ✓ Prerequisites OK
#    ✓ Postgres+pgvector running
#    ✓ Schema applied
#    ✓ MVP ingestion complete (~237 chunks)
#    ✓ Pre-flight checks passed
#    ✓ Smoke tests passed
```

### Option B: Manual (more control)

```bash
# 1. Bring up only the DB
podman compose up -d db

# 2. Wait for the DB to be ready
sleep 5

# 3. Apply schema
psql "postgresql://cip:cip@localhost:5432/cip" -f db/schema.sql

# 4. Ingest KB
make ingest

# 5. Bring up the API
make up

# 6. Smoke test
make smoke
```

### Option C: Full stack (DB + API + Web)

```bash
# Brings everything up at once
podman compose up -d db api

# Wait for the DB to be ready
sleep 8

# Apply schema (first time)
podman exec -it cip-db psql -U cip -d cip -f /docker-entrypoint-initdb.d/01-schema.sql

# Ingest KB
make ingest

# Smoke test
make smoke

# Open Web UI
make web
# → Opens http://localhost:8080
```

---

## 🧪 Smoke Test (Quick Validation)

```bash
# Local
make smoke

# Custom URL
python scripts/smoke_test.py --url https://homolog.cip.internal --api-key xxx

# Verbose
make smoke-verbose
```

**Expected output**:
```
======================================================================
  CIP SMOKE TEST — http://localhost:8000
======================================================================
  [PASS] Health (public)                              (   5.2ms)
  [PASS] Liveness probe                                (   3.1ms)
  [PASS] Readiness probe                               (  45.8ms)
  [PASS] Prometheus metrics                            (   4.0ms)
  [PASS] Ask: AWS Well-Architected                     (1850.3ms)
  [PASS] Ask: grounding with URL                       (1620.5ms)
  [PASS] Analyze: insecure Terraform                   (2050.7ms)
  [PASS] Streaming (SSE)                               (3200.4ms)

  RESULT: 8 passed | 0 failed | 0 skipped
  [OK] ALL smoke tests passed!
```

**Exit codes**:
- 0 = all passed
- 1 = some failed
- 2 = API is not reachable

---

## 🔧 Configuration (.env for homolog)

```bash
# LLM (stub or local for no-cost homolog)
LLM_PROVIDER=stub
# To validate with a real LLM:
# LLM_PROVIDER=minimax
# LLM_MODEL=MiniMax-M3
# LLM_API_KEY=sk-cp-...
# LLM_BASE_URL=https://api.minimax.chat/v1

# Cloud tools (mock for homolog without creds)
CIP_USE_MOCK_CLOUDS=true
# CIP_MOCK_CLOUD_URL=http://localhost:8888

# Performance
CIP_QUERY_CACHE_TTL=3600  # 1h cache (in homolog)

# Auth (in homolog may be disabled)
CIP_API_KEYS="dev-key-homolog:tenant-default:60"

# Mode
CIP_ENV=dev
LOG_LEVEL=DEBUG  # more verbose in homolog
```

---

## 📋 Homologation Checklist (manual validation)

Before promoting to production, validate:

### ✅ Infrastructure
- [ ] DB reachable (port 5432)
- [ ] pgvector extension installed
- [ ] Schema applied (4 tables + 6 indexes)
- [ ] KB populated (chunks > 0)

### ✅ API
- [ ] Health check returns 200
- [ ] Liveness probe OK
- [ ] Readiness probe OK (all 4 checks)
- [ ] Prometheus metrics exposed
- [ ] Audit log writing

### ✅ Functionality
- [ ] Ask with grounding (official URLs)
- [ ] Ask with stream (progressive chunks)
- [ ] Analyze detects findings (insecure TF → critical)
- [ ] Specialists route correctly
- [ ] ReAct mode works (opt-in)
- [ ] Mock cloud tools return data

### ✅ Performance
- [ ] p95 latency < 5s
- [ ] Cache hit rate > 50% (after warmup)
- [ ] Throughput > 5 req/s
- [ ] Memory < 2GB per replica

### ✅ Security
- [ ] API key auth works
- [ ] Tenant isolation works
- [ ] Rate limit works (429 after X req/min)
- [ ] Logs do not leak PII

### ✅ Operational
- [ ] Smoke tests pass
- [ ] Pre-flight check passes
- [ ] Eval score >= 4.0 (when real LLM available)
- [ ] Demo works end-to-end

---

## 🔄 Homologation Workflow

```
Dev (local)             Homolog (staging)         Prod
─────────────────       ─────────────────       ────────────────
make up                  podman compose up        deploy cloud
make ingest              make ingest (real)       (skipped, KB
                                                  already populated)
make smoke               make smoke               make smoke
                         (with real LLM)          (with real LLM)
git push origin          trigger deploy           trigger deploy
                   ──>  (GitHub Actions)    ──>  (Cloud PaaS)
```

---

## 🐛 Troubleshooting

### DB does not connect
```bash
# Check whether the container is running
podman ps -a | grep cip-db

# If it is not, start it
podman compose up -d db

# Logs
podman logs cip-db
```

### Schema does not apply
```bash
# Check whether the DB is ready
podman exec cip-db pg_isready -U cip

# Apply manually
podman exec -i cip-db psql -U cip -d cip < db/schema.sql
```

### Smoke test fails with 503
```bash
# Readiness probe failed — DB probably down
podman ps -a | grep cip-db
podman logs cip-db
```

### LLM does not respond
```bash
# Check .env
grep LLM_PROVIDER .env
# If stub: LLM_PROVIDER=stub (dev)

# To test with real MiniMax
LLM_PROVIDER=minimax python -m cip.api.app
```

### Full reset (start from scratch)
```bash
# Stops everything and removes volumes
podman compose down -v
make homolog
```

---

## 📊 Comparison: Homolog vs Production

| Aspect | Homolog | Production |
|---|---|---|
| **DB** | Local Podman | Managed Postgres (RDS or similar) |
| **LLM** | Stub or MiniMax | Bedrock Claude Sonnet 4.5 |
| **Cloud tools** | Mock (CIP_USE_MOCK_CLOUDS=true) | Real (AWS creds) |
| **Auth** | Dev API key | Real tenant API keys |
| **Cache** | CIP_QUERY_CACHE_TTL=3600 (test perf) | CIP_QUERY_CACHE_TTL=3600 |
| **Logs** | stdout (verbose) | Langfuse + CloudWatch |
| **Metrics** | Local /metrics | Prometheus + Datadog |
| **Deploy** | Local | CI/CD |

---

## 📚 Next Steps

When homologation is stable:

1. **Validate eval gate** with real LLM (MiniMax M3)
2. **Document findings** in `docs/32-homolog-results.md`
3. **Promote to production**:
   - Deploy on the chosen PaaS (Cloud Run, App Runner, ECS, etc.)
   - Bedrock: configure AWS creds
   - DNS: point to the PaaS
4. **Smoke test in production**
5. **Monitor** (CloudWatch, Datadog, Sentry)

**For production details**, see:
- `docs/09-plano-execucao-llm-cloud.md` — original plan (10-14 weeks)
- `docs/18-production-runbook.md` — complete runbook
- `docs/23-architecture-c4.md` — C4 architecture
- `docs/14-revisao-humana.md` — review by 5 architects

---

**Status**: Local homolog ready to validate
**Next**: End-to-end validation with real LLM (Round 19+)
**Goal**: Promote to production with confidence
