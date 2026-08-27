-- Migration: Round 22+ Phase 2 — share tokens + extras
-- Adiciona tabela share_tokens (export público) e índices úteis para
-- queries de dashboard.

-- ─── Share tokens (export público read-only) ─────────────────────
CREATE TABLE IF NOT EXISTS share_tokens (
    token            TEXT PRIMARY KEY,                  -- UUIDv4
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tenant_id        TEXT NOT NULL,                     -- cópia para queries
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ,                       -- NULL = nunca expira
    revoked_at       TIMESTAMPTZ,                       -- NULL = ativo
    access_count     INT NOT NULL DEFAULT 0,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS share_tokens_conv_idx
    ON share_tokens (conversation_id)
    WHERE revoked_at IS NULL;

-- ─── Índices para queries de dashboard ───────────────────────────
-- Feedback 👍/👎 por specialist (usado pelo Grafana)
CREATE INDEX IF NOT EXISTS messages_feedback_down_idx
    ON messages ((plan->>'specialists'))
    WHERE feedback = 'down';

-- Latência média por dia (para trend chart)
CREATE INDEX IF NOT EXISTS messages_created_at_idx
    ON messages (created_at, latency_ms)
    WHERE role = 'assistant';
