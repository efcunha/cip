# Modelo de dados

## `cloud_docs` — base de conhecimento (RAG)

| Coluna | Tipo | Descrição |
|---|---|---|
| `cloud` | text | `aws` \| `gcp` \| `azure` |
| `service` | text | ex.: `ec2`, `bigquery`, `aks` |
| `category` | text | compute / storage / networking / pricing / security / database / observability / governance |
| `source` | text | origem, ex.: `aws-well-architected` |
| `doc_type` | text | guide / reference / tutorial / whitepaper / pricing |
| `framework` | text | `well-architected` / `caf` / `architecture-framework` / null |
| `title`, `content`, `url`, `version` | text | conteúdo e proveniência |
| `maturity` | text | basic / intermediate / advanced |
| `embedding` | vector(1024) | vetor bge-large |
| `metadata` | jsonb | seção, hierarquia de headers, tokens, ingested_at |
| `content_hash` | text | dedupe / detecção de drift (índice único) |

**Índices:** HNSW em `embedding`; btree em `(cloud, service)`, `category`, `framework`.

## Camada operacional

- **`environments`**: ambiente analisado por tenant (`tenant_id`, `cloud`).
- **`analyses`**: cada execução (`question`, `answer`, `sources`, `tools_used`, `tokens_used`, `latency_ms`).
- **`findings`**: achados priorizados (`severity`, `domain`, `financial_impact_usd`, `effort`, `references`).

### Priorização (campo `severity` + derivados em `findings`)
- `severity`: critical / high / medium / low.
- `financial_impact_usd`: impacto estimado (vem de tool ao vivo quando possível).
- `effort`: low / medium / high → usado para ROI = impacto / esforço.

## Exemplo de linha em `cloud_docs`

```json
{
  "cloud": "aws",
  "service": "s3",
  "category": "storage",
  "source": "aws-well-architected",
  "doc_type": "guide",
  "framework": "well-architected",
  "title": "Cost Optimization — Storage classes",
  "url": "https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/...",
  "maturity": "intermediate",
  "metadata": {"section": "Cost > Storage > S3", "chunk_tokens": 780}
}
```
