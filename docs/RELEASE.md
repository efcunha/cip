# Release — Cloud Intelligence Platform (CIP)

> Documento operável de build de release. **Não** faz deploy para nenhum destino
> (sem registry/K8s/Railway definidos nesta fase). Este documento cobre apenas:
> build da imagem de produção (estágio `base` enxuto), variáveis obrigatórias e
> o checklist pré-release. `db/curated/` já está versionado neste repositório
> (não há artefato binário separado).

---

## 1. Build de produção (imagem enxuta)

A imagem de **release** usa o estágio `base` do Dockerfile (runtime enxuto: só
`src/` + `db/` + `scripts/`). O estágio `homolog` existe **apenas** para rodar
suíte/avaliação DENTRO do container (carrega `tests/`, `eval/` e dev-deps) e
**nunca** deve ser tagueado como release.

### Comando (local, Podman ora Docker)

```bash
podman build --target base -t cip:<versão> .
```

Substitua `<versão>` pela tag semver (ex.: `0.2.0+integration`) ou pelo SHA do
commit de release (ex.: `cip:d0e6211`).

> O job `build` do CI (`.github/workflows/ci.yml`) já faz o build da release com
> `--target base` e um build **separado** `--target homolog` para validação
> explícita da suíte. `docker build .` **SEM** `--target` resolveria para o último
> estágio (`homolog`) e produziria a imagem inchada — nunca use sem `--target base`.

---

## 2. Variáveis de ambiente

### Obrigatórias (a API não sobe / readiness falha sem elas)

| Variável | Propósito | Obrigatória |
|---|---|---|
| `DATABASE_URL` | Conexão Postgres/pgvector (asyncpg). `readiness` e ingestão dependem dela. | **Sim** |
| `LLM_PROVIDER` | `minimax` \| `deepseek` \| `bedrock` \| `openai` \| `local` \| `stub`. | **Sim** |
| `LLM_API_KEY` **ou** `MINIMAX_API_KEY` **ou** `DEEPSEEK_API_KEY` | Credencial do provider (depende de `LLM_PROVIDER`). | **Sim** (conforme provider) |
| `EMBED_PROVIDER` | `local` \| `bedrock` \| `openai`. | **Sim** (default `local`) |
| `EMBED_MODEL` | Modelo de embeddings (default `intfloat/multilingual-e5-small`). | **Sim** (default) |
| `EMBED_DIM` | Dimensão do embedding — **deve casar** com `EMBED_MODEL` (validator bloqueia mismatch). | **Sim** (default 384) |
| `EMBED_DEVICE` | `cpu` \| `cuda`. | **Sim** (default `cpu`) |

Todas as variáveis acima são lidas por `src/cip/config.py` (`Settings` via
pydantic-settings), inclusive os aliases `MINIMAX_API_KEY`/`DEEPSEEK_API_KEY`
(`validation_alias` explícito). **Não** defina valores aqui — use o manager de
secrets do destino (Railway/encrypted env/sealed-secrets).

### Demais variáveis reconhecidas (opcionais, com default)

Referencie por NOME — nunca cole valores reais de API key.

- **App**: `CIP_ENV`, `CIP_READONLY`, `LOG_LEVEL`
- **Banco**: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- **LLM**: `LLM_MODEL`, `LLM_CONTEXT_SIZE`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`,
  `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES`, `LLM_BASE_URL`, `DEEPSEEK_BASE_URL`
- **Concorrência/robustez**: `MAX_CONCURRENT_REQUESTS`, `REQUEST_TIMEOUT_S`,
  `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_S`, `DB_POOL_RECYCLE_S`
- **Embeddings**: `EMBED_QUERY_INSTRUCTION`, `EMBED_TEXT_INSTRUCTION`
- **Retrieval**: `RETRIEVAL_TOP_K`, `RETRIEVAL_MIN_SCORE`
- **Cloud (tools read-only)**: `AWS_REGION`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AZURE_SUBSCRIPTION_ID`,
  `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
  `GCP_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`
- **Observabilidade**: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- **JWT**: `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_ISSUER`, `JWT_AUDIENCE`

> Regra: `pydantic-settings` com `extra="ignore"` — variáveis desconhecidas são
> ignoradas silenciosamente. A lista acima é a superfície **real** do `config.py`;
> nada aqui foi inventado.

---

## 3. Comando de run (com healthcheck)

O readiness probe que dispara `200 OK` quando DB + embeddings + LLM + rate limiter
estão ok é `/health/ready` (a partir de `src/cip/api/health.py`):

```bash
podman run --rm -p 8000:8000 \
  -e DATABASE_URL="<sua-dsn>" \
  -e LLM_PROVIDER="<provider>" \
  -e LLM_API_KEY="<chave-via-secrets>" \
  -e EMBED_PROVIDER="local" \
  -e EMBED_MODEL="intfloat/multilingual-e5-small" \
  -e EMBED_DIM="384" \
  cip:<versão>
```

Healthcheck após subida:

```bash
curl -fsS http://localhost:8000/health/ready
```

- `/health/live` — liveness (sempre 200 se o processo está vivo; **nunca** depende
  de DB/LLM).
- `/health/ready` — readiness (200 se DB + vector store + LLM + rate limiter ok;
  **503** caso contrário → remova do load balancer, sem restart).
- `/health` — liveness simples público.

> O `Dockerfile` também define um `HEALTHCHECK` (curl `/health/live`) e expõe a
> porta 8000. O container **não** é root (usuário `cip`).

---

## 4. Checklist pré-release

- [ ] Suíte verde: `590 passed / 0 failed` (baseline homologação fechada).
- [ ] Gate homolog `10/10` (avaliação offline strict).
- [ ] Migrations aplicadas: `db/schema.sql` + `db/migrations/*.sql` rodados na base alvo.
- [ ] KB populada: `readiness` reporta `chunks > 0` em `data_cloud_docs`
      (ingestão de `db/curated/` concluída).
- [ ] `EMBED_DIM` e `EMBED_MODEL` consistentes (validator em `config.py` bloqueia
      mismatch no boot).
- [ ] Build de release feito com `--target base` (nunca `homolog` para release).

---

## 5. Deploy standalone (open-source)

Sobe a stack COMPLETA do zero num servidor Linux limpo, com Postgres **próprio do CIP**
(nome neutro, sem "cloudpilot") + API enxuta + bootstrap idempotente. Este é o modo
open-source: o CIP não compartilha banco com o CloudPilot — cada consumidor fala com a
API **somente via HTTP** (`/ask`, `/analyze`) e **nunca lê o banco do CIP** (ver
`docs/49-cip-integration-contract.md`).

> O `docker-compose.yml` (modo integrado, consome Postgres externo `cloudpilot_postgres`,
> imagem `homolog`, porta 8001) **permanece inalterado** e continua sendo o ambiente dev.
> O standalone usa `docker-compose.prod.yml`.

### Pré-requisitos

- Servidor Linux limpo com `podman` (e `podman compose`, ou `podman-compose`) instalado.
- Porta **8000** livre no host (ASSUMPTION: o compose mapeia `8000:8000`; se ocupada,
  alterar o mapeamento no `docker-compose.prod.yml`).
- Rede de saída para baixar: imagem `pgvector/pgvector:pg16`, fonts da KB (URLs de
  documentação AWS/GCP/Azure) e o modelo de embeddings do HuggingFace
  (`intfloat/multilingual-e5-small`, ~450MB) no 1º ingest.

### Subir do zero

```bash
cp .env.prod.example .env.prod      # preencher LLM_PROVIDER + LLM_API_KEY (ou MINIMAX/DEEPSEEK) e CIP_API_KEYS
podman compose -f docker-compose.prod.yml up -d --build
```

O `cip-init` (efêmero) roda `scripts/bootstrap_prod.py`: espera o `cip_postgres` saudável,
aplica `db/schema.sql` + `db/migrations/*.sql` (via `scripts/apply_migrations.py`) e ingere a
KB (`python -m cip.ingestion.ingest --scope mvp`, embeddings LOCAIS em CPU — custo zero).
O `cip-api` só sobe quando o `cip-init` sai com exit 0.

### Tempo esperado do 1º ingest

**Medido em Round 24** (ingest do zero, CPU local, e5-small): **~22 min** (1322s) para
**4324 chunks** (`batches_failed=0`). Varia com CPU/banda; re-subidas não duplicam
(dedupe por `content_hash`), e o 1º ingest baixa o modelo de embeddings (~450MB) uma única vez.

### Health check

```bash
podman compose -f docker-compose.prod.yml exec cip-api \
  curl -fsS http://localhost:8000/health/ready
```

Deve reportar `"healthy":true` com `vector_store` mostrando `chunks > 0`. Teardown limpo:

```bash
podman compose -f docker-compose.prod.yml down -v    # remove postgres + volume + rede
```
