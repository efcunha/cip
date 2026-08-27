# CIP — C4 Architecture

> **Date**: 2026-08-24 | **Version**: 1.0
> **Model**: C4 (Context, Container, Component, Code) — Simon Brown
> **Audience**: Engineers, Architects, SREs

---

## 1. System Context (C1)

**Context diagram**: shows CIP and how it relates to users and external systems.

```mermaid
graph TB
    User[👤 Cloud Engineer /<br/>SRE / Architect]
    API[🤖 CIP API<br/>LLM especialista<br/>AWS/GCP/Azure]
    Bedrock[☁️ AWS Bedrock<br/>Claude Sonnet 4.5]
    PG[(🗄️ Postgres<br/>+ pgvector)]
    CW[☁️ CloudWatch<br/>Observability]
    LF[📊 Langfuse<br/>Tracing opcional]
    Mock[🧪 Mock Cloud APIs<br/>Dev/CI only]

    User -->|HTTPS /ask<br/>/analyze| API
    API -->|Embeddings +<br/>vector search| PG
    API -->|LLM calls| Bedrock
    API -->|Traces| LF
    API -->|Metrics| CW
    API -.->|Mock mode<br/>(dev/CI)| Mock
```

**Personas and usage:**
- **Cloud Engineer**: asks technical questions, receives answers with citations
- **SRE**: analyzes K8s/Terraform manifests, receives prioritized findings
- **Architect**: compares multi-cloud options, receives trade-off tables

**External systems:**
- **Postgres + pgvector**: vector store for RAG
- **AWS Bedrock**: LLM (Claude Sonnet 4.5)
- **Langfuse** (optional): distributed tracing
- **CloudWatch** / Datadog: metrics/logs
- **Mock Cloud APIs** (dev/CI only): emulates AWS/Azure/GCP for testing

---

## 2. Container Diagram (C2)

**Decomposition into containers** (deployable units):

```mermaid
graph TB
    subgraph "Cloud PaaS / Kubernetes"
        API[🚀 cip-api<br/>FastAPI + uvicorn<br/>:8000<br/>Stateless]
        Worker[⚙️ cip-worker<br/>Celery worker<br/>Ingestion + cron]
    end

    subgraph "Database"
        PG[(🗄️ Postgres 16<br/>+ pgvector 0.8<br/>Cloud SQL/RDS)]
    end

    subgraph "External"
        Bedrock[☁️ Bedrock<br/>Claude Sonnet 4.5]
        CW[📈 CloudWatch]
        LF[📊 Langfuse]
        Mock[🧪 Mock Server<br/>scripts/mock_cloud_server]
    end

    Client[👤 User/Client] -->|HTTPS| API

    API -->|SQL queries<br/>vector search| PG
    API -->|invoke model| Bedrock
    API -->|metrics| CW
    API -->|traces| LF

    Worker -->|batch ingestion<br/>monthly cron| PG
    Worker -->|drift detection| API
    Worker -.->|test only| Mock
```

**Container responsibilities:**

### `cip-api` (FastAPI)
- **Endpoints**: `/health`, `/health/live`, `/health/ready`, `/metrics`, `/ask`, `/analyze`
- **Responsibilities**:
  - Auth (API key + tenant_id)
  - Rate limiting (token bucket per tenant)
  - RAG retrieval (pgvector)
  - LLM orchestration (static OR ReAct)
  - Live tools (Cost/Advisor/Recommender)
  - Inspection Engine (TF + K8s)
  - Audit logging + Prometheus metrics
- **Stateless**: state in Postgres+Redis

### `cip-worker` (Celery beat + worker)
- **Jobs**:
  - `monthly_cron` — drift detection (1st day of each month)
  - `ingest_full` — exhaustive ingestion (manual)
  - `eval_run` — eval suite (manual or CI)
- **Benefit**: long-running tasks without blocking the API

### `Postgres + pgvector`
- **Schemas**:
  - `data_cloud_docs` — knowledge base (chunks + embeddings)
  - `environments` — environments analyzed per tenant
  - `analyses` — analysis history
  - `findings` — prioritized findings
- **Operation**: managed PG (Cloud SQL, RDS) or another

### `Bedrock`
- **Default model**: `anthropic.claude-sonnet-4-5-20250929-v1:0`
- **Fallback**: local stub when `LLM_PROVIDER=stub` (dev/test)

---

## 3. Component Diagram (C3)

**Decomposition of the `cip-api` container** into components:

```mermaid
graph TB
    subgraph "cip-api container"
        Auth[🔐 Auth Middleware<br/>X-API-Key + X-Tenant-Id]
        RL[⏱️ Rate Limiter<br/>Token bucket<br/>per tenant]
        Metrics[📊 Metrics<br/>Prometheus]
        Audit[📝 Audit Logger<br/>JSONL]
        Router[🎯 Router<br/>Intent classifier]
        Orch[🎼 Orchestrator<br/>estático + ReAct]
        RAG[🔍 RAG Engine<br/>pgvector search]
        Tools[🔧 Cloud Tools<br/>AWS/Azure/GCP]
        Insp[🔎 Inspection Engine<br/>TF + K8s]
        Spec[🧠 8 Specialists<br/>aws/gcp/azure/finops/...]
        Cache[💾 TTL Cache<br/>tools]
    end

    Client[Client] --> Auth
    Auth --> RL
    Auth --> Orch
    Orch --> Router
    Router -->|intent| Orch
    Orch -->|RAG| RAG
    Orch -->|tools| Tools
    Orch -->|inspection| Insp
    Orch -->|specialists| Spec
    Tools --> Cache
    Orch --> Metrics
    Orch --> Audit
```

**Component responsibilities:**

### Auth Middleware (`cip/api/auth.py`)
- Validates `X-API-Key` against `CIP_API_KEYS` (format `key:tenant:rpm`)
- Extracts `X-Tenant-Id` (optional, must match the key)
- Returns a `TenantContext` for the rest of the pipeline
- In dev: accepts without auth (warning log)

### Rate Limiter (`cip/api/auth.py`)
- Token bucket per tenant (lazy init with full tokens)
- Proportional refill: `tokens_added = elapsed * (rpm/60)`
- HTTP 429 with `Retry-After` when exceeded

### Metrics (`cip/observability.py`)
- In-memory registry (counters + histograms)
- Prometheus text format exposed at `/metrics`
- Labels per endpoint/status/tenant
- Reset at each startup (not persistent)

### Audit Logger (`cip/observability.py`)
- Append-only JSONL at `CIP_AUDIT_LOG_PATH`
- Each request → entry with tenant, endpoint, status, latency
- Minimal PII (only 100 chars of question_preview)

### Router (`cip/agents/router.py`)
- Keyword-based heuristics
- 5 intents: KNOWLEDGE, ENVIRONMENT, COST, IAC_REVIEW, COMPARE
- 1-3 specialists per query (cap=3)
- Combines cloud provider + domain

### Orchestrator (`cip/agents/orchestrator.py`)
- **Static mode** (default): classifier → tools → parallel specialists → merge
- **ReAct mode** (opt-in): loop Thought→Action→Observation (max 5 steps)
- Graceful fallback: ReAct failed → static

### RAG Engine (`cip/rag/engine.py`)
- pgvector with HNSW index
- Filters: cloud, service, category
- Score threshold: `RETRIEVAL_MIN_SCORE=0.80` (e5-small)
- Returns `answer + sources + has_grounding`

### Cloud Tools (`cip/tools/{aws_cost,azure_advisor,gcp_recommender}.py`)
- Read-only (ADR-0003): Cost Explorer, Advisor, Recommender
- TTL cache (default 1h) per method
- Mock mode: `CIP_USE_MOCK_CLOUDS=true` → HTTP to mock server

### Inspection Engine (`cip/inspection/{terraform,kubernetes}.py`)
- 7 Terraform rules: encryption, SG, oversized, tags, etc.
- 7 K8s rules: privileged, hostNetwork, RBAC, probes, etc.
- Each finding has: severity, domain, $ impact, references
- Severity: critical/high/medium/low

### 8 Specialists (`cip/prompts/specialists.py`)
- 3 cloud providers: aws, gcp, azure
- 5 domains: finops, security, sre, kubernetes, terraform
- Each one: system prompt + RAG filtered by its context
- Specific tools (FinOps → cost tools)

### TTL Cache (`cip/tools/cache.py`)
- Token bucket per method
- `@cached(ttl=3600)` decorator
- Reset in production every hour (TTL)

---

## 4. Code Diagram (C4) — Orchestrator

**Code diagram of the orchestrator** (internal components):

```mermaid
graph TB
    subgraph "agents/orchestrator.py"
        Handle[handle<br/>main entrypoint]
        StaticH[_handle_static<br/>default mode]
        ReactH[_handle_react<br/>opt-in mode]
        CollectLD[_collect_live_data<br/>cost signals]
        Inspect[_inspect<br/>IaC analysis]
        RunSpec[_run_specialists<br/>parallel via gather]
        MergeSR[_merge_specialist_results<br/>concat answers]
        BuildSum[_build_summary<br/>final text]
    end

    subgraph "agents/react.py"
        ReactOrch[ReActOrchestrator]
        ReactLoop[loop: Thought→Action→Observation]
        ReactTool[execute_tool: 4 tools]
    end

    subgraph "agents/router.py"
        Classify[classify<br/>heuristic keywords]
    end

    subgraph "rag/engine.py"
        RAGQ[RagEngine.query]
    end

    Handle --> StaticH
    Handle --> ReactH
    ReactH --> ReactOrch
    ReactOrch --> ReactLoop
    ReactLoop --> ReactTool
    ReactTool --> RAGQ
    StaticH --> Classify
    StaticH --> CollectLD
    StaticH --> Inspect
    StaticH --> RAGQ
    StaticH --> RunSpec
    StaticH --> MergeSR
    StaticH --> BuildSum
```

---

## 5. Deployment Diagram (Cloud PaaS)

```mermaid
graph TB
    User[👤 User] -->|HTTPS| CF[☁️ Cloudflare<br/>TLS + DDoS]
    CF -->|Rate limit L7| RL[🛡️ Rate limit<br/>100 req/s]
    RL -->|HTTPS| App[Cloud PaaS App<br/>1+ replicas]
    App -->|psycopg| PG[Managed Postgres<br/>+ pgvector]
    App -->|boto3| BR[AWS Bedrock<br/>Claude Sonnet 4.5]
    App -->|OTLP| LF[Langfuse Cloud]
    App -->|/metrics scrape| Prom[Prometheus<br/>ou Datadog]
```

**Scaling:**
- **Vertical** (1 replica): scale memory/CPU on the PaaS
- **Horizontal** (N replicas): `gcloud run services update cip --min-instances N` (or similar per PaaS)
- **Embedding offload**: `EMBED_PROVIDER=bedrock` to free 1.5GB RAM per replica

---

## 6. Data Flow Diagram

**Flow of a typical `/ask` request:**

```mermaid
sequenceDiagram
    participant U as User
    participant Auth as Auth Middleware
    participant RL as Rate Limiter
    participant R as Router
    participant O as Orchestrator
    participant RAG as RAG Engine
    participant S as Specialists
    participant V as Vector Store
    participant L as LLM (Bedrock)
    participant M as Metrics/Audit

    U->>Auth: POST /ask {question, cloud}
    Auth->>Auth: Valida X-API-Key + X-Tenant-Id
    Auth->>RL: check_rate_limit(ctx)
    RL-->>Auth: OK (token decrementado)
    Auth->>O: handle(question, cloud)
    O->>R: classify(question)
    R-->>O: AnalysisPlan(intent, specialists, clouds)
    O->>RAG: query(question, cloud=plan.clouds[0])
    RAG->>V: SELECT embedding <=> query_embedding LIMIT 8
    V-->>RAG: top-8 chunks
    RAG-->>O: RagResult(answer, sources, has_grounding=True)
    par Para cada specialist
        O->>S: query(augmented_q, cloud=spec_cloud)
        S->>RAG: query
        RAG-->>S: result
        S-->>O: SpecialistResult
    end
    O->>O: merge_specialist_results + build_summary
    O->>M: inc counters + observe latency
    O->>M: audit.log(AuditEntry)
    O-->>U: AskResponse{answer, sources, has_grounding}
```

**ReAct flow** (opt-in):

```mermaid
sequenceDiagram
    participant U as User
    participant O as Orchestrator
    participant R as ReActOrchestrator
    participant L as LLM
    participant T as Tools

    U->>O: handle(q, react_mode=True)
    O->>R: run(q, plan)
    loop Até is_final=true OR max_steps
        R->>L: generate_next_step(q, history)
        L-->>R: {thought, action, action_input, is_final}
        alt is_final=true
            R->>R: return final_answer
        else
            R->>T: execute_tool(action, action_input)
            T-->>R: observation
            R->>R: append to history
        end
    end
    R-->>O: ReActResult(final_answer, steps, tool_calls)
    O-->>U: AnalysisResult(summary=final_answer)
```

---

## 7. Trade-offs and Architectural Decisions

See `docs/adr/` for detailed ADRs:

- **ADR-0001**: RAG-first (no fine-tuning for knowledge)
- **ADR-0002**: pgvector as vector DB
- **ADR-0003**: Read-only tools for live data
- **ADR-0004**: Claude via Bedrock + local e5-small
- **ADR-0005** (NEW): Static mode + ReAct as opt-in

---

## 8. Extension Points

To add a new cloud provider (e.g. Oracle Cloud):

1. **Create a tool** in `src/cip/tools/oracle_cloud.py` (same AWS/Azure/GCP pattern)
2. **Register it in the orchestrator** (`collect_cost_signals`)
3. **Add keywords** in `agents/router.py` (CLOUD_KEYWORDS)
4. **Add a specialist** in `prompts/specialists.py` (oracle_specialist)
5. **Create a ReAct tool** if you want to expose it via ReAct mode
6. **Add it to the mock server** for testing (`mock_cloud_server.py`)

---

**Last updated**: 2026-08-24
**Version**: 1.0
**Maintainer**: Senior Cloud Engineer
