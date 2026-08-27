# Homologation with a Real LLM (Round 22+)

> Guide for validating the CIP end-to-end with a real LLM (MiniMax M3, Bedrock,
> OpenAI) in a local environment, covering **all** knowledge areas: AWS /
> GCP / Azure + **Software Architecture patterns** + **case studies**.

## 🎯 What is different about this homologation?

| | `make homolog` | `make homolog-real` |
|---|---|---|
| LLM provider | `stub` (no network) | `minimax`/`bedrock`/`openai` (REAL) |
| Expected latency | < 1s (mock) | 1–5s per query |
| Cost | $0 | ~$0.01–0.05 per query |
| Cases covered | API availability | Response quality (rubric) |
| Knowledge areas | 1 (current cloud) | **5** (aws, gcp, azure, software_arch, case_studies) |
| Gate | API health ≥ ok | Average score ≥ 60% mentions + grounding |

Use `make homolog` for a quick smoke sanity-check.
Use `make homolog-real` to validate **real model quality** before production.

---

## 🚀 Setup (3 steps)

### 1) Bring up the stack (same as classic homologation)

```bash
make homolog          # or: make homolog-fast if the KB is already populated
```

This brings up Postgres+pgvector, applies schema + migration 002, and ingests the KB
(including `architecture` + `case-studies` Round 22).

### 2) Configure the real LLM

```bash
# Option A — MiniMax M3 (default in .env.example)
export LLM_PROVIDER=minimax
export LLM_MODEL=MiniMax-M3
export LLM_API_KEY=sk-cp-YOUR-TOKEN
export LLM_BASE_URL=https://api.minimax.chat/v1

# Option B — Bedrock (Claude Sonnet 4.5)
export LLM_PROVIDER=bedrock
export LLM_MODEL=anthropic.claude-sonnet-4-5-20250929-v1:0
# AWS credentials via env (STS / SSO / IMDS)

# Option C — OpenAI
export LLM_PROVIDER=openai
export LLM_MODEL=gpt-4o
export LLM_API_KEY=sk-...
```

> **Important**: `LLM_PROVIDER=stub` is explicitly **rejected** by
> `homolog_validate.py` — you cannot homologate quality without a real LLM.

### 3) Run the homologation

```bash
# Full validation (5 knowledge areas, ~10 queries, ~30-60s)
make homolog-real

# Focus on software architecture patterns
make homolog-software-arch

# Focus on case studies / postmortems
make homolog-cases

# Script variants (fine control):
python scripts/homolog_validate.py --strict --skip-setup
python scripts/homolog_validate.py --area software_architecture
python scripts/homolog_validate.py --area case_studies
```

---

## 📊 What is evaluated?

For each query in `HOMOLOG_SUITE`, the script validates:

1. **Grounding** — does the response have `has_grounding=true` (RAG retrieved sources)?
2. **Mentions** — do all `must_mention` terms appear in the response?
3. **Latency** — < 10s/query with MiniMax M3 (1.9s p95 with stub)
4. **Cost** — estimated by response size × rate per provider
5. **Binary gate** — passes if ≥ 60% of mentions + grounding OK

Markdown + JSON reports are written to:
- `eval/results/homolog_report.md`
- `eval/results/homolog_results.json`

Sample output:
```markdown
# Homologation Report — Real LLM (minimax)

**Date**: 2026-08-24T12:34:56Z
**Provider**: `minimax`
**Cases**: 9/10 passed
**Average accuracy**: 4.30
**Average latency**: 2150 ms
**Estimated total cost**: $0.0234
**Gate**: ❌ FAILED

## By knowledge area
| Area | N | Pass | Accuracy | Latency (ms) | Cost (USD) |
|---|---|---|---|---|---|
| aws | 2 | 2/2 | 4.50 | 2100 | $0.0048 |
| software_architecture | 4 | 4/4 | 4.75 | 2300 | $0.0100 |
| case_studies | 2 | 1/2 | 3.50 | 2050 | $0.0050 |
```

---

## 🆘 Troubleshooting

| Symptom | Likely cause | Solution |
|---|---|---|
| `[FAIL] LLM_PROVIDER=stub detected` | `.env` still in dev mode | `export LLM_PROVIDER=minimax` before running |
| `connectivity error` | MiniMax API is down | Check `LLM_BASE_URL` or use Bedrock |
| Low score in `case_studies` | KB still lacks case study chunks | Run `make ingest-forum-cases` first |
| Frequent `no_grounding` | Round 22 ingestion did not run | `make schema-migrate && make ingest` |
| Timeout at 60s | Slow provider / poor network | `LLM_TIMEOUT_S=120` in `.env` |
| Cost > $0.05/query | Response too long | Lower `LLM_MAX_TOKENS=1024` |

---

## 🔗 Related useful commands

| Command | Purpose |
|---|---|
| `make homolog` | Full setup with stub LLM (smoke) |
| `make homolog-fast` | Setup without re-ingestion |
| `make homolog-real` | Full validation with real LLM + 5 areas |
| `make homolog-software-arch` | Software architecture only |
| `make homolog-cases` | Case studies only |
| `make ingest-forum-cases` | Fetch + ingest postmortems from forums |
| `make forum-fetch` | Only fetch URLs from HN/dev.to/Reddit (no ingest) |
| `make schema-migrate` | Apply pending SQL migrations |
| `make eval-strict` | Offline eval (no LLM) — static quality gate |

---

## 🐳 Container image (`target: homolog`)

The `docker-compose.yml` builds `cip-api` with `target: homolog` (multi-stage
stage of the `Dockerfile`). This stage extends the lean runtime (`base`)
with `eval/`, `tests/` and the dev deps (`pytest`), making it possible to run
`preflight`, `eval-strict` and the test suite **inside** the container — useful
in the Podman/WSL environment, where the Postgres port is not reachable from the host.

```bash
# run eval/tests inside the container
podman compose exec cip-api pytest
podman compose exec cip-api python scripts/homolog_validate.py --strict
```

> For a **real deploy**, build the `base` stage (lean image, without test
> artifacts): `docker build --target base .`.

## 📚 Next steps

- Add your own queries to `HOMOLOG_SUITE` in
  `scripts/homolog_validate.py` to cover scenarios in your domain.
- Integrate `make homolog-real --strict` into nightly CI to validate
  quality before merges into main.
- Configure Langfuse (in `.env`) for detailed tracing of each query
  and to compare latency/cost between MiniMax M3, Bedrock and OpenAI.
