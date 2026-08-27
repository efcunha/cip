# Round 22.8 — Catalog cleanup: normalizar numeração T1..T7 + zerar RuntimeWarnings do test_react.py

> **Data**: 2026-08-26 | **Escopo**: limpeza cosmética — normalizar a numeração do
> catálogo de regras terraform e eliminar os 3 `RuntimeWarning: coroutine never awaited`
> em `test_react.py`. SEM baixar o gate (10/10) nem regredir a suíte (590 passing).
> Sem tocar em `router.py` nem `_resolve_cloud_from_area`; sem alterar a LÓGICA de
> detecção de nenhuma regra de inspeção (só rótulos/docstrings/nomes de teste).

---

## 🎯 Resultado

| Métrica | Antes | Depois |
|---|---|---|
| Testes | 590 passed / 0 failed | **590 passed / 0 failed** (19 skipped) |
| RuntimeWarning (test_react.py) | 3 (`_tool_query_rag._q` ×2 + `Orchestrator.handle`) | **0** |
| Homolog full 1x (LLM real minimax) | 10/10 (baseline) | **10/10** |
| Numeração catálogo terraform | docstring divergente do código/teste | **consistente** (T4=Multi-AZ, T7=prevent_destroy) |

---

## ✅ PASSO 1 — Normalizar numeração do catálogo terraform

### Diagnóstico

A docstring do catálogo (topo de `src/cip/inspection/terraform.py`) afirmava:

- `T4 - S3 bucket com public ACL/access (block_public_acls = false)`
- `T7 - RDS sem Multi-AZ em ambiente de produção`

… mas o **código inline** e os **testes** implementavam/usavam:

- `T4 — RDS sem Multi-AZ em produção` (linha 204 do módulo; `TestTerraformRuleT4_RDSNoMultiAZ`)
- `T7 — Sem lifecycle/prevent_destroy` (linha 316 do módulo; `TestTerraformRuleT7_NoPreventDestroy`)

Ou seja, a docstring estava **dessincronizada** da implementação. Isso foi registrado como
gap no Round 22.7 (gap #2): *"A label da regra RDS Multi-AZ oscila entre 'T4' (código/teste)
e 'T7' (docstring do catálogo em terraform.py)"*.

### Mapeamento ANTES (regra → número)

| # | Docstring (topo) | Comentário inline | Classe de teste |
|---|---|---|---|
| T1 | S3 sem SSE | S3 sem SSE | `T1_S3NoEncryption` |
| T2 | SG ingress 0.0.0.0/0 | SG ingress 0.0.0.0/0 | `T2_SecurityGroupPublic` |
| T3 | RDS sem storage_encrypted | RDS sem storage_encrypted | `T3_RDSNoEncryption` |
| **T4** | **S3 public ACL** ❌ | **RDS sem Multi-AZ** | **`T4_RDSNoMultiAZ`** |
| T5 | Compute sem tags | Compute sem tags | `T5_NoTags` |
| T6 | Instância oversized | Instância oversized | `T6_OversizedInstance` |
| **T7** | **RDS sem Multi-AZ** ❌ | **sem prevent_destroy** | **`T7_NoPreventDestroy`** |
| extra | backend remoto (OPERATIONS) | backend remoto (EXTRA) | — |

Divergências reais: **T4** e **T7** (3 fontes não concordavam). As demais (T1/T2/T3/T5/T6)
já estavam alinhadas.

### Mapeamento DEPOIS (regra → número)

Escolhi a convenção que **menos muda testes** — a do código/teste (Multi-AZ=T4,
prevent_destroy=T7) — e alinhei **apenas a docstring** do catálogo:

| # | Domínio | Regra | Fonte |
|---|---|---|---|
| T1 | Segurança | S3 sem server-side encryption | docstring ✅ + inline ✅ + teste ✅ |
| T2 | Segurança | SG ingress 0.0.0.0/0 | ✅ ✅ ✅ |
| T3 | Segurança | RDS sem storage_encrypted | ✅ ✅ ✅ |
| **T4** | **Segurança** | **RDS sem Multi-AZ em produção** | **docstring ✅** + inline ✅ + teste ✅ |
| T5 | FinOps | Compute sem tags/labels | ✅ ✅ ✅ |
| T6 | FinOps | Instância oversized | ✅ ✅ ✅ |
| **T7** | **Operations** | **Recurso crítico sem prevent_destroy** | **docstring ✅** + inline ✅ + teste ✅ |
| extra | Reliability | Terraform sem backend remoto | docstring ✅ + inline ✅ |

> Nota: o "extra" não tem número (é uma regra global fora do loop de resources). A
> docstring antiga o colocava sob "OPERATIONS" enquanto o comentário inline o marcava como
> "EXTRA"; unifiquei para "RELIABILITY — (extra)". Nenhuma mudança de comportamento.

### Diff (docstring do catálogo)

```diff
 SEGURANÇA:
   T1 - S3 sem server-side encryption
   T2 - Security Group ingress 0.0.0.0/0
   T3 - RDS sem storage_encrypted
-  T4 - S3 bucket com public ACL/access (block_public_acls = false)
+  T4 - RDS sem Multi-AZ em ambiente de produção
 
 FINOPS:
   T5 - Recurso de compute sem tags/labels (governança/custo)
   T6 - Instância oversized (m5/m4/c5 families sem justification para tamanho)
 
-RELIABILITY:
-  T7 - RDS sem Multi-AZ em ambiente de produção
-
 OPERATIONS:
+  T7 - Recurso crítico sem lifecycle/prevent_destroy
+
+RELIABILITY:
   (extra) - Terraform sem backend remoto de state (state local)
```

Nenhuma detecção alterada — só o texto do catálogo (docstring) e o reagrupamento de
categorias (que já correspondia ao `domain=` real de cada Finding).

---

## ✅ PASSO 2 — Zerar os 3 RuntimeWarning coroutine-never-awaited

### Diagnóstico (ROOT CAUSE)

`src/cip/agents/react.py` chamava `asyncio.run(<coroutine>)` **dentro de um event loop já
em execução** (o loop do ReAct `run()`, async). `asyncio.run()` não pode ser chamado de um
loop rodando; ao tentar, a coroutine passada como argumento **nunca é agendada** e o GC
emite `RuntimeWarning: coroutine ... was never awaited`.

Afetava três pontos:

1. `_tool_query_rag` — `asyncio.run(_q())` → vazava `_tool_query_rag.<locals>._q`.
2. `_tool_invoke_specialist` — `asyncio.run(_q())` → mesma coroutine `_q`.
3. `_fallback_to_static` — `asyncio.run(static_orch.handle(...))` → vazava `Orchestrator.handle`.

Além do warning, isso era um **bug latente em produção**: o `query_rag`/`invoke_specialist`
e o fallback estático **nunca executavam de verdade** quando o ReAct rodava sob um loop
async (o caminho normal via `await orch.handle(react_mode=True)`).

### Correção (sem mudar contrato de detecção)

- `_execute_tool` → `async def`; awaita `_tool_query_rag`/`_tool_invoke_specialist`; as
  tools síncronas (`_tool_get_live_data`, `_tool_inspect_iac`) continuam síncronas.
- `_tool_query_rag` / `_tool_invoke_specialist` → `async def`; awaitam `self._engine.query(...)`
  diretamente (sem `asyncio.run`, sem coroutine interna `_q`). Agora usam `self._engine`
  (injetável/mockável) em vez do singleton `get_engine()` — consistente com
  `_fallback_to_static`, que já usava `self._engine`. Em produção `self._engine` default é
  `get_engine()`, logo **comportamento idêntico**.
- `_fallback_to_static` → `async def`; `await static_orch.handle(...)` direto.
- `run()` → `await self._execute_tool(...)` (2 chamadas) e `await self._fallback_to_static(...)` (2 chamadas).

### Ajuste de teste (contrato async)

`tests/test_react.py` tinha 3 chamadas síncronas que agora precisam de await:

- `test_unknown_tool_returns_message` → `await orch._execute_tool(...)` + `async def`.
- `test_query_rag_calls_engine` → `await orch._tool_query_rag(...)` + `async def`.
- `test_invoke_specialist_uses_prompt` → `await orch._tool_invoke_specialist(...)` + `async def`.

Todos os três já eram `@pytest.mark.asyncio` (ou ganharam o mark), então a mudança é pura
mecânica de await, sem afrouxar nenhuma asserção.

### Efeito colateral benéfico

Ao usar `self._engine` (o mock injetado nos testes de loop) em vez de `get_engine()` real,
os testes de loop deixaram de instanciar o `PGVectorStore`/pool psycopg3 — eliminando também
o `RuntimeWarning: coroutine 'Connection._cancel' was never awaited` (teardown do pool
assíncrono do psycopg3) que emergia quando o engine real era tocado, e reduzindo o tempo do
`test_react.py` de ~18s para ~3s.

---

## ✅ PASSO 3 — Validação

### Suíte principal

```
$ podman exec cip-api sh -lc "IS_TESTING=1 python -m pytest -q \
    --ignore=tests/test_smoke_ask.py --ignore=tests/test_ingest_delta.py"
590 passed, 19 skipped, 1 warning in 277.51s
```

- **0 failed** (590/590).
- Único warning: `PytestRemovedIn10Warning` (depreciação de fixture class-scoped em
  `test_mock_cloud_cli.py`) — **pré-existente**, não é RuntimeWarning, fora do escopo.

### test_react.py isolado (com `-W error::RuntimeWarning`)

```
$ podman exec cip-api sh -lc "IS_TESTING=1 python -m pytest tests/test_react.py -W error::RuntimeWarning -q"
19 passed in 2.96s        # 0 warnings
```

Antes da correção: `19 passed, 7 warnings` (RuntimeWarning de coroutine nunca awaitada).

### Homolog full 1x (LLM real MiniMax M3)

`python scripts/homolog_validate.py --strict` (sem `IS_TESTING=1`, provider `minimax`)
→ **10/10**, acc 5.00 em todos os casos.

> ⚠️ Diagnóstico de processo: uma primeira tentativa com `IS_TESTING=1` derrubou o
> homolog para 0/10 porque `IS_TESTING=1` força `_StubLLM` (determinístico) no lugar do
> MiniMax real — o stub não gera os `must_mention`, então a acc despenca. Re-rodado **sem**
> `IS_TESTING=1`, fechou em 10/10. O report `eval/results/homolog_report.md`/`.json` foi
> re-sincronizado com a rodada real (10/10). Nenhuma mudança de código foi necessária para
> o gate.

---

## 📁 Artefatos alterados

| Arquivo | Mudança |
|---|---|
| `src/cip/inspection/terraform.py` | docstring do catálogo normalizada (T4=Multi-AZ, T7=prevent_destroy + categorias) |
| `src/cip/agents/react.py` | tools/fallback async (sem `asyncio.run`); `self._engine` em vez de `get_engine()` |
| `tests/test_react.py` | 3 testes ajustados para o contrato async das tools |
| `eval/results/homolog_report.md` + `.json` | re-sincronizados com a rodada real 10/10 (minimax) |
| `docs/46-round-22.8-catalog-cleanup.md` | este documento |

---

## 🎯 Gaps para review (KIRO)

1. O `PytestRemovedIn10Warning` (fixture class-scoped como instance method em
   `test_mock_cloud_cli.py`) segue aberto — depreciação do pytest 10, fora do escopo
   cosmético deste round.
2. As tools `_tool_get_live_data`/`_tool_inspect_iac` permanecem **síncronas** dentro de um
   `_execute_tool` agora async — se um dia ganharem I/O assíncrono, precisarão virar async
   também (hoje são CPU-bound, então correto).
3. O "extra" backend-remoto do catálogo terraform continua sem número (T8?) — decidir se
   vale numerar para fechar o catálogo em 8 regras explícitas.
