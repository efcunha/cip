-- Migration: Round 22+ — Chat multi-turn + feedback loop
-- Adiciona suporte a conversas persistentes (memória entre perguntas) e
-- feedback por mensagem (👍/👎) para treinar/improve o modelo.
--
-- Idempotente: pode rodar múltiplas vezes.

-- ─── Conversations ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id           TEXT PRIMARY KEY,                    -- UUIDv4 gerado no app
    tenant_id    TEXT NOT NULL,                       -- multi-tenant isolation
    user_id      TEXT,                                -- opcional, futuro SSO
    title        TEXT,                                -- auto-gerado da 1ª pergunta
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb  -- extensibilidade
);

CREATE INDEX IF NOT EXISTS conversations_tenant_idx
    ON conversations (tenant_id, updated_at DESC);

-- ─── Messages (pertencem a uma conversation) ────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,                 -- UUIDv4
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tenant_id       TEXT NOT NULL,                    -- denormalizado p/ queries rápidas
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,                    -- pergunta ou resposta completa
    -- Metadata da resposta do assistant
    sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
    findings        JSONB NOT NULL DEFAULT '[]'::jsonb,
    plan            JSONB,                            -- AnalysisPlan (intent, specialists)
    tools_used      JSONB NOT NULL DEFAULT '[]'::jsonb,
    latency_ms      INT,
    model_name      TEXT,                             -- ex: 'MiniMax-M3'
    cost_estimated_usd NUMERIC(12, 6),
    -- Feedback (populated depois)
    feedback        TEXT CHECK (feedback IS NULL OR feedback IN ('up', 'down')),
    feedback_note   TEXT,
    feedback_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS messages_conv_idx
    ON messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS messages_tenant_idx
    ON messages (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS messages_feedback_idx
    ON messages (feedback)
    WHERE feedback IS NOT NULL;

-- ─── Atualiza updated_at da conversation quando uma message é inserida ─
CREATE OR REPLACE FUNCTION touch_conversation_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations
    SET updated_at = now()
    WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS messages_touch_conversation ON messages;
CREATE TRIGGER messages_touch_conversation
    AFTER INSERT ON messages
    FOR EACH ROW EXECUTE FUNCTION touch_conversation_updated_at();
