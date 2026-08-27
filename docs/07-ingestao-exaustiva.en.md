# Exhaustive ingestion (coverage of ~100% of the prioritized services)

This document describes the **bulk ingestion** strategy for the official
documentation of the three clouds, complementing the curated ingestion in `sources.yaml`.

## Why not "100% of everything"

The cloud catalogs each have hundreds of services (AWS ~240, Azure ~200,
GCP ~150), with tens of thousands of pages that change every week. Ingesting
*literally everything* would produce an expensive base to maintain, full of noise (SDK
references, changelogs, localized pages) and with low signal for
architecture recommendations.

The adopted approach is **exhaustive coverage of the prioritized services**: the
curated catalog in `sources.yaml` defines *which* services matter (with
category and metadata), and the discovery layer expands each service to
**all the pages of its documentation**.

## Sources per provider

| Cloud | Discovery source | Content format |
|-------|---------------------|---------------------|
| AWS   | `<guide>/llms.txt` (official index for LLMs) | Clean Markdown via `.md` |
| GCP   | `docs.cloud.google.com/sitemap.xml` (60 sub-sitemaps) | HTML → markdown |
| Azure | `learn.microsoft.com/_sitemaps/sitemapindex.xml` (`azure_en-us_*`, `entra_en-us_*`) | HTML → markdown |

Observations:

- **AWS** is the best case: each guide exposes an `llms.txt` that lists all the
  pages, and each page has a `.md` version (clean markdown, no JS). This
  eliminates the rendering problem and produces high-quality chunks.
- **GCP** publishes sitemaps that include everything (including Java/Node/PHP SDK
  references). We filter by the product prefix derived from `sources.yaml`
  (e.g.: `/compute/docs`, `/bigquery/docs`).
- **Azure** publishes a sitemap per product **and per language**. We restrict to the
  `azure_en-us_*` sub-sitemaps (where `/en-us/azure/<service>/` lives) and
  `entra_en-us_*`, and filter by the service path.

## Estimated volume (scope=full, no limit)

| Cloud | Services | Pages |
|-------|----------|---------|
| AWS   | 45       | ~24.300 |
| GCP   | 37       | ~178.000 |
| Azure | 38       | ~21.000 |

> Numbers vary as the documentation is updated. Use `--max-pages-per-service`
> to limit during tests.

## How to use

### Preview (does not persist, only counts pages)

```bash
python -m cip.ingestion.discovery --cloud aws   --scope full
python -m cip.ingestion.discovery --cloud gcp   --scope full --limit 200
python -m cip.ingestion.discovery --cloud azure --scope full --json azure_pages.json
```

### Expanded ingestion

```bash
# Exhaustive (caution: tens of thousands of pages)
python -m cip.ingestion.ingest --scope full --expand

# Recommended to start: limit pages per service + resume
python -m cip.ingestion.ingest --scope full --cloud aws --expand \
    --max-pages-per-service 300 --resume
```

When expanding, each service is split into **batches of 40 pages**
(`EXPAND_BATCH_SIZE`). Each batch has its own progress key, so
`--resume` resumes exactly where it stopped and failures stay isolated per batch.

## Incremental (delta) ingestion — what makes automation viable

The expensive step of ingestion is **embedding** (the `SemanticSplitterNodeParser` uses
embeddings to split the text). Reprocessing ~223 thousand pages on every run
would be unviable. That is why ingestion is **incremental**:

1. Each downloaded page has a `doc_hash` (SHA-256 of the raw content).
2. Before embedding, the ingestor queries the database:
   - **unchanged** (`url` + `doc_hash` already exist) → **skipped** (no embedding);
   - **changed** (`url` exists, different `doc_hash`) → old chunks are
     removed and the page is re-ingested;
   - **new** (`url` absent) → ingested.
3. Additional dedupe by chunk `content_hash` (catches identical chunks across
   different pages).

Result: after the initial load, recurring runs only embed what
actually changed — fast and cheap.

## Automation (GitHub Actions)

The `.github/workflows/refresh-docs.yml` workflow keeps the base updated **without
human action**:

- **Scheduled weekly** (Monday, 03:00 UTC), in parallel per cloud (matrix).
- Runs `ingest --scope full --expand --resume --time-budget-min N` per cloud.
- **Cache** of sitemaps and progress between runs (less rework).
- **`--time-budget-min`** ends the job with slack within the runner limit;
  `--resume` continues on the next run.
- `workflow_dispatch` allows manual triggering with `cloud`, `max_pages_per_service`
  and `time_budget_min` as parameters.
- A `validate-links` gate runs on PRs that change `sources.yaml`.

> **Infrastructure prerequisites**: the runner must reach the pgvector database
> (via public `DB_HOST`/tunnel or a self-hosted runner). Embedding with
> `BAAI/bge-large-en-v1.5` on CPU is slow for the full corpus — it is recommended
> to do the **initial load (seed)** once on infrastructure with more resources
> (or GPU) and let CI handle only the **weekly delta**, which is light.

## Robustness

- **Cache**: downloaded sitemaps live in `src/cip/ingestion/.discovery_cache/`
  (git-ignored). Re-runs do not re-download everything; only what was missed.
- **Content filter**: the ingestor discards pages with fewer than
  `MIN_CONTENT_CHARS` (500) characters — avoids indexing empty pages or redirect
  shells.
- **Delta + dedupe**: `doc_hash` (page level) avoids re-embedding what did not
  change; `content_hash` (chunk level) avoids repeated chunks.
- **Batches**: each service is split into batches of 40 pages, with isolated failures
  and per-batch progress.
- **Parallelism**: sub-sitemap downloads are parallelized; a sub-sitemap that
  fails by timeout is only logged and recovered on the next run (cache).

## Noise filter

`discovery.py` discards URLs of low architectural value (see
`DEFAULT_EXCLUDE_PATTERNS`): SDK/CLI/API references, release notes, code samples
and — the biggest offender on GCP — **language variants** (`?hl=...`) and version
variants (`?view=...`). Each GCP page appeared ~14x (one per locale); keeping
only the canonical one dropped GCP from 178k to ~11k pages.

| Cloud | Without filter | With filter | Reduction |
|-------|-----------|-----------|---------|
| GCP   | ~178.000  | ~11.400   | −94% |
| Azure | ~21.000   | ~15.700   | −25% |
| AWS   | ~24.300   | ~24.300   | ~0 (already clean via `.md`) |
| **Total** | **~223.000** | **~51.400** | **−77%** |

## Cost/time estimate (measured on this infra)

Real benchmark (runner CPU): the small 384d model embeds ~8 chunks/s
(final embedding); with the `SemanticSplitter` (which also embeds) the effective rate
stays at ~4-6 chunks/s. Tokens/page: AWS `.md` ~2.5k (clean); GCP/Azure ~10k (HTML
with boilerplate).

| Scenario | Pages | Chunks (approx.) | Embed time (CPU) | Storage (384d) |
|---------|---------|-----------------|-------------------|----------------|
| **Curated (prod default)** | ~245 | ~2.000 | ~5-10 min | ~12 MB |
| Exhaustive filtered | ~51.400 | ~400.000 | ~20-24 h (1 CPU) | ~2.3 GB |

Cost with **managed** embeddings (optional, ~US$0.02/1M tokens):
- Curated: ~US$ 0.05 (one-time).
- Exhaustive: ~US$ 15-25 (one-time); the weekly delta afterwards is cents.

> **Practical conclusion:** the **curated** one runs smoothly on a cheap server (a few
> MB, minutes of embedding, ~0.5 GB of RAM for the model). The **exhaustive** one only makes
> sense with dedicated infrastructure (or managed embeddings) — it is not the default.

## Tuning `MIN_CONTENT_CHARS`

Kept at **500** characters: discards empty pages/redirect shells without
cutting real content. Since GCP/Azure are long pages and AWS comes in clean `.md`,
there is no gain in raising the limit; the noise cut is done by URL (above).

## Best practices / limits

- Respect `robots.txt` and each provider's terms of use. The documentation paths
  used here are public and permitted for reading.
- Prefer running the exhaustive ingestion incrementally (per cloud, with
  `--max-pages-per-service` and `--resume`) before a complete full run.
- The monthly re-ingestion (`refresh-docs.yml` workflow) keeps the knowledge
  updated without model retraining.
