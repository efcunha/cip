# CloudPilot → CIP Integration Contract (HTTP)

> **Status**: canonical. **Sources**: `src/cip/api/app.py`, `src/cip/api/schemas.py`,
> `src/cip/api/auth.py`, `src/cip/api/health.py`. Nothing here is speculative — the shapes
> below mirror the actual Pydantic models.

## 1. Founding principle

CIP is an **HTTP-first** AI service. CloudPilot (and any other consumer)
consumes CIP **exclusively via HTTP**:

- `POST /ask`     — knowledge question (pure RAG, with optional filters).
- `POST /analyze` — full analysis (orchestrator: RAG + read-only tools + inspection).

**Consumers NEVER read CIP's database.** There is no cross-database access, no shared
table, and no schema contracts. The only contract is HTTP. This isolates CIP
(including the self-contained mode of `docker-compose.prod.yml`, which has its own
`cip_postgres` Postgres) and allows fixing the RAG/KB without re-deploying consumers.

## 2. Authentication

- Per-request headers:
  - `X-API-Key`: valid key registered in `CIP_API_KEYS` (`key:tenant:rpm,...`).
  - `X-Tenant-Id`: tenant id (required in production; optional in dev).
- In production (`CIP_ENV=production`) without `X-API-Key` → `401`; invalid key → `403`;
  tenant mismatch → `403`. Rate limit per tenant → `429` (`Retry-After`).

## 3. `POST /ask` — pure RAG

### Request (`AskRequest`)

```json
{
  "question": "How to reduce the cost of an S3 bucket with cold data?",  // min_length 3
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

`has_grounding=false` indicates an answer without grounding above `RETRIEVAL_MIN_SCORE`.
`/ask/stream` (SSE) exists as a streaming variant (`chunk`/`done` events).

## 4. `POST /analyze` — full analysis (orchestrator)

### Request (`AnalyzeRequest`)

```json
{
  "question": "Does this VPC have disproportionate cost?",  // min_length 3
  "cloud": "aws",              // optional
  "iac_payload": "resource \"aws_s3_bucket\" { … }",  // optional: .tf or k8s YAML
  "react_mode": false          // optional: forces ReAct mode (default: CIP_REACT_MODE)
}
```

### Response 200 (`AnalyzeResponse`)

```json
{
  "summary": "…",
  "intent": "finops",                       // nullable
  "clouds": ["aws"],                        // list
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

`/analyze/stream` (SSE) is the streaming variant (`summary` in progressive chunks).

## 5. Health (the consumer uses it for gating/discovery)

- `GET /health/live` → `200 {"status":"alive"}` (liveness, no dependencies).
- `GET /health/ready` → `200` if DB + vector_store (chunks>0) + LLM + rate_limiter are ok;
  otherwise `503`. The `vector_store.details.chunks` field reports the KB size.

## 6. Operational notes

- **Errors**: overload → `429`; handler timeout → `504`; internal failure → `500` (detail).
- **Readonly**: `CIP_READONLY=true` locks mutating actions; `/ask` and `/analyze` are read-only.
- **Metrics**: `GET /metrics` (Prometheus). OpenAPI documentation: `GET /docs`, `/openapi.json`.
- **Embeddings**: local on CPU (default `intfloat/multilingual-e5-small`, dim 384) in
  self-contained mode; the consumer does NOT need to know this — only the HTTP contract above.
