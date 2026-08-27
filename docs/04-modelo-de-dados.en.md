# Data model

## `cloud_docs` — knowledge base (RAG)

| Column | Type | Description |
|---|---|---|
| `cloud` | text | `aws` \| `gcp` \| `azure` |
| `service` | text | e.g.: `ec2`, `bigquery`, `aks` |
| `category` | text | compute / storage / networking / pricing / security / database / observability / governance |
| `source` | text | origin, e.g.: `aws-well-architected` |
| `doc_type` | text | guide / reference / tutorial / whitepaper / pricing |
| `framework` | text | `well-architected` / `caf` / `architecture-framework` / null |
| `title`, `content`, `url`, `version` | text | content and provenance |
| `maturity` | text | basic / intermediate / advanced |
| `embedding` | vector(1024) | bge-large vector |
| `metadata` | jsonb | section, header hierarchy, tokens, ingested_at |
| `content_hash` | text | dedupe / drift detection (unique index) |

**Indexes:** HNSW on `embedding`; btree on `(cloud, service)`, `category`, `framework`.

## Operational layer

- **`environments`**: environment analyzed per tenant (`tenant_id`, `cloud`).
- **`analyses`**: each run (`question`, `answer`, `sources`, `tools_used`, `tokens_used`, `latency_ms`).
- **`findings`**: prioritized findings (`severity`, `domain`, `financial_impact_usd`, `effort`, `references`).

### Prioritization (`severity` field + derived fields in `findings`)
- `severity`: critical / high / medium / low.
- `financial_impact_usd`: estimated impact (comes from a live tool when possible).
- `effort`: low / medium / high → used for ROI = impact / effort.

## Example row in `cloud_docs`

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
