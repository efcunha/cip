# Chat Multi-turn + Feedback Loop (Round 22+)

> Adiciona **memória de conversa** (multi-turn) e **feedback por mensagem** (👍/👎)
> ao CIP. Resolve dois gaps críticos para virar chat de produção para FinOps/K8s/multi-cloud.

## 🎯 O que mudou

### Antes (single-turn)
```
Usuário: "Como reduzir custo de EC2?"
CIP:    "Use Savings Plans..." (responde, esquece)

Usuário: "E se eu já tenho Reserved Instances?"
CIP:    "Use Savings Plans..." (NÃO lembra da pergunta anterior)
```

### Depois (multi-turn + feedback)
```
Usuário: "Como reduzir custo de EC2?"
CIP:    "Considere Savings Plans ou Reserved Instances..."  (responde)

Usuário: "E se eu já tenho Reserved Instances?"
CIP:    "Nesse caso, Savings Plans Compute oferecem mais flexibilidade..."  (lembra!)

[Usuário clica 👍]  →  feedback persistido  →  futuro fine-tuning
```

## 🏗️ Arquitetura

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

## 🔌 Endpoints (FastAPI router em src/cip/api/chat.py)

| Método | Path | Body | Response |
|---|---|---|---|
| `POST` | `/chat/conversations` | `{title?, metadata?}` | `ConversationOut` (201) |
| `GET` | `/chat/conversations?limit=&offset=` | — | `{items: [...], total: N}` |
| `GET` | `/chat/conversations/{id}` | — | `ConversationOut` + messages[] |
| `DELETE` | `/chat/conversations/{id}` | — | 204 |
| `POST` | `/chat/conversations/{id}/messages` | `{question, cloud?, iac_payload?, stream?}` | `MessageOut` (201) |
| `POST` | `/chat/messages/{id}/feedback` | `{feedback: "up"|"down", note?}` | `{msg_id, feedback, ...}` |

**Multi-tenant**: Todas as queries filtram por `tenant_id`. Tentar acessar conversa de outro tenant retorna **404** (não 403, evita leak).

## 🧠 Como o multi-turn funciona

Quando você envia uma pergunta, o `chat.py`:

1. Carrega as últimas 10 mensagens da conversa
2. Formata como `[HISTÓRICO DA CONVERSA]\nUsuário: ...\nAssistente: ...\n[FIM]\n\n[PERGUNTA ATUAL]\n...`
3. Injeta como prefixo na pergunta para o orchestrator
4. O orchestrator processa com o histórico como system message
5. Persiste user + assistant messages
6. Auto-gera título na primeira mensagem (primeiros 80 chars)

**Por que limit=10?** Para não estourar o context window. Histórico longo prejudica retrieval (chunk similarity).

## 👍/👎 Feedback loop

Após cada resposta do assistant, aparece uma barra:

```
[👍 Útil]  [👎 Não útil]  [(opcional) por que?...]   ✓ Obrigado!
```

POST `/chat/messages/{id}/feedback` persiste no banco. Útil para:

1. **Treinar modelos** — coletar pares `(prompt, response, 👍/👎)` para fine-tuning
2. **Identificar padrões** — "75% das respostas sobre FinOps ganham 👎" → problema claro
3. **Auditoria** — "por que o usuário não gostou desta resposta?"

## 🎨 UI (web/index.html + web/app.js)

### Sidebar: lista de conversas
- Botão `＋` cria nova conversa
- Click no item carrega histórico
- Botão `×` apaga (com confirmação)

### Cada mensagem do assistant
- Conteúdo com formatação (markdown leve)
- Badge com metadata: `✓ 8 fontes`, `⏱ 5.2s`
- Barra de feedback abaixo (👍/👎/nota opcional)

### Streaming
- Token-by-token via SSE (`/ask/stream` legacy ou `chat/.../messages?stream=true` em versões futuras)
- Typing indicator enquanto carrega
- Auto-scroll

## 🚀 Como usar

### Local (sem container)
```bash
# 1. Aplica migration 003
psql -U cip -d cip -h 127.0.0.1 -p 5432 -f db/migrations/003_conversations_and_feedback.sql

# 2. Sobe API
make up

# 3. Sobe UI
make web

# 4. Abre http://localhost:8080
```

### Com Docker Compose (recomendado)
```bash
# O docker-compose.yml já sobe postgres + cip-api
docker compose up -d

# Aplica migrations no postgres do compose
docker compose exec postgres psql -U cip -d cip -f /docker-entrypoint-initdb.d/migrations/003_conversations_and_feedback.sql

# Sobe UI standalone
python scripts/serve_web.py --port 8080 --api-url http://localhost:8000
```

Acesse `http://localhost:8080` no browser.

## 🧪 Como testar via curl

```bash
# 1. Criar conversa
curl -X POST http://localhost:8000/chat/conversations \
  -H "X-Tenant-Id: default" \
  -H "Content-Type: application/json" \
  -d '{"title": "Minha sessão FinOps"}'
# → {"id": "uuid-xxx", "tenant_id": "default", ...}

# 2. Enviar primeira pergunta
curl -X POST http://localhost:8000/chat/conversations/<uuid-xxx>/messages \
  -H "X-Tenant-Id: default" \
  -H "Content-Type: application/json" \
  -d '{"question": "Como reduzir custo de EC2?", "cloud": "aws"}'

# 3. Refinar (lembra do histórico)
curl -X POST http://localhost:8000/chat/conversations/<uuid-xxx>/messages \
  -H "X-Tenant-Id: default" \
  -H "Content-Type: application/json" \
  -d '{"question": "E se eu já tenho Reserved Instances?"}'

# 4. Dar feedback
curl -X POST http://localhost:8000/chat/messages/<msg-uuid>/feedback \
  -H "X-Tenant-Id: default" \
  -H "Content-Type: application/json" \
  -d '{"feedback": "up"}'

# 5. Listar conversas do tenant
curl http://localhost:8000/chat/conversations \
  -H "X-Tenant-Id: default"
```

## 📊 Métricas para acompanhar

| Métrica | Query SQL |
|---|---|
| Feedback 👍/👎 rate por especialista | `SELECT plan->>'specialists', feedback, count(*) FROM messages GROUP BY 1,2` |
| Latência média por área | `SELECT metadata->>'area', avg(latency_ms) FROM messages WHERE role='assistant' GROUP BY 1` |
| Conversas mais longas | `SELECT id, count(messages) FROM conversations c JOIN messages m ON ... GROUP BY 1` |
| Custo total por dia | `SELECT date(created_at), sum(cost_estimated_usd) FROM messages GROUP BY 1` |

## 🔮 Próximos passos

- [ ] SSE multi-turn (`/chat/.../messages?stream=true`)
- [ ] Conversation export (markdown/JSON download)
- [ ] Compartilhar conversa via link público
- [ ] Search dentro de uma conversa (`?q=cost`)
- [ ] Tags/labels por conversa (FinOps, K8s, Security)
- [ ] WebSocket para push notifications (multi-device)
- [ ] Feedback agregado por specialist (dashboard)
