# Phase 2 Features (Round 22+) — Production-grade chat

> 6 features implementadas para tornar o CIP um chat de produção para
> FinOps/K8s/multi-cloud. Assumem **infraestrutura rodando** (Docker Compose).

## 🎯 Quick start (3 passos)

```bash
# 1. Subir tudo
docker compose up -d

# 2. Aplicar migrations (002 + 003 + 004)
docker compose exec postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/002_relax_cloud_and_doc_type_constraints.sql
docker compose exec postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/003_conversations_and_feedback.sql
docker compose exec postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/004_share_tokens_and_extras.sql

# 3. Subir UI
python scripts/serve_web.py --port 8080 --api-url http://localhost:8000
# → http://localhost:8080
```

---

## 1. SSE Streaming Multi-turn

### O que faz
POST `/chat/conversations/{id}/messages?stream=true` retorna **Server-Sent Events** com chunks progressivos. Mesma história da versão não-streaming, mas com UX de ChatGPT (token por token aparece na tela).

### Formato SSE
```
event: chunk
data: {"delta": "Os 6 pilares "}

event: chunk
data: {"delta": "do AWS Well-Architected são: "}

event: chunk
data: {"delta": "1. Excelência operacional..."}

event: done
data: {"msg_id": "...", "answer": "...", "sources": [...], "latency_ms": 4530}
```

### Como testar via curl
```bash
curl -N -X POST "http://localhost:8000/chat/conversations/{conv_id}/messages" \
  -H "Content-Type: application/json" -H "X-Tenant-Id: default" \
  -d '{"question":"Quais os 6 pilares do AWS Well-Architected?","stream":true}'
```

### Status
- ✅ Endpoint funcional
- ⚠️ Chunking atual: 50 chars / 20ms (simula streaming)
- 🔜 TODO: orchestrator.handle_stream() com LLM que suporte stream_generate

---

## 2. Export + Share Link

### O que faz
- **Export markdown**: `GET /chat/conversations/{id}/export?format=md` — markdown legível com título, mensagens alternadas, fontes como footnotes
- **Export JSON**: `?format=json` — dump completo com metadados
- **Share link**: `POST /chat/conversations/{id}/share` gera um token público (UUIDv4); `GET /chat/share/{token}` acessa sem auth (read-only, com access_count)

### Como testar
```bash
# 1. Criar conversa
CONV_ID=$(curl -X POST http://localhost:8000/chat/conversations \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"title":"share-test"}' | jq -r .id)

# 2. Perguntar
curl -X POST "http://localhost:8000/chat/conversations/$CONV_ID/messages" \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"question":"O que é FinOps?"}' | jq .

# 3. Export markdown
curl "http://localhost:8000/chat/conversations/$CONV_ID/export?format=md" \
  -H "X-Tenant-Id: default" | head -20

# 4. Share link
TOKEN=$(curl -X POST "http://localhost:8000/chat/conversations/$CONV_ID/share" \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"expires_hours":24}' | jq -r .token)

# 5. Acessar sem auth
curl "http://localhost:8000/chat/share/$TOKEN" | jq .
```

### Schema
Tabela `share_tokens` (Round 22+ migration 004):
```sql
CREATE TABLE share_tokens (
    token TEXT PRIMARY KEY,  -- UUIDv4
    conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
    tenant_id TEXT,
    created_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,  -- NULL = nunca expira
    revoked_at TIMESTAMPTZ,
    access_count INT DEFAULT 0,
    metadata JSONB
);
```

---

## 3. WebSocket Push

### O que faz
- WebSocket em `ws://localhost:8000/ws/chat?tenant_id=X&conversation_id=Y`
- Server faz **broadcast** de eventos: `message_added`, `feedback_changed`, `conversation_updated`, `typing`, `ping`
- Cliente pode `subscribe` / `unsubscribe` por conversa
- **In-memory pub/sub** (dev single-pod; trocar por Redis em prod multi-pod)

### Eventos do server → client
| Evento | Quando | Payload |
|---|---|---|
| `connected` | handshake | `{tenant_id, conversation_id, server_time}` |
| `subscribed` | após subscribe | `{conversation_id}` |
| `message_added` | nova msg | `{tenant_id, conversation, message}` |
| `feedback_changed` | feedback 👍/👎 | `{tenant_id, conversation, msg_id, feedback}` |
| `typing` | user está digitando | `{tenant_id, conversation_id, is_typing}` |
| `ping` | heartbeat (30s) | `{ts}` |

### Eventos do client → server
| Evento | Payload | Efeito |
|---|---|---|
| `subscribe` | `{conversation_id}` | recebe eventos dessa conversa |
| `unsubscribe` | `{conversation_id}` | para de receber |
| `pong` | — | resposta ao ping |
| `typing` | `{conversation_id, is_typing}` | broadcast para outros |

### Como testar
```javascript
// Frontend (vanilla JS)
const ws = new WebSocket("ws://localhost:8000/ws/chat?tenant_id=default&conversation_id=" + convId);
ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.event === "message_added") {
        // Atualiza UI em tempo real (outro device adicionou msg)
    }
};
ws.send(JSON.stringify({event: "subscribe", conversation_id: convId}));
```

### Status
- ✅ Pub/sub in-memory funcional
- ✅ Heartbeat 30s
- 🔜 TODO: trocar dict in-memory por Redis pub/sub para multi-pod
- 🔜 TODO: rate limit por conexão (anti-spam)

---

## 4. JWT + RBAC + OAuth2

### Roles disponíveis
| Role | Permissões | Caso de uso |
|---|---|---|
| `admin` | `*` (tudo) | admin do tenant / platform owner |
| `member` | CRUD no seu tenant | user final do chat |
| `viewer` | read-only | auditor / observador |
| `agent` | chamadas /ask + /analyze | automação / CI |

### Fluxo de auth
```
1. Cliente faz POST /auth/dev-token (dev) OU OAuth2 password flow (prod)
2. Recebe access_token (JWT HS256 dev / RS256 prod)
3. Envia em Authorization: Bearer <token>
4. Backend valida + popula request.state.principal
5. require_permission("messages:read") checa RBAC
```

### Como gerar um JWT (dev)
```bash
# Admin
curl -X POST http://localhost:8000/auth/dev-token \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice","tenant_id":"acme","role":"admin","scopes":["*"]}'
# → {"access_token":"eyJhbGc...","token_type":"bearer","expires_in":3600,"scope":"*"}

# Usar
curl -H "Authorization: Bearer eyJhbGc..." http://localhost:8000/auth/me
# → {"sub":"alice","tenant_id":"acme","role":"admin","scopes":["*"],"permissions":["*"]}
```

### OAuth2 em prod
Em prod, **use IdP externo** (Keycloak, Auth0, Okta). O fluxo:
1. Redirecionar user para `https://idp.example.com/authorize?client_id=cip-api&...`
2. User autentica no IdP
3. IdP redireciona de volta com `code`
4. Backend troca `code` por `access_token` via POST para `/token`
5. Valida `iss`, `aud`, `exp` (config: `CIP_JWT_ISSUER`, `CIP_JWT_AUDIENCE`, `CIP_JWT_ALGORITHM=RS256`)

Configuração prod (env):
```bash
CIP_JWT_ALGORITHM=RS256
CIP_JWT_PUBLIC_KEY=<PEM public key>
CIP_JWT_ISSUER=https://idp.example.com
CIP_JWT_AUDIENCE=cip-api
```

### Status
- ✅ JWT HS256 (dev) funcional
- ✅ /auth/dev-token emite tokens com role customizado
- ✅ /auth/me retorna Principal completo
- ✅ /auth/refresh rotaciona tokens
- ✅ RBAC com 4 roles
- 🔜 TODO: OAuth2 authorization code flow real (dev tem password flow)
- 🔜 TODO: Integração com IdPs (Keycloak, Auth0)

---

## 5. Métricas Prometheus + Grafana

### Novas métricas (Phase 2)
| Métrica | Tipo | Labels | Descrição |
|---|---|---|---|
| `cip_conversations_created_total` | Counter | tenant_id | conversas criadas |
| `cip_messages_created_total` | Counter | tenant_id, role | mensagens (user/assistant) |
| `cip_feedback_total` | Counter | tenant_id, feedback | 👍 / 👎 |
| `cip_chat_latency_seconds` | Histogram | operation, tenant_id | latência por operação |
| `cip_chat_feedback_negative_ratio` | Gauge | tenant_id | ratio 👎/total |

### Como acessar
```bash
curl http://localhost:8000/metrics | grep cip_chat
# cip_chat_conversations_created_total{tenant_id="default"} 5.0
# cip_chat_messages_created_total{role="assistant",tenant_id="default"} 12.0
# cip_chat_feedback_total{feedback="up",tenant_id="default"} 3.0
# cip_chat_latency_seconds_bucket{operation="chat_message",tenant_id="default",le="5.0"} 8.0
```

### Dashboard Grafana
Arquivo: [`ops/grafana/cip-dashboard.json`](../ops/grafana/cip-dashboard.json)

**Como instalar:**
1. Abra Grafana → "+" → Import
2. Cole o conteúdo de `ops/grafana/cip-dashboard.json`
3. Configure as datasources:
   - `Prometheus` → URL `http://prometheus:9090`
   - `PostgreSQL` → conexão com `cip-postgres:5432`
4. Salve

**Painéis incluídos:**
- Conversas criadas (24h) — stat
- Mensagens por role (24h) — timeseries
- Feedback 👍/👎 ratio (24h) — gauge
- Latência p95 por tenant — timeseries
- Feedback 👎 por specialist (top 10) — table
- Custo total estimado (24h) — stat (currency)
- Conversas mais longas (top 10) — table

---

## 6. Testes de carga (locust + k6)

### locust (Python)
Arquivo: [`tests/load/locustfile.py`](../tests/load/locustfile.py)

**3 personas:**
- `ChatUser` (peso 1) — simula user realista (pergunta + feedback)
- `HeavyAsker` (peso 1) — stress puro de /ask
- `AdminScroller` (peso 1) — auditoria (lista + export)

**Como rodar:**
```bash
# 1. Instalar locust
pip install locust

# 2. Web UI (http://localhost:8089)
locust -f tests/load/locustfile.py --host=http://localhost:8000

# 3. Headless (CI)
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
  --headless --users 200 --spawn-rate 20 --run-time 60s \
  --csv=load-results
```

### k6 (JavaScript)
Arquivo: [`tests/load/k6-script.js`](../tests/load/k6-script.js)

**Stages:** ramp-up 50 → 200 → 0 (total ~70s)

**Thresholds:**
- p95 chat_message < 5s
- p99 chat_message < 15s
- chat_success rate > 99%
- chat_errors count < 10

**Como rodar:**
```bash
# 1. Instalar k6 (https://k6.io/docs/getting-started/installation)
brew install k6   # macOS
choco install k6  # Windows
# ou Docker: docker run -i grafana/k6 run - <tests/load/k6-script.js

# 2. Rodar
k6 run tests/load/k6-script.js

# 3. Com mais users
k6 run --vus 200 --duration 60s tests/load/k6-script.js

# 4. Com env custom
BASE_URL=http://staging.cip.example.com TENANT=staging k6 run tests/load/k6-script.js
```

### Targets (200 concurrent users)
- p95 latência < 5s para /chat/.../messages
- p99 latência < 15s
- error rate < 1%
- RPS > 50

---

## 🧪 Como validar tudo de uma vez

```bash
# Unit + integration tests (sem infra)
pytest tests/test_chat_multiturn.py tests/test_phase2_features.py \
       tests/test_homolog.py tests/test_round22_knowledge_areas.py -v
# 148 passed, 13 skipped (precisam de infra)

# Com infra rodando (Docker Compose up -d)
docker compose up -d
pytest tests/test_phase2_features.py::TestSSEStreaming -v
pytest tests/test_phase2_features.py::TestExport -v
pytest tests/test_phase2_features.py::TestJWTAuth -v
# Devem passar sem SKIPPED
```

## 🔮 Próximos passos (Phase 3)

- [ ] **OAuth2 + OIDC real** — integração com Keycloak/Auth0
- [ ] **Multi-pod pub/sub** — Redis para WebSocket
- [ ] **Real LLM streaming** — orchestrator.handle_stream() + OpenAI stream mode
- [ ] **Conversation export PDF** — usar weasyprint ou pandoc
- [ ] **Tenant-level rate limiting** — baseado em JWT claims
- [ ] **SAML SSO** — para enterprises com IdP SAML
- [ ] **Audit log dashboard** — Grafana panel de audit.jsonl
- [ ] **Cost attribution** — breakdown por specialist
- [ ] **Embeddings versioning** — para migrar modelos sem re-ingerir tudo
- [ ] **CI integration** — locust em pipeline, fail se p95 > 10s
