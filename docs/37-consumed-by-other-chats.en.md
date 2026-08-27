# CIP consumed by other chats (Round 22+ Phase 3)

> CIP exposes an HTTP API that other chats (cloudpilot, custom agents,
> Make/n8n, etc.) can call. The focus is: **you configure URL + token in
> their chat, and that chat consumes CIP**.

## 🎯 Concept

```
┌──────────────────────────────────────────────────────────────────┐
│  Another chat (cloudpilot / Make / custom agent / etc.)           │
│                                                                  │
│  - Has config:                                                   │
│      CIP_API_URL = "https://cip.example.com"                      │
│      CIP_API_TOKEN = "eyJhbGciOi..." (JWT)                        │
│                                                                  │
│  - When it needs canonical cloud knowledge:                       │
│      POST {CIP_API_URL}/consult                                  │
│      Headers: Authorization: Bearer {CIP_API_TOKEN}               │
│               X-Tenant-Id: {workspace_id}                        │
│      Body: {question, cloud?, service?, ...}                     │
│                                                                  │
│  - Receives response with sources (official AWS/GCP/Azure citations) │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼ HTTP
┌──────────────────────────────────────────────────────────────────┐
│  CIP (this project, D:\cip)                                      │
│                                                                  │
│  - FastAPI API running (ex: localhost:8000 or container)         │
│  - POST /consult → RAG engine → data_cloud_docs (237 chunks)    │
│  - Returns CipRagResult shape (answer, sources, has_grounding)  │
└──────────────────────────────────────────────────────────────────┘
```

## 🚀 Quick start (cloudpilot consuming CIP)

### 1. Start CIP
```bash
cd D:\cip
docker compose up -d
# API available at http://localhost:8000
```

### 2. Generate a token in CIP
```bash
# In dev (CIP_ENV=dev enabled):
curl -X POST http://localhost:8000/auth/dev-token \
  -H "Content-Type: application/json" \
  -d '{"user_id":"cloudpilot","tenant_id":"acme","role":"admin","scopes":["*"]}' | jq -r .access_token
# → eyJhbGciOiJIUzI1NiIs...

# In prod, use the OAuth2 IdP (Keycloak, Auth0, Okta) and receive the token via normal flow.
```

### 3. Configure cloudpilot
```bash
# D:\cloudpilot-deploy\.env (or .env.local)
CIP_API_URL=http://host.docker.internal:8000
CIP_API_TOKEN=eyJhbGciOiJIUzI1NiIs...
```

### 4. Restart cloudpilot
```bash
cd D:\cloudpilot-deploy
# Restart the backend
```

Done! The cloudpilot chat now consumes canonical CIP via HTTP instead
of using the local table.

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

**Fields:**
| Field | Type | Default | Description |
|---|---|---|---|
| `question` | str (1-4000) | — | Question to CIP (**required**) |
| `cloud` | str | None | Filters: `aws`, `gcp`, `azure` |
| `service` | str | None | Filters: `ec2`, `s3`, `lambda`, etc. |
| `category` | str | None | Filters: `compute`, `storage`, etc. |
| `top_k` | int (1-20) | 8 | How many chunks to return |
| `min_score` | float (0-1) | 0.80 | Minimum similarity score |
| `run_id` | str (UUID) | None | For audit log correlation |
| `prompt_hash` | str (hex) | None | SHA-256 hex (16 chars) for audit |
| `include_global` | bool | true | Also search in private corpus (if any) |

### Response (200 — with grounding)
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

### Response (200 — without grounding)
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

## 🔌 Integration with cloudpilot

### What changed
cloudpilot's `app/services/ai/cip_client.py` had `consult_official_cloud_knowledge` which imported `cip_query.query_cip_cloud_docs` **in-process** (local table).

Now there is `app/services/ai/cip_http_client.py` with the `consult_official_cloud_knowledge` function that:
1. If `CIP_API_URL` and `CIP_API_TOKEN` are configured → calls `POST {CIP_API_URL}/consult`
2. Otherwise → falls back to the in-process version (original behavior)

**Zero code in the agent needs to change.** `ToolExecutor._consult_official_cloud_knowledge` (in `tools.py`) keeps calling `consult_official_cloud_knowledge(...)` — what changed is which implementation serves it.

### Configuration (cloudpilot)
```bash
# .env
CIP_API_URL=https://cip.example.com
CIP_API_TOKEN=eyJhbGciOiJIUzI1NiIs...

# Pydantic Settings (config.py)
class Settings:
    CIP_API_URL: str = ""
    CIP_API_TOKEN: str = ""
```

### How cloudpilot uses it
```python
# In agent.py or tools.py (unchanged):
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

## 🧪 How to test locally

### 1. Start CIP
```bash
cd D:\cip
docker compose up -d
```

### 2. Verify /consult directly
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

Expected response:
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

### 3. Configure cloudpilot and test
```bash
# D:\cloudpilot-deploy\.env
CIP_API_URL=http://host.docker.internal:8000  # if cloudpilot runs in a container
# or http://localhost:8000 if it runs on the same machine
CIP_API_TOKEN=<token generated above>

# Restart cloudpilot
cd D:\cloudpilot-deploy
# (depends on how you run it — uvicorn, docker, etc.)

# Test the chat — it will show that it now calls CIP via HTTP
```

## 🎯 Why this pattern is better than in-process

| Aspect | In-process | HTTP |
|---|---|---|
| Coupling | strong (same Python) | weak (JSON contract only) |
| Versioning | requires rebuild | independent |
| Multi-tenant | depends on RLS | native via JWT claims |
| Migration cost | re-deploy everything | just adjust URLs |
| Auditing | 1 origin (CIP) | 2 correlatable origins (CIP + cloudpilot) |
| Scale | CIP and cloudpilot coupled | each scales separately |
| Latency | < 5ms (in-process) | ~50-200ms (network) — acceptable for tool calls |

## 📊 Exposed metrics

The `/consult` endpoint is instrumented with:
- `cip_chat_latency_seconds{operation="consult", tenant_id="..."}` — Histogram
- Structured log: `consult_completed` with `n_sources`, `has_grounding`, `latency_ms`, `run_id`
- Audit log (cloudpilot-side): `log_rag_query` with `cloud`, `service`, `category`

## 🔮 Next steps

- [ ] **A2A protocol** (Agent-to-Agent) for dynamic tool discovery
- [ ] **Streaming /consult** — Server-Sent Events for large responses
- [ ] **Multi-tenant dedicated KB** — `workspace_id` in query filters private corpus
- [ ] **Rate limiting** — based on JWT claims
- [ ] **Observability** — OpenTelemetry trace propagation cloudpilot → CIP
