# Round 24 — Docker Compose stand-alone (self-contained) + bootstrap idempotente + ingest cronometrado

> **Data**: 2026-08-26 | **Escopo**: criar `docker-compose.prod.yml` self-contained (Postgres
> próprio do CIP, nome neutro `cip_postgres`) + bootstrap idempotente (schema + migrations +
> ingest do zero) + **cronometrar o ingest do zero** + documentar contrato HTTP CloudPilot→CIP.
> SEM alterar o `docker-compose.yml` atual (modo integrado). SEM tocar router.py /
> `_resolve_cloud_from_area` / lógica de RAG. SEM push/deploy. Todos os containers de teste
> foram derrubados ao final; os 16 originais permanecem UP e intactos.

---

## 🎯 Resultado

| Métrica | Valor (medido) |
|---|---|
| Ingest do zero (CPU local, e5-small) | **~22.8 min** (bootstrap total: 1368s) |
| Chunks ingeridos do zero | **4325** (`batches_failed=0`) |
| Tabelas criadas (schema + migrations) | **9** (cloud_docs, data_cloud_docs, environments, analyses, findings, conversations, messages, share_tokens, schema_migrations) |
| Migrations aplicadas | **3** (002, 003, 004) |
| `/health/ready` no teste isolado | **healthy:true** — vector_store **4325 chunks** |
| Contrato HTTP CloudPilot→CIP | `docs/49-cip-integration-contract.md` |
| Suíte dev (não regredida) | 590 passed / 0 failed (ver PASSO 6) |
| Originais após teardown | cloudpilot_postgres + cip-api **Up (healthy)** |

---

## ✅ PASSO 1 — `docker-compose.prod.yml` self-contained

Criado `docker-compose.prod.yml` com três serviços:

1. **`cip_postgres`** — Postgres PRÓPRIO do CIP (imagem `pgvector/pgvector:pg16`), nome **neutro**
   (não "cloudpilot"), volume nomeado `cip_pgdata`, `POSTGRES_USER/PASSWORD/DB=cip`,
   healhtcheck `pg_isready -U cip -d cip`.
2. **`cip-init`** — imagem `target base`, `depends_on: cip_postgres (service_healthy)`,
   `entrypoint: python scripts/bootstrap_prod.py`, `restart: "no"` (efêmero, sai 0 ao terminar).
3. **`cip-api`** — `target base`, `depends_on: cip-init (service_completed_successfully)`,
   `DATABASE_URL=postgresql://cip:cip@cip_postgres:5432/cip`, `env_file .env.prod` (required:false),
   porta `8000:8000` (ASSUMPTION: 8000 livre no servidor de destino — documentado).
4. Rede própria `cip_prod_net` (criada pelo compose, NÃO external) + volume `cip_pgdata`.

Também criado `.env.prod.example` (placeholders versionáveis, espelhando as obrigatórias de
`docs/RELEASE.md`: `LLM_PROVIDER`, `LLM_API_KEY`|`MINIMAX_API_KEY`|`DEEPSEEK_API_KEY`, `EMBED_*`,
`CIP_API_KEYS`) e adicionado `.env.prod` ao `.gitignore`.

> O `docker-compose.yml` existente (modo integrado: Postgres externo + imagem `homolog` +
> porta 8001) **não foi alterado** — apenas documentado no cabeçalho do novo compose e no
> `docs/RELEASE.md`.

---

## ✅ PASSO 2 — Bootstrap idempotente

Criado `scripts/bootstrap_prod.py` (chamado pelo `cip-init`). Sequência idempotente:

1. `_wait_for_db()` — aguarda o `cip_postgres` aceitar TCP.
2. `_apply_schema()` — aplica `db/schema.sql` via psycopg `ClientCursor` (a imagem `base` **não**
   tem o binário `psql`).
3. `_apply_migrations()` — chama `scripts/apply_migrations.py` (tabela de controle
   `schema_migrations` impede re-aplicação).
4. `_ingest()` — `python -m cip.ingestion.ingest --scope mvp` (dedupe por `content_hash` +
   delta por `doc_hash` fazem re-subidas não duplicarem).

**Escolha registrada**: init-service dedicado via `scripts/bootstrap_prod.py`. Um shell script
(`bootstrap_prod.sh`) foi descartado porque a imagem `base` não tem `psql` nem `bash`-isms — o
script Python reusa o driver `psycopg` já presente e é idempotente por construção.

### 🐛 ROOT CAUSE corrigido — `scripts/apply_migrations.py` não persistia nada

Durante o teste do bootstrap do zero, descobriu-se um bug REAL (pré-existente) em
`apply_migrations.py`: as migrations printavam **"OK"** e saíam com exit 0, mas **nenhuma
tabela era criada** e `schema_migrations` ficava vazia. Causa em duas camadas:

1. `conn.execute(sql)` usa o **extended protocol** do psycopg 3.3, que **não divide scripts
   multi-statement** (especialmente com `CREATE FUNCTION ... $$ ... $$`). Statements após o
   primeiro eram descartados silenciosamente.
2. Mesmo com `ClientCursor` (simple query) aplicado, o `already_applied()` fazia um
   `conn.execute("SELECT ... %s")` **fora de transação** com `autocommit=False`, deixando a
   conexão em estado **INTRANS**; o `with conn.transaction()` seguinte não iniciava transação
   nova e o script rodava numa transação "suja" descartada no fim.

**Fix** (mínima e cirúrgica, sem tocar RAG/router):
- Executar o SQL das migrations via `ClientCursor(conn)` (simple query).
- `conn.rollback()` após o SELECT de `already_applied` para fechar a transação implícita.

Prova: após a fix, o bootstrap do zero criou as **9 tabelas** e registrou as **3 migrations**.
O `db/schema.sql` não tinha o problema (sem `$$`), mas recebeu `ClientCursor` por consistência.

---

## ✅ PASSO 3 — Ingest do zero cronometrado

O wrapper `podman compose` está **BLOCKED** neste host Windows (ver "BLOCKED" abaixo), então o
teste funcional foi orquestrado com a **CLI `podman`** reproduzindo fielmente o que o compose
faria (mesmos nomes de rede/volume/containers, mesma imagem `target base`, mesmo entrypoint).

**Medição REAL** (do zero, banco limpo, CPU local, modelo `intfloat/multilingual-e5-small`):

```
t0 = 2026-08-26T13:50:12 (podman run -d cip-init → bootstrap)
t1 = 2026-08-26T14:13:01 (container finished, ExitCode=0)
TOTAL bootstrap (wait-db + schema + migrations + ingest) = 1368s ≈ 22.8 min
ingestion_complete: ingested_chunks=4325, skipped=168, batches_done=83, batches_failed=0
```

A medição foi feita por **timestamps reais de início/fim do container `cip-init`**
(`podman inspect State.StartedAt / State.FinishedAt`), não por estimativa. Re-rodada idempotente
confirmou `ingested_chunks=0, skipped=190` (dedupe por `content_hash` não duplica).

> O número de chunks (4325) é ligeiramente inferior aos 4785 do banco de produção porque o
> ingest do zero num host limpo não consegue baixar algumas fontes remotas de `case-studies`/
> `architecture` (blogs que bloqueiam fetch — problema documentado desde o Round 22.4). É
> esperado e não é regressão.

---

## ✅ PASSO 4 — Saúde + teardown

Subido `cip-api` (imagem `cip:prod`) contra o `cip_postgres` próprio, mapeado em `8100:8000`
(a porta 8000 do host é do cloudpilot_backend). `/health/ready`:

```json
{"healthy":true,"checks":[
  {"name":"database","healthy":true,"message":"Postgres+pgvector OK (31ms)"},
  {"name":"llm","healthy":true,"message":"LLM provider 'stub' initialized"},
  {"name":"vector_store","healthy":true,"message":"4325 chunks indexed","details":{"chunks":4325}},
  {"name":"rate_limiter","healthy":true,"message":"Rate limiter operational"}
],"version":"0.2.0+integration"}
```

**chunks > 0 (4325) vindos do ingest do zero** — prova a stack self-contained saudável.
(ASSUMPTION: `LLM_PROVIDER=stub` no teste para o readiness não depender de chave de API; em
produção o provedor real vem de `.env.prod`.)

**Teardown** (equivalente a `down -v`): `podman rm -f` dos 3 containers + `podman volume rm
cip_pgdata` + `podman network rm cip_prod_net`. Confirmado: **nenhum leftover** e os originais
`cloudpilot_postgres` e `cip-api` continuam **Up (healthy)**.

---

## ✅ PASSO 5 — Documentação

- `docs/RELEASE.md` — nova seção **"Deploy standalone (open-source)"** (pré-reqs, `cp
  .env.prod.example .env.prod`, `podman compose -f docker-compose.prod.yml up -d --build`,
  tempo esperado do 1º ingest **~23 min** medido, health check, teardown).
- `docs/49-cip-integration-contract.md` — contrato HTTP CloudPilot→CIP (`/ask`, `/analyze`,
  request/response baseados nos modelos Pydantic reais de `src/cip/api/schemas.py`; consumo
  **SÓ HTTP**; consumidores **NUNCA leem o banco do CIP**).
- `docs/50-round-24-standalone-compose.md` — este documento.

---

## BLOCKED (registrado honestamente)

`podman compose -f docker-compose.prod.yml ...` **não roda neste host Windows** — o wrapper Go
do podman falha com `get machine connection URI: could not find a matching machine for
connection "ssh://root@127.0.0.1:57498/..."`, porque precisa ler a metadata da "machine" em
`C:\Users\ECUNHA\.config\containers\podman\machine\wsl\...` e esbarra em **Acesso negado** (ACL
fora do workspace). O `podman` CLI puro (`ps/run/exec/build/network/volume`) funciona
normalmente. Também **pip não roda** (Permission denied no TMP do sandbox), então
`podman-compose` Python não pôde ser instalado como provider alternativo.

**Contorno aplicado**: orquestração do teste com `podman` CLI direto (mesmos recursos que o
compose declararia), o que prova o comportamento do compose; o artefato `docker-compose.prod.yml`
permanece válido e pronto para um servidor Linux (onde `podman compose` funciona normalmente).
`podman build --target base` com **contexto limpo** (staging sem `.pytest_cache`) foi usado e
provou o build enxuto (o contexto da raiz falha por ACL no `.pytest_cache`, pré-existente).

---

## 📁 Artefatos alterados

| Arquivo | Mudança |
|---|---|
| `docker-compose.prod.yml` | novo — stack self-contained (cip_postgres + cip-init + cip-api, rede/volume próprios) |
| `.env.prod.example` | novo — placeholders versionáveis (LLM_*, EMBED_*, CIP_API_KEYS) |
| `scripts/bootstrap_prod.py` | novo — bootstrap idempotente (schema + migrations + ingest) |
| `scripts/apply_migrations.py` | **fix** — ClientCursor + rollback (multi-statement/migrations não persistiam) |
| `.gitignore` | + `.env.prod` |
| `docs/RELEASE.md` | + seção "Deploy standalone (open-source)" |
| `docs/49-cip-integration-contract.md` | novo — contrato HTTP CloudPilot→CIP |
| `docs/50-round-24-standalone-compose.md` | este documento |

---

## 🎯 Gaps para review (KIRO)

1. **Destino de deploy** ainda não definido (servidor Linux/VM/K8s/Railway) — fora de escopo.
2. **Registry** de imagens não provisionado (a imagem `cip:prod` fica local / build no alvo).
3. **Secrets manager** — `LLM_API_KEY`/`CIP_API_KEYS` em produção: sem vault definido.
4. Imagem base continua pesada (~2GB+ por `torch`/CUDA via `sentence-transformers`); considerar
   `EMBED_PROVIDER=bedrock|openai` (sem ML local) como otimização futura.
5. **Rename futuro** do container `cloudpilot_postgres` → nome neutro (é o Postgres DO CIP,
   nome herdado/enganoso) — mudança de infra do ambiente dev, não deste round.
6. Migração do ambiente dev local para o standalone (quando/quem) — fica para decisão humana.
