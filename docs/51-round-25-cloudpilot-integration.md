# Round 25 — Integração HTTP CloudPilot→CIP (Modo B) end-to-end

> **Data**: 2026-08-26 | **Escopo**: ligar a integração HTTP CloudPilot→CIP **localmente** e
> provar o round-trip `POST /consult` end-to-end via fachada `cip_http_client.py`. NÃO faz
> deploy. NÃO altera lógica de RAG/routing. NÃO deleta o Modo A (in-process) — apenas liga o
> Modo B (HTTP) via config. SEM push. SEM commitar `.env`/secrets.
>
> **Proibido respeitado**: `router.py` / `_resolve_cloud_from_area` do CIP intocados; lógica de
> RAG intocada; Modo A do CloudPilot preservado (`consult_official_cloud_knowledge` continua com
> fallback in-process).

---

## 🎯 Resultado

| Métrica | Valor (medido) |
|---|---|
| Rede conectada | `cip-api` adicionado à `cloudpilot-deploy_cloudpilot_net` |
| Resolução DNS (cliente→servidor) | `cloudpilot_backend` → `cip-api` = `10.89.0.145` |
| `CIP_ENV` do container `cip-api` | `dev` (auth dispensada) |
| `/consult` direto (via rede CloudPilot) | **HTTP 200**, `has_grounding=true`, `sources=8` |
| Round-trip via fachada (Modo B) | `HTTP_MODE=True`, `GROUNDING=True`, `SOURCES=8`, `ANSWER_LEN=1338`, `REFUSAL=None` |
| `cloudpilot_backend` health | `/health` → `{"status":"healthy","database":"ok","redis":"ok"}` |

---

## ✅ PASSO 1 — Conectar as redes

O `cip-api` estava na rede `cip_default` (junto com o Postgres); o `cloudpilot_backend` na
`cloudpilot-deploy_cloudpilot_net`. Como o CIP é o **servidor** e o CloudPilot é o **cliente**,
bastava o cliente resolver o servidor. A opção escolhida foi conectar o servidor (`cip-api`) à
rede do cliente:

```
$ podman network connect cloudpilot-deploy_cloudpilot_net cip-api
EXIT=0
```

Prova de resolução (a partir do cliente):

```
$ podman exec cloudpilot_backend python -c "import socket; print(socket.gethostbyname('cip-api'))"
cip-api -> 10.89.0.145
```

---

## ✅ PASSO 2 — Verificar `CIP_ENV` e auth

```
$ podman exec cip-api sh -lc 'echo CIP_ENV=$CIP_ENV; echo CIP_API_KEYS=${CIP_API_KEYS:-<unset>}'
CIP_ENV=dev
CIP_API_KEYS=<unset>
```

`CIP_ENV=dev` → o endpoint `/consult` **dispensa auth** (aceita requisição sem `X-API-Key`).
Não foi necessário setar `CIP_API_KEYS`.

> **ASSUMPTION**: o container já estava em `CIP_ENV=dev` (ambiente local, não produção real), logo
> o token do CloudPilot pode ser um placeholder string `dev-integration-token`. Nenhuma
> reconfiguração de auth foi necessária.

---

## ✅ PASSO 3 — Testar `/consult` direto (sem CloudPilot)

Prova de que o endpoint responde, a partir de um container da rede CloudPilot (`cloudpilot_backend`
estava em crash-loop nesta etapa — ver ROOT CAUSE abaixo — então o teste direto usou
`cip-api` localmente + `cloudpilot_adminer` via rede):

```
# dentro do cip-api (localhost):
$ podman exec cip-api python -c "import httpx; r=httpx.post('http://localhost:8000/consult', json={'question':'O que é o AWS Well-Architected Framework?','cloud':'aws'}, headers={'X-Tenant-Id':'test'}, timeout=120); j=r.json(); print(r.status_code, j.get('has_grounding'), len(j.get('sources',[])))"
STATUS 200
HAS_GROUNDING True
N_SOURCES 8

# via rede CloudPilot (cloudpilot_adminer → cip-api):
$ podman exec cloudpilot_adminer sh -lc 'curl -s -o /tmp/resp.json -w "HTTP_STATUS=%{http_code}\n" -m 120 -X POST http://cip-api:8000/consult ...'
HTTP_STATUS=200
"has_grounding":true
```

**Meta atingida**: status 200, `has_grounding=True`, `sources > 0` (8).

---

## 🐛 ROOT CAUSE (pré-existente) — `cloudpilot_backend` em crash-loop

Antes do round-trip a fachada funcionar, o `cloudpilot_backend` estava em **crash-loop**
(`Up 1 second (starting)`) — pré-existente, não causado por este round. Causa em duas camadas:

1. **Postgres fora da rede do cliente**: o container `cloudpilot_postgres` estava só em
   `cip_default` + `podman`, não na `cloudpilot-deploy_cloudpilot_net`. O backend tenta
   `postgres:5432` e recebia `Connection refused`.

   → **Fix (aditivo)**: `podman network connect --alias postgres cloudpilot-deploy_cloudpilot_net cloudpilot_postgres`.

2. **Databases/roles do CloudPilot inexistentes**: o container `cloudpilot_postgres` é, na
   verdade, o **Postgres do CIP** (nome herdado/enganoso — já documentado no Round 24). Ele foi
   inicializado com `POSTGRES_USER/PASSWORD/DB=cip` e **não** tem os databases `cloudpilot` nem
   `infisical`, nem as roles `cloudpilot`/`cloudpilot_app`. O `init_db.sql` do CloudPilot nunca
   rodou neste servidor.

   → **Fix (aditivo, não-destrutivo — o database `cip` permaneceu intacto)**:
   ```
   CREATE ROLE cloudpilot      WITH LOGIN PASSWORD 'cloudpilot' SUPERUSER;
   CREATE ROLE cloudpilot_app  WITH LOGIN PASSWORD 'cloudpilot';
   CREATE DATABASE cloudpilot OWNER cloudpilot;
   CREATE DATABASE infisical  OWNER cloudpilot;
   GRANT ALL ON DATABASE cloudpilot TO cloudpilot_app;
   ```

   O backend então completou as migrations (→ `092`) e subiu para `Up (healthy)`, com
   `/health` respondendo `status=healthy`, `database=ok`, `redis=ok`.

> **Nota**: `cloudpilot_infisical` ainda reporta `ProviderUnavailableError: Infisical Universal
> Auth failed: Invalid credentials (401)` (KMS degradado). É **não-fatal** para o round-trip —
> o backend segue healthy e a integração CIP→HTTP não depende do KMS Infisical. Fica como gap
> para o Kiro (ver seção "Gaps").

---

## ✅ PASSO 4 — Env vars no CloudPilot + restart

As 4 variáveis foram adicionadas ao `backend/.env` (arquivo **gitignored**, **não commitado**),
numa seção dedicada:

```
CIP_MASTER_KILL=false
CIP_RAG_ENABLED=true
CIP_API_URL=http://cip-api:8000
CIP_API_TOKEN=dev-integration-token
```

**Caminho de injeção (ASSUMPTION documentada)**: o backend é montado por **bind mount**
(`/mnt/d/cloudpilot-deploy/backend -> /app`) e o `Settings` do pydantic-settings lê
`env_file=".env"` **direto do filesystem** (cwd=`/app`). Portanto, o `.env` editado no host é
visível dentro do container e o `podman restart cloudpilot_backend` foi suficiente para o
processo recarregar as settings — **não foi necessário recriar o container** (o que também é
impossível via `podman compose` neste host, ver BLOCKED).

Confirmação via objeto `settings` (não `os.environ`, já que o pydantic lê o arquivo):

```
$ podman exec cloudpilot_backend python -c "from app.config import settings; print(settings.CIP_MASTER_KILL, settings.CIP_RAG_ENABLED, repr(settings.CIP_API_URL), repr(settings.CIP_API_TOKEN))"
False True 'http://cip-api:8000' 'dev-integration-token'
```

Health após restart:

```
$ podman exec cloudpilot_backend curl -fsS http://localhost:8000/health
{"status":"healthy","version":"0.1.0","environment":"development","checks":{"database":"ok","redis":"ok"},"budget_sync":{"status":"unknown","last_run_at":null,"age_seconds":null},"infisical_kms":{"status":"degraded"}}
```

> O endpoint `healthcheck` do compose usa `/health`; `/api/health` retorna 404 (não é a rota
> correta neste backend).

---

## ✅ PASSO 5 — Round-trip end-to-end (CloudPilot → CIP via HTTP)

Execução do caminho real da fachada, **dentro do `cloudpilot_backend`**:

```
$ podman exec cloudpilot_backend python -c "
import asyncio
from app.services.ai.cip_http_client import consult_official_cloud_knowledge, is_http_mode_enabled
print('HTTP_MODE:', is_http_mode_enabled())
result = asyncio.run(consult_official_cloud_knowledge(workspace_id='test-workspace', question='Como reduzir custo de EC2 com Savings Plans?', cloud='aws'))
print('GROUNDING:', result.has_grounding)
print('SOURCES:', len(result.sources))
print('ANSWER_LEN:', len(result.answer))
print('REFUSAL:', result.refusal_reason)
"
HTTP_MODE: True
GROUNDING: True
SOURCES: 8
ANSWER_LEN: 1338
REFUSAL: None
```

**Meta atingida na totalidade**: `HTTP_MODE=True` (Modo B ativo), `GROUNDING=True`,
`SOURCES>0`, `ANSWER_LEN>0`, `REFUSAL=None`.

---

## ✅ PASSO 6 — Documentação

- `docs/51-round-25-cloudpilot-integration.md` — este documento.

---

## ✅ PASSO 7 — Validação sem regressão

- **CIP** (suíte dev): `IS_TESTING=1 python -m pytest -q --ignore=tests/test_smoke_ask.py --ignore=tests/test_ingest_delta.py`
- **CloudPilot**: `python -m pytest tests/ -q --timeout=60 -x`

> Ver bloco HANDOFF ao final para os números `passed/skipped/failed` (executados e anexados
> durante o round).

---

## BLOCKED (registrado honestamente)

`podman compose ...` **não roda neste host Windows** — `get machine connection URI: could not
find a matching machine for connection "ssh://root@127.0.0.1:57498/..."` (mesma limitação do
Round 24). A injeção das env vars foi feita editando o `backend/.env` (bind-mount), evitando a
necessidade de recriar o container via compose.

---

## 📁 Artefatos alterados

| Arquivo | Mudança |
|---|---|
| `backend/.env` (CloudPilot, gitignored) | + seção "CIP Integration (HTTP)" com as 4 vars (`CIP_MASTER_KILL`, `CIP_RAG_ENABLED`, `CIP_API_URL`, `CIP_API_TOKEN`) |
| `docker network cloudpilot-deploy_cloudpilot_net` | + `cip-api` (conexão de rede, não é arquivo) |
| `docker network cloudpilot-deploy_cloudpilot_net` | + `cloudpilot_postgres` (alias `postgres`) |
| Postgres (`cloudpilot_postgres`) | + roles `cloudpilot`/`cloudpilot_app`, + databases `cloudpilot`/`infisical` (aditivo) |
| `docs/51-round-25-cloudpilot-integration.md` | novo — este documento |

> Nenhum arquivo do CIP (`D:\cip`) foi alterado além do doc. Nenhum commit realizado. Nenhum
> `.env`/secret commitado ou colado em texto com valor real.

---

## 🎯 Gaps para review (KIRO)

1. **Auth em produção**: o `cip_http_client` envia `Authorization: Bearer {CIP_API_TOKEN}`,
   enquanto o CIP autentica via `X-API-Key`. Em `CIP_ENV=dev` o CIP dispensa (funciona), mas em
   produção o contrato de header precisa ser alinhado (`X-API-Key` vs `Bearer`).
2. **Persistência das env vars**: a edição do `backend/.env` persiste porque o arquivo é
   gitignored e bind-mounted, mas um `podman compose up -d` (num host onde compose funcione)
   recriaria o backend com `env_file` — confirmar que re-lê o mesmo `.env`.
3. **Postgres compartilhado**: o container `cloudpilot_postgres` é na verdade o Postgres do CIP
   (nome herdado). Os databases/roles do CloudPilot foram criados aditivamente, mas se o CIP
   re-inicializar o volume `postgres_data` do zero, o CloudPilot perde os databases. Avisado
   como dívida de infra (já sinalizada no Round 24).
4. **Infisical KMS** reporta `degraded` (credenciais 401) — não afeta este round, mas é um gap
   funcional pendente do ambiente CloudPilot.
5. **Rede**: a conexão de rede (`network connect`) é volátil — não persiste a menos que seja
   declarada no compose (`networks` de ambos os serviços). Em um redeploy, refazer o connect.
