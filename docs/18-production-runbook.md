# Production Runbook — CIP Cloud Intelligence Platform

> **Data**: 2026-08-24 | **Versão**: 1.0 | **Status**: Operacional
> **Audiência**: SREs, Engenheiros de Plataforma, Arquitetos Cloud

---

## 🎯 Visão Geral

O CIP é uma LLM especialista em AWS/GCP/Azure servida como API REST. Este runbook cobre:
- Deploy inicial (Cloud PaaS)
- Operação diária (monitoramento, scaling)
- Resposta a incidentes (degradation, recovery)
- Manutenção (drift detection, re-ingestion mensal)

**SLA target:**
- Latência p95 < 5s (MVP) / < 3s (produção com Bedrock/Claude)
- Uptime ≥ 99.5% (excluindo manutenção)
- Score eval ≥ 4.0 (gate de qualidade)

---

## 📊 Arquitetura de Produção

```
┌─────────────────┐
│  Cloudflare/     │ ← Rate limit L4, DDoS
│  AWS WAF        │
└────────┬────────┘
         │
┌────────▼────────┐
│  Cloud PaaS     │ ← FastAPI + uvicorn
│  (1+ replicas)  │   - /ask, /analyze (autenticados)
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

**Componentes externos:**
- **Postgres 16 + pgvector 0.8**: vector store
- **AWS Bedrock**: Claude Sonnet 4.5 (LLM base)
- **HuggingFace**: opcional, para embeddings locais
- **Langfuse** (opcional): tracing distribuído
- **SendGrid/Slack** (opcional): alertas via webhook

---

## 🚀 Deploy Inicial

### Pré-requisitos
- Cloud PaaS account (Cloud Run, App Runner, ECS, etc.)
- Postgres 16 + pgvector (managed DB ou RDS)
- AWS account com Bedrock habilitado
- Domínio customizado (opcional)

### Passo 1: Provisionar Banco

```bash
# Cloud SQL ou managed Postgres
# (depende do PaaS escolhido)

# Ou AWS RDS
aws rds create-db-instance \
  --db-instance-identifier cip-prod \
  --db-name cip \
  --engine postgres --engine-version 16 \
  --db-instance-class db.t3.medium \
  --master-username cip --master-user-password <SECURE> \
  --enable-extension pgvector
```

### Passo 2: Configurar Environment Variables

```bash
# Obrigatórias
DATABASE_URL=postgresql://cip:<SECURE>@<HOST>:5432/cip
LLM_PROVIDER=bedrock
LLM_MODEL=anthropic.claude-sonnet-4-5-20250929-v1:0
EMBED_PROVIDER=local
EMBED_MODEL=intfloat/multilingual-e5-small
EMBED_DIM=384
CIP_API_KEYS="key-prod-abc:tenant-acme:60,key-prod-def:tenant-zenith:120"
CIP_ENV=prod
LOG_LEVEL=INFO

# Opcionais (tracing + audit)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
CIP_AUDIT_LOG_PATH=/var/log/cip/audit.jsonl
```

### Passo 3: Aplicar Schema

```bash
psql $DATABASE_URL -f db/schema.sql
```

### Passo 4: Ingestão Inicial

```bash
# MVP (~245 URLs → ~237 chunks)
python -m cip.ingestion.ingest --scope mvp

# Full (~245 URLs curadas + expand → ~5k chunks)
python -m cip.ingestion.ingest --scope full --expand
```

### Passo 5: Pre-flight Check

```bash
python scripts/preflight.py
# Esperado: [GO] Todos os checks críticos passaram.
```

### Passo 6: Deploy

```bash
# Cloud PaaS (exemplos)
gcloud run deploy --source .
# ou
aws ecs update-service ...
# ou
fly deploy

# Ou Docker (qualquer host)
docker build -t cip:latest .
docker run -d --name cip \
  -p 8000:8000 \
  -e DATABASE_URL=$DATABASE_URL \
  -e CIP_API_KEYS=$CIP_API_KEYS \
  cip:latest
```

### Passo 7: Smoke Test em Produção

```bash
# Health
curl https://api.cip.internal/health/ready

# Auth
curl -H "X-API-Key: key-prod-abc" \
     -H "X-Tenant-Id: tenant-acme" \
     -d '{"question":"O que é AWS S3?"}' \
     -H "Content-Type: application/json" \
     https://api.cip.internal/ask
```

---

## 🩺 Monitoramento

### Endpoints Críticos

| Endpoint | Função | Probe Type | SLA |
|---|---|---|---|
| `GET /health` | Liveness simples | - | < 50ms |
| `GET /health/live` | Liveness probe (k8s) | LivenessProbe | < 100ms |
| `GET /health/ready` | Readiness probe (k8s) | ReadinessProbe | < 5s |
| `GET /metrics` | Métricas Prometheus | Scraped | < 200ms |
| `POST /ask` | RAG query | Authenticated | p95 < 5s |
| `POST /analyze` | Orquestração completa | Authenticated | p95 < 8s |

### Métricas-Chave (Prometheus)

```
# Request rate por endpoint/status
cip_requests_total{endpoint="/ask",method="POST",status="200",tenant="acme"}

# Latência
cip_request_duration_seconds_bucket{endpoint="/ask",method="POST",le="5.0"}

# Grounding rate (% respostas com citação)
rate(cip_grounded_responses_total[5m]) / rate(cip_requests_total[5m])

# Findings gerados
cip_findings_total{severity="critical",domain="security",tenant="acme"}

# Specialists executados
cip_specialist_executions_total{specialist="finops",tenant="acme"}

# Errors
rate(cip_requests_total{status=~"5.."}[5m])
```

### Alertas Sugeridos (Datadog/Prometheus)

```yaml
# Latência degradada
- alert: cip_high_latency
  expr: histogram_quantile(0.95, rate(cip_request_duration_seconds_bucket[5m])) > 5
  for: 5m
  severity: warning

# Error rate alto
- alert: cip_high_error_rate
  expr: rate(cip_requests_total{status=~"5.."}[5m]) > 0.1
  for: 2m
  severity: critical

# Grounding baixo
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

Toda request gera entrada em `$CIP_AUDIT_LOG_PATH` (JSONL append-only):

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

**Retenção recomendada**: 90 dias para compliance (configurar S3 lifecycle se /var/log/cip/audit.jsonl).

---

## 🔄 Operação Diária

### Cron Jobs Configurados

| Job | Schedule | Comando | Owner |
|---|---|---|---|
| **Drift detection mensal** | `0 3 1 * *` (1º dia, 03:00 UTC) | `python scripts/monthly_cron.py` | SRE |
| **Test suite** | Cada push/PR | CI/CD | - |
| **Eval gate** | Cada push/PR | CI/CD | - |
| **Audit log rotation** | `0 0 * * *` (diário) | logrotate | SRE |
| **DB vacuum** | `0 4 * * 0` (domingo) | VACUUM ANALYZE | SRE |

### Tarefas Diárias (15min)

```bash
# 1. Health check
curl -sf https://api.cip.internal/health/ready | jq .

# 2. Verificar métricas (taxa de erro, latência)
curl -s https://api.cip.internal/metrics | grep -E "cip_requests_total{status=\"5" | head

# 3. Audit log (últimas 100 entradas, sumarizar)
tail -100 $CIP_AUDIT_LOG_PATH | jq -r '.tenant_id' | sort | uniq -c

# 4. DB health (conexões, vacuum)
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity;"
psql $DATABASE_URL -c "SELECT relname, n_live_tup, n_dead_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 5;"
```

### Tarefas Semanais (30min)

```bash
# 1. Eval score check (regressão?)
python eval/run_eval.py --api https://api.cip.internal --report-md --strict
# Esperado: GATE: [PASS] — se falhar, alertar e investigar

# 2. Drift detection manual (extra)
python scripts/monthly_reingest.py --detect-only

# 3. Audit log review (compliance)
jq -r '.status' $CIP_AUDIT_LOG_PATH | sort | uniq -c

# 4. Cost report (Bedrock dashboard)
# Verificar AWS Cost Explorer para "Claude Sonnet 4.5" usage
```

### Tarefas Mensais (2h)

```bash
# 1. Rodar cron mensal (drift + re-ingest se necessário)
python scripts/monthly_cron.py
# Esperado: 0 mudanças OU drift detectado + re-ingest OK

# 2. Avaliação humana (Quality Gate)
# - 5 arquitetos × 20 cenários = 100 reviews
# - Consolidar com eval automatizado (60% humano + 40% auto)

# 3. Capacity planning
psql $DATABASE_URL -c "SELECT pg_size_pretty(pg_database_size('cip'));"
psql $DATABASE_URL -c "SELECT count(*) FROM data_cloud_docs;"

# 4. Backup verification
# Verificar que backups automáticos do Cloud PaaS estão sendo feitos
```

---

## 🚨 Resposta a Incidentes

### Incidente 1: Latência p95 > 5s

**Sintomas**: Alerta `cip_high_latency`, dashboard Grafana mostra p95 acima de SLA.

**Diagnóstico**:
```bash
# 1. Verificar latência por endpoint
curl -s https://api.cip.internal/metrics | grep cip_request_duration_seconds_bucket | head

# 2. Verificar concorrência atual
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity;"

# 3. Verificar erros do LLM
tail -1000 /var/log/cip/app.log | grep "llm_error\|bedrock_error"
```

**Ações**:
1. **Se Bedrock lento**: escalar para Bedrock provisioned throughput (contatar AWS)
2. **Se DB lento**: verificar `n_dead_tup` (rodar VACUUM) ou `pg_stat_activity` (long-running queries)
3. **Se concorrência alta**: aumentar `MAX_CONCURRENT_REQUESTS` (env var) + escalar PaaS
4. **Se embeddings lento**: mudar `EMBED_PROVIDER` de `local` para `bedrock` (Titan)

### Incidente 2: Erro 500 sustentado

**Sintomas**: Alerta `cip_high_error_rate`.

**Diagnóstico**:
```bash
# 1. Logs estruturados
tail -500 /var/log/cip/app.log | jq 'select(.level == "error") | .event + ": " + .error'

# 2. Audit log para contexto
tail -1000 $CIP_AUDIT_LOG_PATH | jq 'select(.status >= 500) | {timestamp, endpoint, tenant_id, error}'

# 3. DB connectivity
psql $DATABASE_URL -c "SELECT 1"  # se falhar, problema de DB
```

**Ações**:
1. **Se DB down**: PaaS gerenciado tem failover automático para replica
2. **Se Bedrock quota exceeded**: verificar `aws service-quotas list-service-quotas --service-code bedrock` e solicitar increase
3. **Se Langfuse down**: tracing degrada gracefully (não bloqueia)
4. **Se resposta com grounding 0%**: KB pode estar corrompida → re-ingest

### Incidente 3: Grounding rate < 80%

**Sintomas**: Respostas sem citação, alerta `cip_low_grounding_rate`.

**Diagnóstico**:
```bash
# 1. Verificar se vector store tem dados
psql $DATABASE_URL -c "SELECT count(*) FROM data_cloud_docs;"

# 2. Verificar última ingestion
psql $DATABASE_URL -c "SELECT MAX(ingested_at) FROM data_cloud_docs;"  # se schema permitir

# 3. Verificar drift (URLs podem ter mudado)
python scripts/monthly_reingest.py --detect-only
```

**Ações**:
1. **Se KB vazia ou desatualizada**: rodar re-ingest completo
2. **Se retrieval_min_score muito alto**: diminuir temporariamente
3. **Se LLM ignorando contexto**: revisar system prompt + auditoria de respostas

### Incidente 4: Tenant reclama de rate limit

**Sintomas**: Tenant reporta 429 Too Many Requests.

**Diagnóstico**:
```bash
# 1. Verificar uso do tenant
jq "select(.tenant_id == \"acme\") | .endpoint" $CIP_AUDIT_LOG_PATH | sort | uniq -c

# 2. Verificar rate limit config
grep "CIP_API_KEYS" .env  # ver rpm por tenant
```

**Ações**:
1. **Aumentar rate limit do tenant**: editar `CIP_API_KEYS` no env e redeploy
2. **Se uso legítimo**: considerar upgrade de plano do tenant
3. **Se abuse**: adicionar 403 + ban temporário

---

## 🛡️ Segurança

### API Key Management

```bash
# Gerar nova chave (Python)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Adicionar à lista (manter keys antigas para rotação)
CIP_API_KEYS="key-old:tenant-a:60,key-new:tenant-a:60"
# Remover key-old após deploy (rotação completa)

# Revogar chave comprometida
CIP_API_KEYS="key-remaining:tenant-a:60"  # sem a comprometida
```

### Audit Log Compliance

- **Retenção**: 90 dias (compliance LGPD/GDPR)
- **Acesso**: somente SREs autorizados (chmod 600)
- **Backup**: S3 com lifecycle policy
- **PII**: nunca logamos pergunta completa (apenas preview 100 chars)

### Network Security

- TLS 1.3 obrigatório (Cloudflare)
- Rate limit L4 no edge (Cloudflare)
- WAF rules para SQLi, XSS, RCE patterns
- IP allowlist para endpoints admin (futuro)

---

## 📈 Scaling

### Vertical (single replica)

```bash
# Cloud PaaS: escalar CPU/RAM (exemplos)
gcloud run services update cip --memory 2Gi --cpu 2
# ou
aws ecs update-service --service-name cip --desired-count 1
```

**Limite atual**: 1 replica com 2GB RAM. Embeddings bge-large em CPU precisa de ~1.5GB.

### Horizontal (multi-replica)

```bash
# Cloud PaaS: múltiplas replicas
gcloud run services update cip --min-instances 3
# ou
aws ecs update-service --service-name cip --desired-count 3
```

**Atenção**:
- Embeddings modelo carrega por processo (1.5GB RAM × 3 replicas = 4.5GB total)
- Considerar `EMBED_PROVIDER=bedrock` para liberar memória
- Métricas são in-memory (cada replica tem suas próprias) — usar scrape Prometheus centralizado

### Embedding Offload (recomendado para > 3 replicas)

```bash
EMBED_PROVIDER=bedrock  # usa Titan Embeddings via API
EMBED_MODEL=amazon.titan-embed-text-v1
EMBED_DIM=1536
```

Trade-off: latência +50ms por embedding, mas libera 1.5GB RAM por replica.

---

## 📋 Checklist de Go-Live (antes de promover para produção)

### Infraestrutura
- [ ] Postgres+pgvector provisionado com backup automático
- [ ] App deployado no cloud PaaS com health checks configurados
- [ ] Domínio customizado + TLS configurado
- [ ] DNS records validados
- [ ] Alertas configurados (Datadog/Sentry/Prometheus)

### Configuração
- [ ] `CIP_ENV=prod`
- [ ] `CIP_API_KEYS` com tenants configurados
- [ ] `LLM_PROVIDER=bedrock` (não `stub`)
- [ ] `LLM_MODEL=anthropic.claude-sonnet-4-5-20250929-v1:0`
- [ ] Langfuse creds setadas (opcional)
- [ ] Audit log path configurado

### Dados
- [ ] Schema aplicado (`db/schema.sql`)
- [ ] Ingestion completa (>= 1000 chunks)
- [ ] Drift detector limpo (0 mudanças pendentes)

### Quality Gate
- [ ] Pre-flight check passa (`python scripts/preflight.py` → GO)
- [ ] Eval suite passa com score >= 4.0 em todos os critérios
- [ ] Review humana completada (5 arquitetos × 20 casos)
- [ ] Gate `cip_low_grounding_rate` não dispara

### Segurança
- [ ] API keys rotacionadas (não são as de dev)
- [ ] Audit log path com permissões 600
- [ ] Network policies: API só acessível via Cloudflare
- [ ] Rate limits por tenant validados
- [ ] Penetration test executado (opcional)

### Operacional
- [ ] Runbook publicado e treinado com SRE
- [ ] On-call schedule definido
- [ ] Slack channel para alertas criado
- [ ] Documentação de API publicada
- [ ] Dashboard Grafana/Datadog configurado

### Pós-Deploy (primeira semana)
- [ ] Latência p95 < 5s validada em produção real
- [ ] Custo por query < $0.05 (acompanhar AWS bill)
- [ ] Grounding rate > 80% em produção
- [ ] 0 erros 500 não esperados
- [ ] Feedback dos 3 primeiros tenants

---

## 📞 Contatos

| Papel | Contato | Escala |
|---|---|---|
| SRE on-call | PagerDuty → @sre-oncall | 24/7 |
| Tech Lead | @tech-lead-cip | Dias úteis |
| AWS support | AWS Console → Support | 24/7 (Enterprise) |
| Langfuse support | support@langfuse.com | Dias úteis |

---

## 📚 Referências

- `docs/09-plano-execucao-llm-cloud.md` — Plano original
- `docs/16-progresso-round-6.md` — Production Hardening (auth, rate limit, CI/CD)
- `docs/17-progresso-round-7.md` — Fine-tuning infra
- `docs/adr/0001-rag-first-em-vez-de-fine-tuning.md` — ADR-0001
- `docs/adr/0003-tools-read-only-para-dados-ao-vivo.md` — ADR-0003
- `scripts/preflight.py` — Pre-flight check script
- `scripts/monthly_cron.py` — Cron mensal

---

**Última atualização**: 2026-08-24 | **Versão**: 1.0
**Status**: Pronto para uso operacional
