-- Migration: Round 22 — knowledge areas adicionais
-- Relaxa as constraints CHECK para permitir (a) 'multi', 'architecture',
-- 'case-studies' em `cloud`, e (b) novos doc_types (postmortem,
-- case-study, engineering-blog).
--
-- Idempotente: pode rodar múltiplas vezes sem erro.
-- Aplicar com: make schema-migrate-002 (ou psql -f direto)

-- 1) Drop & recriar constraint de cloud (inclui novos pseudo-clouds)
ALTER TABLE cloud_docs
    DROP CONSTRAINT IF EXISTS cloud_docs_cloud_check;

ALTER TABLE cloud_docs
    ADD CONSTRAINT cloud_docs_cloud_check
    CHECK (cloud IN ('aws', 'gcp', 'azure', 'multi', 'architecture', 'case-studies'));

-- 2) Drop & recriar constraint de doc_type (inclui novos tipos)
ALTER TABLE cloud_docs
    DROP CONSTRAINT IF EXISTS cloud_docs_doc_type_check;

ALTER TABLE cloud_docs
    ADD CONSTRAINT cloud_docs_doc_type_check
    CHECK (doc_type IN ('guide','reference','tutorial','whitepaper','pricing',
                        'postmortem','case-study','engineering-blog'));
