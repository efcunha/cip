# CIP consumido por outros chats (Round 22+ Phase 3)

> O CIP expõe uma API HTTP que outros chats (cloudpilot, agentes custom,
> Make/n8n, etc.) podem chamar. O foco é: **você configura URL + token no
> chat dele, e o chat consome o CIP**.

## 🎯 Conceito

```
┌──────────────────────────────────────────────────────────────────┐
│  Outro chat (cloudpilot / Make / agente custom / etc.)            │
│                                                                  │
│  - Tem config:                                                   │
│      CIP_API_URL = "https://cip.example.com"                      │
│      CIP_API_TOKEN = "eyJhbGciOi..." (JWT)                        │
│                                                                  │
│  - Quando precisa de conhecimento canônico sobre cloud:           │
│      POST {CIP_API_URL}/consult                                  │
│      Headers: Authorization: Bearer {CIP_API_TOKEN}               │
│               X-Tenant-Id: {workspace_id}                        │
│      Body: {question, cloud?, service?, ...}                     │
│                                                                  │
│  - Recebe resposta com sources (citações oficiais AWS/GCP/Azure)  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼ HTTP
┌──────────────────────────────────────────────────────────────────┐
│  CIP (este projeto, C:\Projetos\cip)                                      │
│                                                                  │
│  - API FastAPI rodando (ex: localhost:8000 ou container)         │
│  - POST /consult → RAG engine → data_cloud_docs (237 chunks)    │
│  - Retorna shape CipRagResult (answer, sources, has_grounding)  │
└──────────────────────────────────────────────────────────────────┘
```

## 🚀 Quick start (cloudpilot consumindo CIP)

### 1. Suba o CIP
```bash
cd C:\Projetos\cip
docker compose up -d
# API disponível em http://localhost:8000
```

### 2. Gere um token no CIP
```bash
# Em dev (CIP_ENV=dev habilitado):
curl -X POST http://localhost:8000/auth/dev-token \
  -H "Content-Type: application/json" \
  -d '{"user_id":"cloudpilot","tenant_id":"acme","role":"admin","scopes":["*"]}' | jq -r .access_token
# → eyJhbGciOiJIUzI1NiIs...

# Em prod, use o IdP OAuth2 (Keycloak, Auth0, Okta) e receba o token via fluxo normal.
```

### 3. Configure o cloudpilot
```bash
# C:\Projetos\cloudpilot-deploy\.env (ou .env.local)
CIP_API_URL=http://host.docker.internal:8000
CIP_API_TOKEN=eyJhbGciOiJIUzI1NiIs...
```

### 4. Reinicie o cloudpilot
```bash
cd C:\Projetos\cloudpilot-deploy
# Reiniciar o backend
```

Pronto! O chat do cloudpilot agora consome o CIP canônico via HTTP em vez
de usar a tabela local.

## 📋 Endpoint `POST /consult` (CIP)

### Request
```http
POST /consult
Authorization: Bearer {JWT}
Content-Type: application/json
X-Tenant-Id: {workspace_id}
```

```json
{
  "question": "Quais são os 6 pilares do AWS Well-Architected Framework?",
  "cloud": "aws",
  "service": "ec2",
  "category": "compute",
  "top_k": 8,
  "min_score": 0.80,
  "run_id": "uuid-do-call-upstream",
  "prompt_hash": "abc123def456",
  "include_global": true
}
```

**Campos:**
| Campo | Tipo | Default | Descrição |
|---|---|---|---|
| `question` | str (1-4000) | — | Pergunta ao CIP (**required**) |
| `cloud` | str | None | Filtra: `aws`, `gcp`, `azure` |
| `service` | str | None | Filtra: `ec2`, `s3`, `lambda`, etc. |
| `category` | str | None | Filtra: `compute`, `storage`, etc. |
| `top_k` | int (1-20) | 8 | Quantos chunks retornar |
| `min_score` | float (0-1) | 0.80 | Score mínimo de similaridade |
| `run_id` | str (UUID) | None | Para correlação de audit log |
| `prompt_hash` | str (hex) | None | SHA-256 hex (16 chars) para audit |
| `include_global` | bool | true | Buscar também em corpus privado (se houver) |

### Response (200 — com grounding)
```json
{
  "answer": "Os 6 pilares do AWS Well-Architected Framework são: 1. Excelência operacional, 2. Segurança, ...",
  "sources": [
    {
      "cloud": "aws",
      "service": "well-architected",
      "title": "AWS Well-Architected Framework — Overview",
      "url": "https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html",
      "score": 0.91,
      "doc_id": 42,
      "source_version": "v1.0",
      "timestamp": "2024-01-15T10:00:00Z",
      "content_preview": "The AWS Well-Architected Framework helps cloud architects build...",
      "workspace_id": null,
      "is_global": true,
      "source": "aws-docs",
      "canonical_url": "https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html",
      "quarantined": false,
      "marked": false
    }
  ],
  "has_grounding": true,
  "refusal_reason": null,
  "run_id": "uuid-do-call-upstream",
  "latency_ms": 1234
}
```

### Response (200 — sem grounding)
```json
{
  "answer": "",
  "sources": [],
  "has_grounding": false,
  "refusal_reason": "no_grounding_above_min_score",
  "run_id": "...",
  "latency_ms": 850
}
```

### Response (500)
```json
{
  "detail": "consult failed: <erro do engine RAG>"
}
```

## 🔌 Integração com cloudpilot

### O que mudou
O `app/services/ai/cip_client.py` do cloudpilot tinha `consult_official_cloud_knowledge` que importava `cip_query.query_cip_cloud_docs` **in-process** (tabela local).

Agora existe `app/services/ai/cip_http_client.py` com a função `consult_official_cloud_knowledge` que:
1. Se `CIP_API_URL` e `CIP_API_TOKEN` estão configurados → chama `POST {CIP_API_URL}/consult`
2. Senão → fallback para a versão in-process (comportamento original)

**Zero código no agent precisa mudar.** O `ToolExecutor._consult_official_cloud_knowledge` (em `tools.py`) continua chamando `consult_official_cloud_knowledge(...)` — o que mudou é qual implementação atende.

### Configuração (cloudpilot)
```bash
# .env
CIP_API_URL=https://cip.example.com
CIP_API_TOKEN=eyJhbGciOiJIUzI1NiIs...

# Settings Pydantic (config.py)
class Settings:
    CIP_API_URL: str = ""
    CIP_API_TOKEN: str = ""
```

### Como o cloudpilot usa
```python
# Em agent.py ou tools.py (inalterado):
result = await consult_official_cloud_knowledge(
    workspace_id=ctx.workspace_id,
    question="Quais os 6 pilares do AWS Well-Architected?",
    cloud="aws",
    run_id=current_run_id,
    prompt_hash=hash_prompt(question),
)
# result.sources tem o shape CipRagResult (igual ao in-process)
for src in result.sources:
    print(src["title"], src["url"], src["score"])
```

## 🧪 Como testar localmente

### 1. Suba o CIP
```bash
cd C:\Projetos\cip
docker compose up -d
```

### 2. Verifique o /consult direto
```bash
TOKEN=$(curl -sX POST http://localhost:8000/auth/dev-token \
  -H "Content-Type: application/json" \
  -d '{"user_id":"smoke","tenant_id":"smoke","role":"admin"}' | jq -r .access_token)

curl -sX POST http://localhost:8000/consult \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: smoke" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Quais os 6 pilares do AWS Well-Architected?",
    "cloud": "aws"
  }' | jq .
```

Resposta esperada:
```json
{
  "answer": "Os 6 pilares são: 1. Excelência operacional...",
  "sources": [
    {
      "cloud": "aws",
      "service": "well-architected",
      "title": "AWS Well-Architected Framework — Overview",
      "url": "https://docs.aws.amazon.com/...",
      "score": 0.91,
      "doc_id": 42,
      ...
    }
  ],
  "has_grounding": true,
  "refusal_reason": null,
  "run_id": "...",
  "latency_ms": 1234
}
```

### 3. Configure o cloudpilot e teste
```bash
# C:\Projetos\cloudpilot-deploy\.env
CIP_API_URL=http://host.docker.internal:8000  # se cloudpilot roda em container
# ou http://localhost:8000 se roda na mesma máquina
CIP_API_TOKEN=<token gerado acima>

# Reinicia o cloudpilot
cd C:\Projetos\cloudpilot-deploy
# (depende de como você roda — uvicorn, docker, etc.)

# Testa o chat — vai aparecer que agora ele chama o CIP via HTTP
```

## 🎯 Por que este padrão é melhor que in-process

| Aspecto | In-process | HTTP |
|---|---|---|
| Acoplamento | forte (mesmo Python) | fraco (só contrato JSON) |
| Versionamento | precisa rebuild | independente |
| Multi-tenant | depende de RLS | nativo via JWT claims |
| Custo de migração | re-deploy tudo | só ajusta URLs |
| Auditoria | 1 origem (CIP) | 2 origens correlacionáveis (CIP + cloudpilot) |
| Escala | CIP e cloudpilot acoplados | cada um escala separado |
| Latência | < 5ms (in-process) | ~50-200ms (rede) — aceitável para tool calls |

## 📊 Métricas expostas

O endpoint `/consult` é instrumentado com:
- `cip_chat_latency_seconds{operation="consult", tenant_id="..."}` — Histogram
- Log estruturado: `consult_completed` com `n_sources`, `has_grounding`, `latency_ms`, `run_id`
- Audit log (cloudpilot-side): `log_rag_query` com `cloud`, `service`, `category`

## 🔮 Próximos passos

- [ ] **A2A protocol** (Agent-to-Agent) para descoberta dinâmica de tools
- [ ] **Streaming /consult** — Server-Sent Events para respostas grandes
- [ ] **Multi-tenant dedicated KB** — `workspace_id` em query filtra corpus privado
- [ ] **Rate limiting** — baseado em JWT claims
- [ ] **Observability** — OpenTelemetry trace propagation cloudpilot → CIP
