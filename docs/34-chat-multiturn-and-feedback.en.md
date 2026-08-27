# Multi-turn Chat + Feedback Loop (Round 22+)

> Adds **conversation memory** (multi-turn) and **per-message feedback** (👍/👎)
> to CIP. Resolves two critical gaps to become a production chat for FinOps/K8s/multi-cloud.

## 🎯 What changed

### Before (single-turn)
```
Usuário: "Como reduzir custo de EC2?"
CIP:    "Use Savings Plans..." (responde, esquece)

Usuário: "E se eu já tenho Reserved Instances?"
CIP:    "Use Savings Plans..." (NÃO lembra da pergunta anterior)
```

### After (multi-turn + feedback)
```
Usuário: "Como reduzir custo de EC2?"
CIP:    "Considere Savings Plans ou Reserved Instances..."  (responde)

Usuário: "E se eu já tenho Reserved Instances?"
CIP:    "Nesse caso, Savings Plans Compute oferecem mais flexibilidade..."  (lembra!)

[Usuário clica 👍]  →  feedback persistido  →  futuro fine-tuning
```

## 🏗️ Architecture

```
                ┌─────────────────────────────────────────────┐
                │  Web UI (web/)                               │
                │  - Lista de conversas na sidebar           │
                │  - Mensagens com 👍/👎 feedback bar         │
                │  - Streaming SSE                             │
                └────────────────────┬────────────────────────┘
                                     │ POST /chat/conversations/{id}/messages
                                     ▼
                ┌─────────────────────────────────────────────┐
                │  FastAPI (cip-api container)                │
                │  - POST   /chat/conversations               │
                │  - GET    /chat/conversations               │
                │  - GET    /chat/conversations/{id}          │
                │  - DELETE /chat/conversations/{id}          │
                │  - POST   /chat/conversations/{id}/messages │
                │  - POST   /chat/messages/{id}/feedback      │
                └────────────────────┬────────────────────────┘
                                     │ SQL (asyncpg pool)
                                     ▼
                ┌─────────────────────────────────────────────┐
                │  Postgres + pgvector                         │
                │  - cloud_docs        (já existia, RAG)      │
                │  - analyses          (já existia)            │
                │  - environments      (já existia)            │
                │  - findings          (já existia)            │
                │  - conversations     (NOVO - Round 22+)      │
                │  - messages          (NOVO - Round 22+)      │
                │      + feedback, feedback_note, feedback_at │
                └─────────────────────────────────────────────┘
```

## 📊 Schema (db/migrations/003_conversations_and_feedback.sql)

```sql
CREATE TABLE conversations (
    id          TEXT PRIMARY KEY,                       -- UUIDv4
    tenant_id   TEXT NOT NULL,                          -- multi-tenant isolation
    user_id     TEXT,                                   -- futuro SSO
    title       TEXT,                                   -- auto-gerado da 1ª pergunta
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE messages (
    id               TEXT PRIMARY KEY,                    -- UUIDv4
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tenant_id        TEXT NOT NULL,                       -- denormalizado p/ queries
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content          TEXT NOT NULL,                       -- pergunta ou resposta
    sources          JSONB NOT NULL DEFAULT '[]',          -- citações
    findings         JSONB NOT NULL DEFAULT '[]',
    plan             JSONB,                                -- AnalysisPlan
    tools_used       JSONB NOT NULL DEFAULT '[]',
    latency_ms       INT,
    model_name       TEXT,
    cost_estimated_usd NUMERIC(12,6),
    feedback         TEXT CHECK (feedback IS NULL OR feedback IN ('up','down')),
    feedback_note    TEXT,
    feedback_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

## 🔌 Endpoints (FastAPI router in src/cip/api/chat.py)

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/chat/conversations` | `{title?, metadata?}` | `ConversationOut` (201) |
| `GET` | `/chat/conversations?limit=&offset=` | — | `{items: [...], total: N}` |
| `GET` | `/chat/conversations/{id}` | — | `ConversationOut` + messages[] |
| `DELETE` | `/chat/conversations/{id}` | — | 204 |
| `POST` | `/chat/conversations/{id}/messages` | `{question, cloud?, iac_payload?, stream?}` | `MessageOut` (201) |
| `POST` | `/chat/messages/{id}/feedback` | `{feedback: "up"|"down", note?}` | `{msg_id, feedback, ...}` |

**Multi-tenant**: All queries filter by `tenant_id`. Trying to access another tenant's conversation returns **404** (not 403, avoids leak).

## 🧠 How multi-turn works

When you send a question, `chat.py`:

1. Loads the last 10 messages of the conversation
2. Formats as `[HISTÓRICO DA CONVERSA]\nUsuário: ...\nAssistente: ...\n[FIM]\n\n[PERGUNTA ATUAL]\n...`
3. Injects as a prefix to the question for the orchestrator
4. The orchestrator processes with the history as a system message
5. Persists user + assistant messages
6. Auto-generates title on the first message (first 80 chars)

**Why limit=10?** To avoid blowing the context window. Long history hurts retrieval (chunk similarity).

## 👍/👎 Feedback loop

After each assistant response, a bar appears:

```
[👍 Útil]  [👎 Não útil]  [(opcional) por que?...]   ✓ Obrigado!
```

POST `/chat/messages/{id}/feedback` persists to the database. Useful for:

1. **Training models** — collect `(prompt, response, 👍/👎)` pairs for fine-tuning
2. **Identifying patterns** — "75% of FinOps responses get 👎" → clear problem
3. **Auditing** — "why didn't the user like this response?"

## 🎨 UI (web/index.html + web/app.js)

### Sidebar: conversation list
- `＋` button creates a new conversation
- Click on item loads history
- `×` button deletes (with confirmation)

### Each assistant message
- Content with formatting (light markdown)
- Metadata badge: `✓ 8 fontes`, `⏱ 5.2s`
- Feedback bar below (👍/👎/optional note)

### Streaming
- Token-by-token via SSE (`/ask/stream` legacy or `chat/.../messages?stream=true` in future versions)
- Typing indicator while loading
- Auto-scroll

## 🚀 How to use

### Local (without container)
```bash
# 1. Apply migration 003
psql -U cip -d cip -h 127.0.0.1 -p 5432 -f db/migrations/003_conversations_and_feedback.sql

# 2. Start API
make up

# 3. Start UI
make web

# 4. Open http://localhost:8080
```

### With Docker Compose (recommended)
```bash
# docker-compose.yml already starts postgres + cip-api
docker compose up -d

# Apply migrations on the compose postgres
docker compose exec postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/003_conversations_and_feedback.sql

# Start UI standalone
python scripts/serve_web.py --port 8080 --api-url http://localhost:8000
```

Access `http://localhost:8080` in the browser.

## 🧪 How to test via curl

```bash
# 1. Create conversation
curl -X POST http://localhost:8000/chat/conversations \
  -H "X-Tenant-Id: default" \
  -H "Content-Type: application/json" \
  -d '{"title": "Minha sessão FinOps"}'
# → {"id": "uuid-xxx", "tenant_id": "default", ...}

# 2. Send first question
curl -X POST http://localhost:8000/chat/conversations/<uuid-xxx>/messages \
  -H "X-Tenant-Id: default" \
  -H "Content-Type: application/json" \
  -d '{"question": "Como reduzir custo de EC2?", "cloud": "aws"}'

# 3. Refine (remembers history)
curl -X POST http://localhost:8000/chat/conversations/<uuid-xxx>/messages \
  -H "X-Tenant-Id: default" \
  -H "Content-Type: application/json" \
  -d '{"question": "E se eu já tenho Reserved Instances?"}'

# 4. Give feedback
curl -X POST http://localhost:8000/chat/messages/<msg-uuid>/feedback \
  -H "X-Tenant-Id: default" \
  -H "Content-Type: application/json" \
  -d '{"feedback": "up"}'

# 5. List tenant conversations
curl http://localhost:8000/chat/conversations \
  -H "X-Tenant-Id: default"
```

## 📊 Metrics to track

| Metric | SQL Query |
|---|---|
| Feedback 👍/👎 rate per specialist | `SELECT plan->>'specialists', feedback, count(*) FROM messages GROUP BY 1,2` |
| Average latency per area | `SELECT metadata->>'area', avg(latency_ms) FROM messages WHERE role='assistant' GROUP BY 1` |
| Longest conversations | `SELECT id, count(messages) FROM conversations c JOIN messages m ON ... GROUP BY 1` |
| Total cost per day | `SELECT date(created_at), sum(cost_estimated_usd) FROM messages GROUP BY 1` |

## 🔮 Next steps

- [ ] Multi-turn SSE (`/chat/.../messages?stream=true`)
- [ ] Conversation export (markdown/JSON download)
- [ ] Share conversation via public link
- [ ] Search within a conversation (`?q=cost`)
- [ ] Tags/labels per conversation (FinOps, K8s, Security)
- [ ] WebSocket for push notifications (multi-device)
- [ ] Aggregated feedback per specialist (dashboard)
