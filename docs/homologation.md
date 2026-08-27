# Homologação Local — Guia Completo

> **Audiência**: Engenheiros de QA, SREs, desenvolvedores
> **Data**: 2026-08-24
> **Stack**: Podman + Python 3.11+ + CIP

---

## 🎯 O que é a Homologação?

A homologação é o ambiente **idêntico ao de produção**, mas com:
- Dados sintéticos ou mascarados
- Mock das clouds externas (`CIP_USE_MOCK_CLOUDS=true`)
- API key de dev (sem custo de Bedrock se LLM_PROVIDER=stub)
- Volume menor de dados

**Objetivo**: Validar mudanças antes de promover para produção (cloud PaaS + Bedrock real).

---

## 🚀 Setup Rápido (5 minutos)

### Opção A: Tudo automatizado (Recomendado)

```bash
# 1. Verifica pré-requisitos
podman --version    # esperado: podman 4.x+
python --version     # esperado: 3.11+

# 2. Setup completo
make homolog
# ou
python scripts/setup_homolog.py

# 3. Resultado esperado:
#    ✓ Pré-requisitos OK
#    ✓ Postgres+pgvector rodando
#    ✓ Schema aplicado
#    ✓ Ingestion MVP completa (~237 chunks)
#    ✓ Pre-flight checks passou
#    ✓ Smoke tests passaram
```

### Opção B: Manual (mais controle)

```bash
# 1. Subir só o DB
podman compose up -d db

# 2. Aguardar DB ficar pronto
sleep 5

# 3. Aplicar schema
psql "postgresql://cip:cip@localhost:5432/cip" -f db/schema.sql

# 4. Ingerir KB
make ingest

# 5. Subir API
make up

# 6. Smoke test
make smoke
```

### Opção C: Stack completa (DB + API + Web)

```bash
# Sobe tudo de uma vez
podman compose up -d db api

# Aguarda DB ficar pronto
sleep 8

# Aplica schema (primeira vez)
podman exec -it cip-db psql -U cip -d cip -f /docker-entrypoint-initdb.d/01-schema.sql

# Ingerir KB
make ingest

# Smoke test
make smoke

# Abrir Web UI
make web
# → Abre http://localhost:8080
```

---

## 🧪 Smoke Test (Validação Rápida)

```bash
# Local
make smoke

# Custom URL
python scripts/smoke_test.py --url https://homolog.cip.internal --api-key xxx

# Verbose
make smoke-verbose
```

**Output esperado**:
```
======================================================================
  CIP SMOKE TEST — http://localhost:8000
======================================================================
  [PASS] Health (público)                              (   5.2ms)
  [PASS] Liveness probe                                (   3.1ms)
  [PASS] Readiness probe                               (  45.8ms)
  [PASS] Métricas Prometheus                            (   4.0ms)
  [PASS] Ask: AWS Well-Architected                     (1850.3ms)
  [PASS] Ask: grounding com URL                        (1620.5ms)
  [PASS] Analyze: Terraform inseguro                   (2050.7ms)
  [PASS] Streaming (SSE)                               (3200.4ms)

  RESULT: 8 passed | 0 failed | 0 skipped
  [OK] TODOS os smoke tests passaram!
```

**Exit codes**:
- 0 = todos passaram
- 1 = algum falhou
- 2 = API não está acessível

---

## 🔧 Configuração (.env para homolog)

```bash
# LLM (stub ou local para homolog sem custo)
LLM_PROVIDER=stub
# Para validar com LLM real:
# LLM_PROVIDER=minimax
# LLM_MODEL=MiniMax-M3
# LLM_API_KEY=sk-cp-...
# LLM_BASE_URL=https://api.minimax.chat/v1

# Tools cloud (mock para homolog sem creds)
CIP_USE_MOCK_CLOUDS=true
# CIP_MOCK_CLOUD_URL=http://localhost:8888

# Performance
CIP_QUERY_CACHE_TTL=3600  # 1h cache (em homolog)

# Auth (em homolog pode ser desabilitado)
CIP_API_KEYS="dev-key-homolog:tenant-default:60"

# Modo
CIP_ENV=dev
LOG_LEVEL=DEBUG  # mais verboso em homolog
```

---

## 📋 Checklist de Homologação (validação manual)

Antes de promover para produção, validar:

### ✅ Infraestrutura
- [ ] DB acessível (porta 5432)
- [ ] pgvector extension instalada
- [ ] Schema aplicado (4 tabelas + 6 índices)
- [ ] KB populada (chunks > 0)

### ✅ API
- [ ] Health check retorna 200
- [ ] Liveness probe OK
- [ ] Readiness probe OK (todos os 4 checks)
- [ ] Métricas Prometheus expostas
- [ ] Audit log gravando

### ✅ Funcionalidade
- [ ] Ask com grounding (URLs oficiais)
- [ ] Ask com stream (chunks progressivos)
- [ ] Analyze detecta findings (TF inseguro → critical)
- [ ] Specialists roteiam corretamente
- [ ] ReAct mode funciona (opt-in)
- [ ] Mock cloud tools retornam dados

### ✅ Performance
- [ ] Latência p95 < 5s
- [ ] Cache hit rate > 50% (após warmup)
- [ ] Throughput > 5 req/s
- [ ] Memory < 2GB por replica

### ✅ Segurança
- [ ] API key auth funciona
- [ ] Tenant isolation funciona
- [ ] Rate limit funciona (429 após X req/min)
- [ ] Logs não vazam PII

### ✅ Operacional
- [ ] Smoke tests passam
- [ ] Pre-flight check passa
- [ ] Eval score >= 4.0 (quando LLM real disponível)
- [ ] Demo funciona end-to-end

---

## 🔄 Workflow de Homologação

```
Dev (local)             Homolog (staging)         Prod
─────────────────       ─────────────────       ────────────────
make up                  podman compose up        deploy cloud
make ingest              make ingest (real)       (skipped, KB
                                                 já populada)
make smoke               make smoke               make smoke
                         (com LLM real)           (com LLM real)
git push origin          trigger deploy           trigger deploy
                    ──>  (GitHub Actions)    ──>  (Cloud PaaS)
```

---

## 🐛 Troubleshooting

### DB não conecta
```bash
# Verifica se container está rodando
podman ps -a | grep cip-db

# Se não está, inicia
podman compose up -d db

# Logs
podman logs cip-db
```

### Schema não aplica
```bash
# Verifica se DB está pronto
podman exec cip-db pg_isready -U cip

# Aplica manualmente
podman exec -i cip-db psql -U cip -d cip < db/schema.sql
```

### Smoke test falha com 503
```bash
# Readiness probe falhou — DB provavelmente down
podman ps -a | grep cip-db
podman logs cip-db
```

### LLM não responde
```bash
# Verifica .env
grep LLM_PROVIDER .env
# Se stub: LLM_PROVIDER=stub (dev)

# Para testar com MiniMax real
LLM_PROVIDER=minimax python -m cip.api.app
```

### Reset completo (start from scratch)
```bash
# Para tudo e remove volumes
podman compose down -v
make homolog
```

---

## 📊 Comparação: Homolog vs Produção

| Aspecto | Homolog | Produção |
|---|---|---|
| **DB** | Podman local | Postgres gerenciado (RDS ou similar) |
| **LLM** | Stub ou MiniMax | Bedrock Claude Sonnet 4.5 |
| **Tools cloud** | Mock (CIP_USE_MOCK_CLOUDS=true) | Real (AWS creds) |
| **Auth** | API key de dev | API keys de tenants reais |
| **Cache** | CIP_QUERY_CACHE_TTL=3600 (testar perf) | CIP_QUERY_CACHE_TTL=3600 |
| **Logs** | stdout (verbose) | Langfuse + CloudWatch |
| **Metrics** | /metrics local | Prometheus + Datadog |
| **Deploy** | Local | CI/CD |

---

## 📚 Próximos Passos

Quando homologação está estável:

1. **Validar eval gate** com LLM real (MiniMax M3)
2. **Documentar achados** em `docs/32-homolog-results.md`
3. **Promover para produção**:
   - Deploy no PaaS escolhido (Cloud Run, App Runner, ECS, etc.)
   - Bedrock: configurar AWS creds
   - DNS: apontar para o PaaS
4. **Smoke test em produção**
5. **Monitorar** (CloudWatch, Datadog, Sentry)

**Para detalhes de produção**, ver:
- `docs/09-plano-execucao-llm-cloud.md` — plano original (10-14 semanas)
- `docs/18-production-runbook.md` — runbook completo
- `docs/23-architecture-c4.md` — arquitetura C4
- `docs/14-revisao-humana.md` — review de 5 arquitetos

---

**Status**: Homolog local pronto para validar
**Próximo**: Validação end-to-end com LLM real (Round 19+)
**Goal**: Promover para produção com confiança
