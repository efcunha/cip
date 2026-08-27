# Production Runbook — CIP Cloud Intelligence Platform

> **Date**: 2026-08-24 | **Version**: 1.0 | **Status**: Operational
> **Audience**: SREs, Platform Engineers, Cloud Architects

---

## 🎯 Overview

CIP is an LLM specializing in AWS/GCP/Azure, served as a REST API. This runbook covers:
- Initial deploy (Cloud PaaS)
- Daily operation (monitoring, scaling)
- Incident response (degradation, recovery)
- Maintenance (drift detection, monthly re-ingestion)

**SLA target:**
- p95 latency < 5s (MVP) / < 3s (production with Bedrock/Claude)
- Uptime ≥ 99.5% (excluding maintenance)
- Eval score ≥ 4.0 (quality gate)

---

## 📊 Production Architecture

```
┌─────────────────┐
│  Cloudflare/     │ ← Rate limit L4, DDoS
│  AWS WAF        │
└────────┬────────┘
         │
┌────────▼────────┐
│  Cloud PaaS     │ ← FastAPI + uvicorn
│  (1+ replicas)  │   - /ask, /analyze (authenticated)
│                 │   - /health/{live,ready} (k8s probes)
│                 │   - /metrics (Prometheus)
└────────┬────────┘
         │
   ┌─────┴──────┐
   │            │
┌──▼───┐   ┌────▼────┐
│Postgres│   │Bedrock │
│+pgvec  │   │Claude  │
│       │   │Sonnet4.5│
└───────┘   └─────────┘
```

**External components:**
- **Postgres 16 + pgvector 0.8**: vector store
- **AWS Bedrock**: Claude Sonnet 4.5 (base LLM)
- **HuggingFace**: optional, for local embeddings
- **Langfuse** (optional): distributed tracing
- **SendGrid/Slack** (optional): webhook alerts

---

## 🚀 Initial Deploy

### Prerequisites
- Cloud PaaS account (Cloud Run, App Runner, ECS, etc.)
- Postgres 16 + pgvector (managed DB or RDS)
- AWS account with Bedrock enabled
- Custom domain (optional)

### Step 1: Provision Database

```bash
# Cloud SQL or managed Postgres
# (depends on the chosen PaaS)

# Or AWS RDS
aws rds create-db-instance \
  --db-instance-identifier cip-prod \
  --db-name cip \
  --engine postgres --engine-version 16 \
  --db-instance-class db.t3.medium \
  --master-username cip --master-user-password <SECURE> \
  --enable-extension pgvector
```

### Step 2: Configure Environment Variables

```bash
# Required
DATABASE_URL=postgresql://cip:<SECURE>@<HOST>:5432/cip
LLM_PROVIDER=bedrock
LLM_MODEL=anthropic.claude-sonnet-4-5-20250929-v1:0
EMBED_PROVIDER=local
EMBED_MODEL=intfloat/multilingual-e5-small
EMBED_DIM=384
CIP_API_KEYS="key-prod-abc:tenant-acme:60,key-prod-def:tenant-zenith:120"
CIP_ENV=prod
LOG_LEVEL=INFO

# Optional (tracing + audit)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
CIP_AUDIT_LOG_PATH=/var/log/cip/audit.jsonl
```

### Step 3: Apply Schema

```bash
psql $DATABASE_URL -f db/schema.sql
```

### Step 4: Initial Ingestion

```bash
# MVP (~245 URLs → ~237 chunks)
python -m cip.ingestion.ingest --scope mvp

# Full (~245 curated URLs + expand → ~5k chunks)
python -m cip.ingestion.ingest --scope full --expand
```

### Step 5: Pre-flight Check

```bash
python scripts/preflight.py
# Expected: [GO] All critical checks passed.
```

### Step 6: Deploy

```bash
# Cloud PaaS (examples)
gcloud run deploy --source .
# or
aws ecs update-service ...
# or
fly deploy

# Or Docker (any host)
docker build -t cip:latest .
docker run -d --name cip \
  -p 8000:8000 \
  -e DATABASE_URL=$DATABASE_URL \
  -e CIP_API_KEYS=$CIP_API_KEYS \
  cip:latest
```

### Step 7: Smoke Test in Production

```bash
# Health
curl https://api.cip.internal/health/ready

# Auth
curl -H "X-API-Key: key-prod-abc" \
     -H "X-Tenant-Id: tenant-acme" \
     -d '{"question":"What is AWS S3?"}' \
     -H "Content-Type: application/json" \
     https://api.cip.internal/ask
```

---

## 🩺 Monitoring

### Critical Endpoints

| Endpoint | Function | Probe Type | SLA |
|---|---|---|---|
| `GET /health` | Simple liveness | - | < 50ms |
| `GET /health/live` | Liveness probe (k8s) | LivenessProbe | < 100ms |
| `GET /health/ready` | Readiness probe (k8s) | ReadinessProbe | < 5s |
| `GET /metrics` | Prometheus metrics | Scraped | < 200ms |
| `POST /ask` | RAG query | Authenticated | p95 < 5s |
| `POST /analyze` | Full orchestration | Authenticated | p95 < 8s |

### Key Metrics (Prometheus)

```
# Request rate per endpoint/status
cip_requests_total{endpoint="/ask",method="POST",status="200",tenant="acme"}

# Latency
cip_request_duration_seconds_bucket{endpoint="/ask",method="POST",le="5.0"}

# Grounding rate (% responses with citation)
rate(cip_grounded_responses_total[5m]) / rate(cip_requests_total[5m])

# Findings generated
cip_findings_total{severity="critical",domain="security",tenant="acme"}

# Specialists executed
cip_specialist_executions_total{specialist="finops",tenant="acme"}

# Errors
rate(cip_requests_total{status=~"5.."}[5m])
```

### Suggested Alerts (Datadog/Prometheus)

```yaml
# Degraded latency
- alert: cip_high_latency
  expr: histogram_quantile(0.95, rate(cip_request_duration_seconds_bucket[5m])) > 5
  for: 5m
  severity: warning

# High error rate
- alert: cip_high_error_rate
  expr: rate(cip_requests_total{status=~"5.."}[5m]) > 0.1
  for: 2m
  severity: critical

# Low grounding
- alert: cip_low_grounding_rate
  expr: rate(cip_grounded_responses_total[15m]) / rate(cip_requests_total{endpoint="/ask"}[15m]) < 0.8
  for: 10m
  severity: warning

# DB connection pool exhausted
- alert: cip_db_pool_exhausted
  expr: rate(cip_requests_total{status="500"}[5m]) > 0.05
  for: 5m
  severity: critical
```

### Audit Log (Compliance)

Every request generates an entry in `$CIP_AUDIT_LOG_PATH` (append-only JSONL):

```json
{
  "timestamp": "2026-08-24T18:30:00Z",
  "tenant_id": "acme",
  "api_key_hash": "abc123def456",
  "endpoint": "/ask",
  "method": "POST",
  "status": 200,
  "latency_ms": 1850,
  "user_agent": "curl/7.79.1",
  "source_ip": "203.0.113.42",
  "question_preview": "Como otimizar custos de EC2?",
  "answer_length": 1240,
  "has_grounding": true,
  "n_sources": 6,
  "tools_used": ["aws:cost"],
  "specialists_used": ["aws", "finops"],
  "findings_count": 0,
  "error": ""
}
```

**Recommended retention**: 90 days for compliance (configure S3 lifecycle if /var/log/cip/audit.jsonl).

---

## 🔄 Daily Operation

### Configured Cron Jobs

| Job | Schedule | Command | Owner |
|---|---|---|---|
| **Monthly drift detection** | `0 3 1 * *` (1st day, 03:00 UTC) | `python scripts/monthly_cron.py` | SRE |
| **Test suite** | Every push/PR | CI/CD | - |
| **Eval gate** | Every push/PR | CI/CD | - |
| **Audit log rotation** | `0 0 * * *` (daily) | logrotate | SRE |
| **DB vacuum** | `0 4 * * 0` (Sunday) | VACUUM ANALYZE | SRE |

### Daily Tasks (15min)

```bash
# 1. Health check
curl -sf https://api.cip.internal/health/ready | jq .

# 2. Check metrics (error rate, latency)
curl -s https://api.cip.internal/metrics | grep -E "cip_requests_total{status=\"5" | head

# 3. Audit log (last 100 entries, summarize)
tail -100 $CIP_AUDIT_LOG_PATH | jq -r '.tenant_id' | sort | uniq -c

# 4. DB health (connections, vacuum)
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity;"
psql $DATABASE_URL -c "SELECT relname, n_live_tup, n_dead_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 5;"
```

### Weekly Tasks (30min)

```bash
# 1. Eval score check (regression?)
python eval/run_eval.py --api https://api.cip.internal --report-md --strict
# Expected: GATE: [PASS] — if it fails, alert and investigate

# 2. Manual drift detection (extra)
python scripts/monthly_reingest.py --detect-only

# 3. Audit log review (compliance)
jq -r '.status' $CIP_AUDIT_LOG_PATH | sort | uniq -c

# 4. Cost report (Bedrock dashboard)
# Check AWS Cost Explorer for "Claude Sonnet 4.5" usage
```

### Monthly Tasks (2h)

```bash
# 1. Run monthly cron (drift + re-ingest if necessary)
python scripts/monthly_cron.py
# Expected: 0 changes OR drift detected + re-ingest OK

# 2. Human evaluation (Quality Gate)
# - 5 architects × 20 scenarios = 100 reviews
# - Consolidate with automated eval (60% human + 40% auto)

# 3. Capacity planning
psql $DATABASE_URL -c "SELECT pg_size_pretty(pg_database_size('cip'));"
psql $DATABASE_URL -c "SELECT count(*) FROM data_cloud_docs;"

# 4. Backup verification
# Verify that Cloud PaaS automatic backups are being performed
```

---

## 🚨 Incident Response

### Incident 1: p95 latency > 5s

**Symptoms**: `cip_high_latency` alert, Grafana dashboard shows p95 above SLA.

**Diagnosis**:
```bash
# 1. Check latency per endpoint
curl -s https://api.cip.internal/metrics | grep cip_request_duration_seconds_bucket | head

# 2. Check current concurrency
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity;"

# 3. Check LLM errors
tail -1000 /var/log/cip/app.log | grep "llm_error\|bedrock_error"
```

**Actions**:
1. **If Bedrock is slow**: scale to Bedrock provisioned throughput (contact AWS)
2. **If DB is slow**: check `n_dead_tup` (run VACUUM) or `pg_stat_activity` (long-running queries)
3. **If concurrency is high**: increase `MAX_CONCURRENT_REQUESTS` (env var) + scale PaaS
4. **If embeddings are slow**: change `EMBED_PROVIDER` from `local` to `bedrock` (Titan)

### Incident 2: Sustained 500 error

**Symptoms**: `cip_high_error_rate` alert.

**Diagnosis**:
```bash
# 1. Structured logs
tail -500 /var/log/cip/app.log | jq 'select(.level == "error") | .event + ": " + .error'

# 2. Audit log for context
tail -1000 $CIP_AUDIT_LOG_PATH | jq 'select(.status >= 500) | {timestamp, endpoint, tenant_id, error}'

# 3. DB connectivity
psql $DATABASE_URL -c "SELECT 1"  # if it fails, DB problem
```

**Actions**:
1. **If DB is down**: managed PaaS has automatic failover to replica
2. **If Bedrock quota exceeded**: check `aws service-quotas list-service-quotas --service-code bedrock` and request an increase
3. **If Langfuse is down**: tracing degrades gracefully (does not block)
4. **If response with 0% grounding**: KB may be corrupted → re-ingest

### Incident 3: Grounding rate < 80%

**Symptoms**: Responses without citation, `cip_low_grounding_rate` alert.

**Diagnosis**:
```bash
# 1. Check if vector store has data
psql $DATABASE_URL -c "SELECT count(*) FROM data_cloud_docs;"

# 2. Check last ingestion
psql $DATABASE_URL -c "SELECT MAX(ingested_at) FROM data_cloud_docs;"  # if schema allows

# 3. Check drift (URLs may have changed)
python scripts/monthly_reingest.py --detect-only
```

**Actions**:
1. **If KB is empty or outdated**: run a full re-ingest
2. **If retrieval_min_score is too high**: lower it temporarily
3. **If LLM is ignoring context**: review system prompt + audit responses

### Incident 4: Tenant complains about rate limit

**Symptoms**: Tenant reports 429 Too Many Requests.

**Diagnosis**:
```bash
# 1. Check tenant usage
jq "select(.tenant_id == \"acme\") | .endpoint" $CIP_AUDIT_LOG_PATH | sort | uniq -c

# 2. Check rate limit config
grep "CIP_API_KEYS" .env  # see rpm per tenant
```

**Actions**:
1. **Increase tenant rate limit**: edit `CIP_API_KEYS` in env and redeploy
2. **If usage is legitimate**: consider upgrading the tenant's plan
3. **If abuse**: add 403 + temporary ban

---

## 🛡️ Security

### API Key Management

```bash
# Generate new key (Python)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Add to the list (keep old keys for rotation)
CIP_API_KEYS="key-old:tenant-a:60,key-new:tenant-a:60"
# Remove key-old after deploy (full rotation)

# Revoke compromised key
CIP_API_KEYS="key-remaining:tenant-a:60"  # without the compromised one
```

### Audit Log Compliance

- **Retention**: 90 days (LGPD/GDPR compliance)
- **Access**: only authorized SREs (chmod 600)
- **Backup**: S3 with lifecycle policy
- **PII**: we never log the full question (only 100-char preview)

### Network Security

- TLS 1.3 mandatory (Cloudflare)
- L4 rate limit at the edge (Cloudflare)
- WAF rules for SQLi, XSS, RCE patterns
- IP allowlist for admin endpoints (future)

---

## 📈 Scaling

### Vertical (single replica)

```bash
# Cloud PaaS: scale CPU/RAM (examples)
gcloud run services update cip --memory 2Gi --cpu 2
# or
aws ecs update-service --service-name cip --desired-count 1
```

**Current limit**: 1 replica with 2GB RAM. bge-large embeddings on CPU needs ~1.5GB.

### Horizontal (multi-replica)

```bash
# Cloud PaaS: multiple replicas
gcloud run services update cip --min-instances 3
# or
aws ecs update-service --service-name cip --desired-count 3
```

**Note**:
- Embeddings model loads per process (1.5GB RAM × 3 replicas = 4.5GB total)
- Consider `EMBED_PROVIDER=bedrock` to free up memory
- Metrics are in-memory (each replica has its own) — use centralized Prometheus scrape

### Embedding Offload (recommended for > 3 replicas)

```bash
EMBED_PROVIDER=bedrock  # uses Titan Embeddings via API
EMBED_MODEL=amazon.titan-embed-text-v1
EMBED_DIM=1536
```

Trade-off: +50ms latency per embedding, but frees up 1.5GB RAM per replica.

---

## 📋 Go-Live Checklist (before promoting to production)

### Infrastructure
- [ ] Postgres+pgvector provisioned with automatic backup
- [ ] App deployed to cloud PaaS with health checks configured
- [ ] Custom domain + TLS configured
- [ ] DNS records validated
- [ ] Alerts configured (Datadog/Sentry/Prometheus)

### Configuration
- [ ] `CIP_ENV=prod`
- [ ] `CIP_API_KEYS` with tenants configured
- [ ] `LLM_PROVIDER=bedrock` (not `stub`)
- [ ] `LLM_MODEL=anthropic.claude-sonnet-4-5-20250929-v1:0`
- [ ] Langfuse creds set (optional)
- [ ] Audit log path configured

### Data
- [ ] Schema applied (`db/schema.sql`)
- [ ] Full ingestion (>= 1000 chunks)
- [ ] Drift detector clean (0 pending changes)

### Quality Gate
- [ ] Pre-flight check passes (`python scripts/preflight.py` → GO)
- [ ] Eval suite passes with score >= 4.0 on all criteria
- [ ] Human review completed (5 architects × 20 cases)
- [ ] `cip_low_grounding_rate` gate does not trigger

### Security
- [ ] API keys rotated (not the dev ones)
- [ ] Audit log path with 600 permissions
- [ ] Network policies: API only accessible via Cloudflare
- [ ] Per-tenant rate limits validated
- [ ] Penetration test executed (optional)

### Operational
- [ ] Runbook published and trained with SRE
- [ ] On-call schedule defined
- [ ] Slack channel for alerts created
- [ ] API documentation published
- [ ] Grafana/Datadog dashboard configured

### Post-Deploy (first week)
- [ ] p95 latency < 5s validated in real production
- [ ] Cost per query < $0.05 (monitor AWS bill)
- [ ] Grounding rate > 80% in production
- [ ] 0 unexpected 500 errors
- [ ] Feedback from the first 3 tenants

---

## 📞 Contacts

| Role | Contact | Escalation |
|---|---|---|
| SRE on-call | PagerDuty → @sre-oncall | 24/7 |
| Tech Lead | @tech-lead-cip | Business days |
| AWS support | AWS Console → Support | 24/7 (Enterprise) |
| Langfuse support | support@langfuse.com | Business days |

---

## 📚 References

- `docs/09-plano-execucao-llm-cloud.md` — Original plan
- `docs/16-progresso-round-6.md` — Production Hardening (auth, rate limit, CI/CD)
- `docs/17-progresso-round-7.md` — Fine-tuning infra
- `docs/adr/0001-rag-first-em-vez-de-fine-tuning.md` — ADR-0001
- `docs/adr/0003-tools-read-only-para-dados-ao-vivo.md` — ADR-0003
- `scripts/preflight.py` — Pre-flight check script
- `scripts/monthly_cron.py` — Monthly cron

---

**Last updated**: 2026-08-24 | **Version**: 1.0
**Status**: Ready for operational use
