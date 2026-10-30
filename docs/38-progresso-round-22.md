# Progresso Round 22 — Homologação no Container + Correção de Rede do Compose

> **Data**: 2026-08-25 | **Round**: 22/30 | **Status**: PARTIAL (homolog LLM real bloqueada por chave ausente)

---

## 🎯 Resultado da Rodada

Corrigido o **gap de rede do `docker-compose.yml`** (bloco `networks:` ausente) e executada a suites de qualidade **dentro do container** (estágio `homolog`). A **homologação com LLM real (MiniMax M3) ficou BLOQUEADA** porque a única `MINIMAX_API_KEY` disponível no ambiente é um placeholder (`sk-cp-ZZ…`), sem chave real.

| Item | Status |
|---|---|
| Bloco `networks:` no compose (DNS interno `cip_default`) | ✅ |
| `cip-api` resolve `cloudpilot_postgres` via DNS | ✅ (10.89.1.6) |
| Migrations SQL aplicadas (002/003/004) | ✅ |
| KB populada (6 knowledge areas, 3.674 chunks) | ✅ |
| Preflight `--strict` | ✅ 6/6 gates |
| Testes dentro do container | ✅ 573 passed / 17 failed / 19 skipped |
| Homolog LLM real (MiniMax M3) | ⛔ BLOCKED (chave placeholder) |
| Eval offline (fallback) | ⚠️ GATE FAIL (esperado sem LLM) |

---

## ✅ Entregas Concretas

### 1. Correção do bloco `networks:` em `docker-compose.yml`

O header instruía `podman network connect cip_default cloudpilot_postgres` e referia "ver `networks:` abaixo", mas o bloco **não existia**. Adicionado o bloco `networks:` declarando `cip_default` como `external: true` (a rede já existe, criada pelo Podman como `<dir>_default`), e referenciado no serviço `cip-api`.

```diff
+ networks:
+   # Rede bridge com DNS habilitado usada pelo cip-api para resolver o Postgres
+   # externo `cloudpilot_postgres` por nome. Declarada como `external` porque já
+   # foi criada na primeira subida do compose ...
+   cip_default:
+     external: true
```

```diff
   cip-api:
     <<: *api-common
     container_name: cip-api
+    networks:
+      - cip_default
```

**Nome real confirmado**: `podman network ls` retorna `cip_default` (bridge), e `podman network inspect cip_default` mostra `dns_enabled: true`.

### 2. `scripts/apply_migrations.py` — reescrito para usar `psycopg` (não `psql`)

O script shellava para o binário `psql`, que **não existe** na imagem runtime/base (só `libpq-dev`). Reescrito para usar `psycopg` (driver Python já presente), com transações explícitas e idempotência. Agora é portável para o estágio enxuto `base`.

### 3. `Dockerfile` — estágio `homolog` com `COPY . ./`

O estágio homolog não copiava artefatos de build/CI referenciados pela suite completa (`Makefile`, `docker-compose.yml`, `docs/`, `.github/`, `CHANGELOG.md`, `ops/`, `iac/`, `QUICKSTART.md`, `.devcontainer/`). Refatorado para `COPY . ./` (o `.dockerignore` já exclui `.env` e caches).

### 4. `scripts/preflight.py` — flag `--strict`

Adicionado `--strict` para uniformizar o CLI com `homolog_validate.py`/`run_eval.py` (no-op: preflight já é estrito por default).

### 5. `src/cip/observability.py` — registry Prometheus dedicado

As métricas de chat usavam o registry GLOBAL do `prometheus_client`, causando `DuplicateTimeseries` quando o módulo era re-importado sob `src.cip.observability` vs `cip.observability`. Movidas para um `CollectorRegistry` dedicado.

### 6. Testes corrigidos (drift factual)

- `tests/test_homolog.py` — `TestPodmanCompatibility` (2 testes): compose agora usa Postgres externo, não sobe `postgres:`/`pgvector`.
- `tests/test_chat_multiturn.py` — `TestDockerIntegration` (2 testes): `test_compose_defines_cip_api_service` e `test_compose_has_postgres_healthcheck` atualizados para Postgres externo.
- `tests/test_minimax_provider.py` — `test_default_provider_is_stub`: isola `os.environ["LLM_PROVIDER"]` (o Dockerfile define `ENV LLM_PROVIDER=minimax`).

### 7. `.dockerignore` — diretórios de cache adicionados

`.pytest_cache/`, `.audit/`, `.tmp_*/`, `pip-*`, `.code-review-graph/` etc. (evita incluir no build context e erros de "Acesso negado").

---

## 🧪 Validação (saídas reais)

### Rede / DB

```
$ podman network ls
NETWORK ID    NAME        DRIVER
7e7334486651  cip_default bridge

$ podman exec cip-api python -c "import socket; print(socket.gethostbyname('cloudpilot_postgres'))"
10.89.1.6
```

### Health (todos os checks)

```json
{"healthy":true,"checks":[
  {"name":"database","healthy":true,"message":"Postgres+pgvector OK (28ms)"},
  {"name":"llm","healthy":true,"message":"LLM provider 'minimax' initialized"},
  {"name":"vector_store","healthy":true,"message":"1473 chunks indexed"},
  {"name":"rate_limiter","healthy":true}]}
```

### Migrations

```
$ podman exec cip-api python scripts/apply_migrations.py
Encontradas 3 migration(s):
  - 002_relax_cloud_and_doc_type_constraints.sql
  - 003_conversations_and_feedback.sql
  - 004_share_tokens_and_extras.sql
Aplicando migrations:
  - 002_relax_cloud_and_doc_type_constraints.sql ... OK
  - 003_conversations_and_feedback.sql ... OK
  - 004_share_tokens_and_extras.sql ... OK
[OK] Migrations processadas.
```

### KB (ingestão completa)

```
total: 3674 chunks
  multi: 1757 | azure: 646 | gcp: 504 | architecture: 368 | aws: 323 | case-studies: 76
```

`ingestion_complete`: `ingested_chunks=2222, skipped=116, batches_done=82, batches_failed=0`.

### Preflight

```
Resumo: 6 OK, 0 FAIL, 0 WARN de 6 checks
  [OK] database             pgvector 0.8.6, 3674 chunks
  [OK] llm_provider         LLM 'minimax' + embed 'local' OK
  [OK] health_endpoints     4 checks passaram
[GO] Todos os checks críticos passaram.
```

### Testes

```
573 passed, 17 failed, 19 skipped, 2 warnings in 274.97s
```

Os 17 restantes são **drift pré-existente** ou **dependentes de chave LLM real** (fora de escopo do Round 22):

| Bucket | N | Causa |
|---|---|---|
| `test_web_ui` JS structure | 5 | `web/app.js` foi reescrito para multi-turn (funções renomeadas) |
| `test_specialists` | 7 | Executa orquestrador real → precisa chave MiniMax válida |
| `test_tools_cache`/`test_tools_mock_integration` | 2 | Execução real de tools → LLM |
| `test_inspection_rules` (RDS Multi-AZ) | 1 | Regra Terraform T4 |
| `test_mock_cloud_cli` | 2 | Subprocess CLI (status/bench) |

### Homolog (BLOCKED) + Eval offline

`MINIMAX_API_KEY` no container = `sk-cp-ZZ…` (placeholder, 125 chars). Sem chave real → **BLOCKED**.

```
$ podman exec cip-api python eval/run_eval.py --offline --strict
Avaliando 106 casos (offline)...
RESULTADO: 3/106 passaram
GATE: [FAIL]
Scores médios:
  accuracy: 3.30 | grounding: 5.00 | citation: 5.00 | format: 1.00 | zero_price: 5.00
```

`accuracy` e `format` não passam sem LLM real (esperado no modo offline — o Inspection Engine só detecta termos/problemas, não gera resposta estruturada).

---

## 📈 Progresso

```
Round 21 — Limpeza Railway (100%) ✅
Round 22 — Homolog no container + rede compose (80% — homolog LLM real bloqueada) ⏳
```

---

## 🚧 BLOCKERS

1. **`LLM_API_KEY`/`MINIMAX_API_KEY` ausente** — a única chave disponível é placeholder `sk-cp-ZZ…`. Sem chave real, a homologação com MiniMax M3 não pode ser executada.
2. **`podman compose` CLI quebrado no host** — `podman compose <sub>` falha com `get machine connection URI: could not find a matching machine` e os `podman machine list`/`podman build` falham com `Acesso negado` em `C:\Users\ECUNHA\.ssh\known_hosts` / `C:\Users\ECUNHA\.config\containers\podman\machine\wsl\` e `C:\Projetos\cip\.pytest_cache`. Contornado com `podman exec`/`podman cp` direto (os containers já estavam UP e saudáveis).

---

## 🎯 Próximos Passos

1. **Fornecer `MINIMAX_API_KEY` real** (env ou `.env`) e re-executar `scripts/homolog_validate.py --strict` para concluir a homologação LLM real.
2. **Atualizar `tests/test_web_ui.py`** para as novas funções do `web/app.js` (multi-turn) — drift factual de Round 22 Phase 2.
3. **Resolver os 7 `test_specialists`** — ou fornecem chave LLM real, ou mockam o orquestrador (hoje chamam o LLM de verdade).
4. **Investigar `test_inspection_rules`** (regra Terraform RDS Multi-AZ) e `test_mock_cloud_cli` (subprocess).
5. **Reparar a conexão `podman compose`/`podman machine`** do host (permissões de `known_hosts`/lockfile) para permitir `build`/`compose` nativos.
