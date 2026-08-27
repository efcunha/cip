# Round 26 — Finalização da integração CIP no CloudPilot (Modo B primário)

> **Data**: 2026-08-26 | **Escopo**: tornar o **Modo B (HTTP)** o caminho PRIMÁRIO de RAG do
> agente CloudPilot, documentar a regra obrigatória (steering + ADR) e persistir a rede no
> compose. NÃO faz deploy. NÃO altera `router.py` / `_resolve_cloud_from_area` do CIP. NÃO muda
> lógica de RAG/embedding. NÃO deleta `cip_client.py` (fica como fallback interno da fachada).
> SEM push. SEM commitar `.env`/tokens.
>
> **Proibido respeitado**: `router.py` / `_resolve_cloud_from_area` intocados; lógica de
> RAG/embedding intocada; `cip_client.py` preservado como fallback; nenhum `.env`/token commitado.

---

## 🎯 Resultado

| Métrica | Valor (medido) |
|---|---|
| Import trocado no agente | `tools.py`: `cip_client.consult_official_cloud_knowledge` → `cip_http_client.consult_official_cloud_knowledge` |
| `is_http_mode_enabled()` no processo do backend | **True** (Modo B ativo) |
| Env vars efetivas (settings) | `CIP_MASTER_KILL=False`, `CIP_RAG_ENABLED=True`, `CIP_API_URL=http://cip-api:8000`, token setado |
| Round-trip via agente real (`ToolExecutor`) | `STATUS=ok`, `GROUNDING=True`, `SOURCES=8`, `ANSWER_LEN=1703`, `REFUSAL=None` |
| CIP suíte dev | **590 passed, 19 skipped, 0 failed** |
| CloudPilot `/health` | `{"status":"healthy","database":"ok","redis":"ok"}` |

---

## ✅ PASSO 1 — Plugar o Modo B no agente (1 import)

Em `backend/app/services/ai/tools.py`, método `_consult_official_cloud_knowledge`:

```diff
-        from app.services.ai import cip_audit, cip_metrics
-        from app.services.ai.cip_client import CipMasterKill, consult_official_cloud_knowledge
+        from app.services.ai import cip_audit, cip_metrics
+        from app.services.ai.cip_client import CipMasterKill
+        from app.services.ai.cip_http_client import consult_official_cloud_knowledge
```

- `CipMasterKill` permanece importado de `cip_client` (é a **exception class**, não a função).
- `consult_official_cloud_knowledge` passa a vir de `cip_http_client` (fachada que roteia
  Modo B↔A automaticamente).
- Docstring do método atualizado para refletir o Modo B como caminho primário.

**Verificação de outros imports**: grep em `backend/app/**` por
`cip_client.consult_official_cloud_knowledge` / `cip_client import` / `cip_http_client import`
encontrou **somente**:

- `tools.py` (corrigido acima);
- `cip_http_client.py` linhas 4/219/223/239 — o fallback interno correto (Modo A);
- `tests/` (não tocados — testam o `cip_client` in-process diretamente).

Não havia nenhum outro ponto de entrada de RAG em produção. O ponto de entrada ÚNICO agora é a
fachada HTTP.

---

## ✅ PASSO 2 — Restart + round-trip via agente real

```
$ podman restart cloudpilot_backend
$ # aguardar healthy (~11 polls x 2s)
```

Confirmação do modo HTTP + env vars efetivas no processo Python (via `settings`, não
`os.environ`):

```
$ podman exec cloudpilot_backend python -c "from app.services.ai import cip_http_client; ..."
http_mode_enabled: True
CIP_API_URL: 'http://cip-api:8000'
TOKEN_SET: True
MASTER_KILL: False
RAG_ENABLED: True
```

Round-trip exercitado pelo **agente real** (não script isolado):

```
$ podman exec cloudpilot_backend python -c "
import asyncio
from app.services.ai.tools import ToolExecutor
exe = ToolExecutor(workspace_id='00000000-0000-4000-8000-000000000001', db_session=None, grant_validator=None, single_use_ledger=None)
r = asyncio.run(exe._consult_official_cloud_knowledge(question='Como reduzir custo de EC2 com Savings Plans?', cloud='aws'))
print('STATUS:', r.get('status'))
print('GROUNDING:', r.get('has_grounding'))
print('SOURCES:', len(r.get('sources',[])))
print('ANSWER_LEN:', len(r.get('answer','')))
print('REFUSAL:', r.get('refusal_reason'))
"
STATUS: ok
GROUNDING: True
SOURCES: 8
ANSWER_LEN: 1703
REFUSAL: None
```

**Meta atingida**: STATUS=ok, GROUNDING=True, SOURCES=8, ANSWER_LEN>0, REFUSAL=None.

---

## ✅ PASSO 3 — Documentar a regra obrigatória (steering + ADR)

- **Steering**: `.github/instructions/cip-llm-rag-mandatory.instructions.md` — regra de que todo
  módulo que precise de LLM/RAG consome via `cip_http_client.consult_official_cloud_knowledge`;
  proíbe LLM direto, pgvector fora de `services/ai/cip_*` e import direto de
  `cip_client.consult_official_cloud_knowledge`.
- **ADR**: `docs/ADR/adr-006-cip-mandatory.md` — decisão registrada (Accepted): CIP é o provider
  LLM/RAG obrigatório, consumido via HTTP (primário) com fallback in-process; contexto +
  consequências + rollback.

---

## ✅ PASSO 4 — Persistir a rede no compose do CloudPilot

Novo override `docker-compose.cip.yml` (o `docker-compose.yml` principal é gerenciado e ficou
intacto):

```yaml
networks:
  cip_default:
    external: true
    name: cip_default

services:
  backend:
    networks:
      - cloudpilot_net
      - cip_default
  celery_worker:
    networks:
      - cloudpilot_net
      - cip_default
```

**ASSUMPTION documentada**: a rede a persistir é `cip_default` — a rede "nativa" do CIP (criada
pelo compose em `D:\cip`, já `external: true`), onde o `cip-api` já está nativamente. Ao ligar
`backend` + `celery_worker` a ela, o `podman network connect` manual deixa de ser necessário. A
rede `cloudpilot-deploy_cloudpilot_net` (onde o `cip-api` foi manualmente conectado no Round 25)
permanece como está; o override declara a rede do CIP como dependência adicional e não recria
nada.

> Validação de sintaxe: `podman compose config` falha neste host (ver BLOCKED abaixo), então o
> YAML foi validado com PyYAML (`yaml.safe_load` em `docker-compose.yml` +
> `docker-compose.override.yml` + `docker-compose.cip.yml` → "YAML OK").

---

## ✅ PASSO 5 — Validação sem regressão

**CIP**:

```
$ podman exec cip-api sh -lc "IS_TESTING=1 python -m pytest -q --ignore=tests/test_smoke_ask.py --ignore=tests/test_ingest_delta.py"
590 passed, 19 skipped, 1 warning in 211.65s
```

**CloudPilot**:

```
$ podman exec cloudpilot_backend curl -sf http://localhost:8000/health
{"status":"healthy","version":"0.1.0","environment":"development","checks":{"database":"ok","redis":"ok"},"budget_sync":{"status":"unknown","last_run_at":null,"age_seconds":null},"infisical_kms":{"status":"degraded"}}
```

Round-trip (PASSO 2) re-executado e **continua verde** (STATUS=ok, GROUNDING=True, SOURCES=8,
ANSWER_LEN=1703, REFUSAL=None).

---

## 📁 Artefatos alterados

| Arquivo | Mudança |
|---|---|
| `backend/app/services/ai/tools.py` | import trocado: `cip_client.consult_official_cloud_knowledge` → `cip_http_client.consult_official_cloud_knowledge` (+ docstring) |
| `.github/instructions/cip-llm-rag-mandatory.instructions.md` | novo — steering da regra obrigatória |
| `docs/ADR/adr-006-cip-mandatory.md` | novo — ADR da decisão |
| `docker-compose.cip.yml` | novo — override que declara `cip_default` external e liga backend/celery a ela |
| `docs/52-round-26-cip-finalization.md` | novo — este documento (em `D:\cip\docs`) |

> Nenhum arquivo do CIP (`D:\cip`) foi alterado além do doc. Nenhum commit realizado. Nenhum
> `.env`/token commitado ou colado com valor real.

---

## BLOCKED (registrado honestamente)

`podman compose config` **não roda neste host Windows** — `get machine connection URI: could not
find a matching machine for connection "ssh://root@127.0.0.1:57498/..."` (mesma limitação dos
Rounds 24/25). A validação da sintaxe do override foi feita via PyYAML. O override é aplicável em
qualquer host onde o compose funcione; a viabilização do round-trip atual usa a conexão de rede
já existente (`cip-api` na `cloudpilot-deploy_cloudpilot_net` + o novo override declarado para o
futuro).

---

## 🎯 Gaps para review (KIRO)

1. **Auth em produção**: `cip_http_client` envia `Authorization: Bearer`, CIP autentica via
   `X-API-Key`. Em `CIP_ENV=dev` o CIP dispensa (funciona); em produção o header precisa alinhar.
2. **grant_validator=None no teste**: o round-trip via `ToolExecutor` usa
   `grant_validator=None`/`single_use_ledger=None` (caminho de teste direto), não o executor
   full do stream_response com capability grants.
3. **Override de rede não exercitado**: `docker-compose.cip.yml` foi validado por YAML, não por
   `podman compose up` (compose quebrado neste host). Precisa de um host com compose funcional
   para confirmar o attach automático do `cip_default`.
4. **Fallback in-process ainda existe**: até o Modo A ser aposentado, a tabela `cip_cloud_docs`
   duplicada permanece como risco de divergência (tracked no `CIP_INTEGRATION.md`).
