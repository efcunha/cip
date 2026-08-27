# Contrato de Integração CloudPilot → CIP (HTTP)

> **Status**: canônico. **Fontes**: `src/cip/api/app.py`, `src/cip/api/schemas.py`,
> `src/cip/api/auth.py`, `src/cip/api/health.py`. Nada aqui é especulativo — os shapes
> abaixo espelham os modelos Pydantic reais.

## 1. Princípio fundador

O CIP é um serviço de IA **HTTP-first**. O CloudPilot (e qualquer outro consumidor)
consome o CIP **exclusivamente via HTTP**:

- `POST /ask`     — pergunta de conhecimento (RAG puro, com filtros opcionais).
- `POST /analyze` — análise completa (orquestrador: RAG + tools read-only + inspeção).

**Consumidores NUNCA leem o banco do CIP.** Não há acesso cruzado a banco, nem tabela
compartilhada, nem contratos de schema. O único contrato é HTTP. Isto isola o CIP
(incluindo o modo self-contained do `docker-compose.prod.yml`, que tem Postgres próprio
`cip_postgres`) e permite corrigir o RAG/KB sem re-deploy dos consumidores.

## 2. Autenticação

- Headers por request:
  - `X-API-Key`: chave válida registrada em `CIP_API_KEYS` (`chave:tenant:rpm,...`).
  - `X-Tenant-Id`: tenant id (obrigatório em produção; opcional em dev).
- Em produção (`CIP_ENV=production`) sem `X-API-Key` → `401`; chave inválida → `403`;
  tenant mismatch → `403`. Rate limit por tenant → `429` (`Retry-After`).

## 3. `POST /ask` — RAG puro

### Request (`AskRequest`)

```json
{
  "question": "Como reduzir custo de um bucket S3 com dados frios?",  // min_length 3
  "cloud": "aws",           // optional: aws|gcp|azure|multi|architecture|case-studies
  "service": "s3",          // optional
  "category": "storage"     // optional
}
```

### Response 200 (`AskResponse`)

```json
{
  "answer": "…",
  "sources": [
    { "cloud": "aws", "service": "s3", "title": "…", "url": "…", "score": 0.85 }
  ],
  "has_grounding": true
}
```

`has_grounding=false` indica resposta sem grounding acima do `RETRIEVAL_MIN_SCORE`.
`/ask/stream` (SSE) existe como variante streaming (eventos `chunk`/`done`).

## 4. `POST /analyze` — análise completa (orquestrador)

### Request (`AnalyzeRequest`)

```json
{
  "question": "Essa VPC tem custo desproporcional?",  // min_length 3
  "cloud": "aws",              // optional
  "iac_payload": "resource \"aws_s3_bucket\" { … }",  // optional: .tf ou YAML k8s
  "react_mode": false          // optional: força modo ReAct (default: CIP_REACT_MODE)
}
```

### Response 200 (`AnalyzeResponse`)

```json
{
  "summary": "…",
  "intent": "finops",                       // nullable
  "clouds": ["aws"],                        // lista
  "findings": [
    {
      "title": "…",
      "severity": "high",                   // critical|high|medium|low
      "domain": "finops",                   // finops|security|reliability|performance|operations
      "description": "…",
      "recommendation": "…",
      "financial_impact_usd": 1200.0,       // nullable
      "effort": "low",                      // nullable: low|medium|high
      "references": ["…"]
    }
  ],
  "sources": [ { "cloud":"aws", "service":"s3", "title":"…", "url":"…", "score":0.85 } ],
  "tools_used": ["aws_cost_explorer", "aws_ec2_describe"]
}
```

`/analyze/stream` (SSE) é a variante streaming (`summary` em chunks progressivos).

## 5. Health (consumidor usa para gating/discovery)

- `GET /health/live` → `200 {"status":"alive"}` (liveness, sem dependências).
- `GET /health/ready` → `200` se DB + vector_store (chunks>0) + LLM + rate_limiter ok;
  senão `503`. O campo `vector_store.details.chunks` informa o tamanho do KB.

## 6. Notas operacionais

- **Erros**: overload → `429`; timeout do handler → `504`; falha interna → `500` (detail).
- **Readonly**: `CIP_READONLY=true` trava ações mutantes; `/ask` e `/analyze` são read-only.
- **Métricas**: `GET /metrics` (Prometheus). Documentação OpenAPI: `GET /docs`, `/openapi.json`.
- **Embeddings**: locais em CPU (default `intfloat/multilingual-e5-small`, dim 384) no
  modo self-contained; o consumidor NÃO precisa saber disso — só do contrato HTTP acima.
