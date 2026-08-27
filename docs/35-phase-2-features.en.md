# Phase 2 Features (Round 22+) — Production-grade chat

> 6 features implemented to make CIP a production chat for
> FinOps/K8s/multi-cloud. They assume **running infrastructure** (Docker Compose).

## 🎯 Quick start (3 steps)

```bash
# 1. Start everything
docker compose up -d

# 2. Apply migrations (002 + 003 + 004)
docker compose exec postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/002_relax_cloud_and_doc_type_constraints.sql
docker compose exec postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/003_conversations_and_feedback.sql
docker compose exec postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/004_share_tokens_and_extras.sql

# 3. Start UI
python scripts/serve_web.py --port 8080 --api-url http://localhost:8000
# → http://localhost:8080
```

---

## 1. Multi-turn SSE Streaming

### What it does
POST `/chat/conversations/{id}/messages?stream=true` returns **Server-Sent Events** with progressive chunks. Same story as the non-streaming version, but with a ChatGPT UX (token by token appears on screen).

### SSE format
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

### How to test via curl
```bash
curl -N -X POST "http://localhost:8000/chat/conversations/{conv_id}/messages" \
  -H "Content-Type: application/json" -H "X-Tenant-Id: default" \
  -d '{"question":"Quais os 6 pilares do AWS Well-Architected?","stream":true}'
```

### Status
- ✅ Endpoint functional
- ⚠️ Current chunking: 50 chars / 20ms (simulates streaming)
- 🔜 TODO: orchestrator.handle_stream() with LLM that supports stream_generate

---

## 2. Export + Share Link

### What it does
- **Export markdown**: `GET /chat/conversations/{id}/export?format=md` — readable markdown with title, alternating messages, sources as footnotes
- **Export JSON**: `?format=json` — full dump with metadata
- **Share link**: `POST /chat/conversations/{id}/share` generates a public token (UUIDv4); `GET /chat/share/{token}` accesses without auth (read-only, with access_count)

### How to test
```bash
# 1. Create conversation
CONV_ID=$(curl -X POST http://localhost:8000/chat/conversations \
  -H "X-Tenant-Id: default" -H "Content-Type: application/json" \
  -d '{"title":"share-test"}' | jq -r .id)

# 2. Ask
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

# 5. Access without auth
curl "http://localhost:8000/chat/share/$TOKEN" | jq .
```

### Schema
`share_tokens` table (Round 22+ migration 004):
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

### What it does
- WebSocket at `ws://localhost:8000/ws/chat?tenant_id=X&conversation_id=Y`
- Server **broadcasts** events: `message_added`, `feedback_changed`, `conversation_updated`, `typing`, `ping`
- Client can `subscribe` / `unsubscribe` per conversation
- **In-memory pub/sub** (dev single-pod; switch to Redis in multi-pod prod)

### Server → client events
| Event | When | Payload |
|---|---|---|
| `connected` | handshake | `{tenant_id, conversation_id, server_time}` |
| `subscribed` | after subscribe | `{conversation_id}` |
| `message_added` | new msg | `{tenant_id, conversation, message}` |
| `feedback_changed` | feedback 👍/👎 | `{tenant_id, conversation, msg_id, feedback}` |
| `typing` | user is typing | `{tenant_id, conversation_id, is_typing}` |
| `ping` | heartbeat (30s) | `{ts}` |

### Client → server events
| Event | Payload | Effect |
|---|---|---|
| `subscribe` | `{conversation_id}` | receives events from this conversation |
| `unsubscribe` | `{conversation_id}` | stops receiving |
| `pong` | — | response to ping |
| `typing` | `{conversation_id, is_typing}` | broadcast to others |

### How to test
```javascript
// Frontend (vanilla JS)
const ws = new WebSocket("ws://localhost:8000/ws/chat?tenant_id=default&conversation_id=" + convId);
ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.event === "message_added") {
        // Updates UI in real time (another device added a msg)
    }
};
ws.send(JSON.stringify({event: "subscribe", conversation_id: convId}));
```

### Status
- ✅ In-memory pub/sub functional
- ✅ 30s heartbeat
- 🔜 TODO: switch in-memory dict to Redis pub/sub for multi-pod
- 🔜 TODO: rate limit per connection (anti-spam)

---

## 4. JWT + RBAC + OAuth2

### Available roles
| Role | Permissions | Use case |
|---|---|---|
| `admin` | `*` (everything) | tenant admin / platform owner |
| `member` | CRUD in your tenant | end chat user |
| `viewer` | read-only | auditor / observer |
| `agent` | /ask + /analyze calls | automation / CI |

### Auth flow
```
1. Client does POST /auth/dev-token (dev) OR OAuth2 password flow (prod)
2. Receives access_token (JWT HS256 dev / RS256 prod)
3. Sends in Authorization: Bearer <token>
4. Backend validates + populates request.state.principal
5. require_permission("messages:read") checks RBAC
```

### How to generate a JWT (dev)
```bash
# Admin
curl -X POST http://localhost:8000/auth/dev-token \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice","tenant_id":"acme","role":"admin","scopes":["*"]}'
# → {"access_token":"eyJhbGc...","token_type":"bearer","expires_in":3600,"scope":"*"}

# Use
curl -H "Authorization: Bearer eyJhbGc..." http://localhost:8000/auth/me
# → {"sub":"alice","tenant_id":"acme","role":"admin","scopes":["*"],"permissions":["*"]}
```

### OAuth2 in prod
In prod, **use an external IdP** (Keycloak, Auth0, Okta). The flow:
1. Redirect user to `https://idp.example.com/authorize?client_id=cip-api&...`
2. User authenticates at the IdP
3. IdP redirects back with `code`
4. Backend exchanges `code` for `access_token` via POST to `/token`
5. Validates `iss`, `aud`, `exp` (config: `CIP_JWT_ISSUER`, `CIP_JWT_AUDIENCE`, `CIP_JWT_ALGORITHM=RS256`)

Production configuration (env):
```bash
CIP_JWT_ALGORITHM=RS256
CIP_JWT_PUBLIC_KEY=<PEM public key>
CIP_JWT_ISSUER=https://idp.example.com
CIP_JWT_AUDIENCE=cip-api
```

### Status
- ✅ JWT HS256 (dev) functional
- ✅ /auth/dev-token issues tokens with custom role
- ✅ /auth/me returns full Principal
- ✅ /auth/refresh rotates tokens
- ✅ RBAC with 4 roles
- 🔜 TODO: real OAuth2 authorization code flow (dev has password flow)
- 🔜 TODO: Integration with IdPs (Keycloak, Auth0)

---

## 5. Prometheus + Grafana Metrics

### New metrics (Phase 2)
| Metric | Type | Labels | Description |
|---|---|---|---|
| `cip_conversations_created_total` | Counter | tenant_id | created conversations |
| `cip_messages_created_total` | Counter | tenant_id, role | messages (user/assistant) |
| `cip_feedback_total` | Counter | tenant_id, feedback | 👍 / 👎 |
| `cip_chat_latency_seconds` | Histogram | operation, tenant_id | latency per operation |
| `cip_chat_feedback_negative_ratio` | Gauge | tenant_id | 👎/total ratio |

### How to access
```bash
curl http://localhost:8000/metrics | grep cip_chat
# cip_chat_conversations_created_total{tenant_id="default"} 5.0
# cip_chat_messages_created_total{role="assistant",tenant_id="default"} 12.0
# cip_chat_feedback_total{feedback="up",tenant_id="default"} 3.0
# cip_chat_latency_seconds_bucket{operation="chat_message",tenant_id="default",le="5.0"} 8.0
```

### Grafana Dashboard
File: [`ops/grafana/cip-dashboard.json`](../ops/grafana/cip-dashboard.json)

**How to install:**
1. Open Grafana → "+" → Import
2. Paste the content of `ops/grafana/cip-dashboard.json`
3. Configure the datasources:
   - `Prometheus` → URL `http://prometheus:9090`
   - `PostgreSQL` → connection to `cip-postgres:5432`
4. Save

**Included panels:**
- Created conversations (24h) — stat
- Messages per role (24h) — timeseries
- Feedback 👍/👎 ratio (24h) — gauge
- p95 latency per tenant — timeseries
- Feedback 👎 per specialist (top 10) — table
- Estimated total cost (24h) — stat (currency)
- Longest conversations (top 10) — table

---

## 6. Load tests (locust + k6)

### locust (Python)
File: [`tests/load/locustfile.py`](../tests/load/locustfile.py)

**3 personas:**
- `ChatUser` (weight 1) — simulates a realistic user (question + feedback)
- `HeavyAsker` (weight 1) — pure /ask stress
- `AdminScroller` (weight 1) — auditing (list + export)

**How to run:**
```bash
# 1. Install locust
pip install locust

# 2. Web UI (http://localhost:8089)
locust -f tests/load/locustfile.py --host=http://localhost:8000

# 3. Headless (CI)
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
  --headless --users 200 --spawn-rate 20 --run-time 60s \
  --csv=load-results
```

### k6 (JavaScript)
File: [`tests/load/k6-script.js`](../tests/load/k6-script.js)

**Stages:** ramp-up 50 → 200 → 0 (total ~70s)

**Thresholds:**
- p95 chat_message < 5s
- p99 chat_message < 15s
- chat_success rate > 99%
- chat_errors count < 10

**How to run:**
```bash
# 1. Install k6 (https://k6.io/docs/getting-started/installation)
brew install k6   # macOS
choco install k6  # Windows
# or Docker: docker run -i grafana/k6 run - <tests/load/k6-script.js

# 2. Run
k6 run tests/load/k6-script.js

# 3. With more users
k6 run --vus 200 --duration 60s tests/load/k6-script.js

# 4. With custom env
BASE_URL=http://staging.cip.example.com TENANT=staging k6 run tests/load/k6-script.js
```

### Targets (200 concurrent users)
- p95 latency < 5s for /chat/.../messages
- p99 latency < 15s
- error rate < 1%
- RPS > 50

---

## 🧪 How to validate everything at once

```bash
# Unit + integration tests (without infra)
pytest tests/test_chat_multiturn.py tests/test_phase2_features.py \
       tests/test_homolog.py tests/test_round22_knowledge_areas.py -v
# 148 passed, 13 skipped (require infra)

# With running infra (Docker Compose up -d)
docker compose up -d
pytest tests/test_phase2_features.py::TestSSEStreaming -v
pytest tests/test_phase2_features.py::TestExport -v
pytest tests/test_phase2_features.py::TestJWTAuth -v
# Should pass without SKIPPED
```

## 🔮 Next steps (Phase 3)

- [ ] **Real OAuth2 + OIDC** — integration with Keycloak/Auth0
- [ ] **Multi-pod pub/sub** — Redis for WebSocket
- [ ] **Real LLM streaming** — orchestrator.handle_stream() + OpenAI stream mode
- [ ] **Conversation export PDF** — use weasyprint or pandoc
- [ ] **Tenant-level rate limiting** — based on JWT claims
- [ ] **SAML SSO** — for enterprises with SAML IdP
- [ ] **Audit log dashboard** — Grafana panel of audit.jsonl
- [ ] **Cost attribution** — breakdown per specialist
- [ ] **Embeddings versioning** — to migrate models without re-ingesting everything
- [ ] **CI integration** — locust in pipeline, fail if p95 > 10s
