-- Cloud Intelligence Platform — schema
-- Requer a extensão pgvector (imagem pgvector/pgvector já inclui).

CREATE EXTENSION IF NOT EXISTS vector;

-- ─── Base de conhecimento (RAG) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cloud_docs (
    id          BIGSERIAL PRIMARY KEY,
    -- cloud: provedor ('aws','gcp','azure'), agregado cloud-agnostic ('multi'),
    -- ou knowledge area adicional ('architecture', 'case-studies').
    -- Round 22+: knowledge areas adicionais vivem sob 'architecture' e 'case-studies'
    -- para não poluir os 3 provedores principais. Ver cip.prompts.specialists.
    cloud       TEXT NOT NULL CHECK (cloud IN ('aws', 'gcp', 'azure', 'multi', 'architecture', 'case-studies')),
    service     TEXT NOT NULL,          -- ex: 'ec2', 'bigquery', 'aks'
    category    TEXT NOT NULL,          -- compute | storage | networking | pricing | security | database | observability | governance | architecture | case-studies
    source      TEXT NOT NULL,          -- ex: 'aws-well-architected', 'gcp-architecture-framework'
    doc_type    TEXT NOT NULL DEFAULT 'guide'  -- guide | reference | tutorial | whitepaper | pricing | postmortem | case-study | engineering-blog
                CHECK (doc_type IN ('guide','reference','tutorial','whitepaper','pricing','postmortem','case-study','engineering-blog')),
    framework   TEXT,                   -- 'well-architected' | 'caf' | 'architecture-framework' | NULL
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    url         TEXT,
    version     TEXT,                   -- versão da doc capturada
    maturity    TEXT DEFAULT 'intermediate' CHECK (maturity IN ('basic','intermediate','advanced')),
    -- Dimensão deve casar com EMBED_DIM / o modelo de embeddings configurado.
    -- Padrão: 384 (intfloat/multilingual-e5-small). Titan=1024, OpenAI 3-small=1536.
    embedding   vector(384),
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash TEXT,                  -- para detecção de drift/dedupe
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Índice vetorial (HNSW: rápido em query)
CREATE INDEX IF NOT EXISTS cloud_docs_embedding_idx
    ON cloud_docs USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Filtros por metadados
CREATE INDEX IF NOT EXISTS cloud_docs_cloud_service_idx ON cloud_docs (cloud, service);
CREATE INDEX IF NOT EXISTS cloud_docs_category_idx       ON cloud_docs (category);
CREATE INDEX IF NOT EXISTS cloud_docs_framework_idx      ON cloud_docs (framework);
CREATE UNIQUE INDEX IF NOT EXISTS cloud_docs_hash_idx    ON cloud_docs (content_hash);

-- ─── Camada operacional (histórico de análises) ───────────────────────────
CREATE TABLE IF NOT EXISTS environments (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    cloud       TEXT NOT NULL CHECK (cloud IN ('aws','gcp','azure','multi')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analyses (
    id            BIGSERIAL PRIMARY KEY,
    environment_id BIGINT REFERENCES environments(id) ON DELETE CASCADE,
    question      TEXT NOT NULL,
    answer        TEXT,
    sources       JSONB DEFAULT '[]'::jsonb,
    tools_used    JSONB DEFAULT '[]'::jsonb,
    tokens_used   INT DEFAULT 0,
    latency_ms    INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS findings (
    id          BIGSERIAL PRIMARY KEY,
    analysis_id BIGINT REFERENCES analyses(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    domain      TEXT NOT NULL,          -- finops | security | reliability | performance | operations
    description TEXT,
    recommendation TEXT,
    financial_impact_usd NUMERIC(12,2),
    effort      TEXT CHECK (effort IN ('low','medium','high')),
    "references"  JSONB DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS findings_severity_idx ON findings (severity);
CREATE INDEX IF NOT EXISTS analyses_env_idx      ON analyses (environment_id);
