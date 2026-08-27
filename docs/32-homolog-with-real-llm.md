# Homologação com LLM Real (Round 22+)

> Guia para validar o CIP end-to-end com um LLM real (MiniMax M3, Bedrock,
> OpenAI) em ambiente local, cobrindo **todos** os knowledge areas: AWS /
> GCP / Azure + **Software Architecture patterns** + **case studies**.

## 🎯 O que é diferente deste homolog?

| | `make homolog` | `make homolog-real` |
|---|---|---|
| Provider LLM | `stub` (sem rede) | `minimax`/`bedrock`/`openai` (REAL) |
| Latência esperada | < 1s (mock) | 1–5s por query |
| Custo | $0 | ~$0.01–0.05 por query |
| Casos cobertos | Disponibilidade da API | Qualidade das respostas (rubrica) |
| Knowledge areas | 1 (cloud atual) | **5** (aws, gcp, azure, software_arch, case_studies) |
| Gate | API health ≥ ok | Score médio ≥ 60% menções + grounding |

Use `make homolog` para sanity-check rápido de fumaça.
Use `make homolog-real` para validar **qualidade real do modelo** antes de produção.

---

## 🚀 Setup (3 passos)

### 1) Subir a stack (igual ao homolog clássico)

```bash
make homolog          # ou: make homolog-fast se a KB já está populada
```

Isso sobe Postgres+pgvector, aplica schema + migration 002, ingere a KB
(incluindo `architecture` + `case-studies` Round 22).

### 2) Configurar o LLM real

```bash
# Opção A — MiniMax M3 (padrão do .env.example)
export LLM_PROVIDER=minimax
export LLM_MODEL=MiniMax-M3
export LLM_API_KEY=sk-cp-SEU-TOKEN
export LLM_BASE_URL=https://api.minimax.chat/v1

# Opção B — Bedrock (Claude Sonnet 4.5)
export LLM_PROVIDER=bedrock
export LLM_MODEL=anthropic.claude-sonnet-4-5-20250929-v1:0
# credenciais AWS via env (STS / SSO / IMDS)

# Opção C — OpenAI
export LLM_PROVIDER=openai
export LLM_MODEL=gpt-4o
export LLM_API_KEY=sk-...
```

> **Importante**: `LLM_PROVIDER=stub` é explicitamente **rejeitado** pelo
> `homolog_validate.py` — não dá para homologar qualidade sem LLM real.

### 3) Rodar a homolog

```bash
# Validação completa (5 knowledge areas, ~10 queries, ~30-60s)
make homolog-real

# Foco em software architecture patterns
make homolog-software-arch

# Foco em case studies / postmortems
make homolog-cases

# Variantes do script (controle fino):
python scripts/homolog_validate.py --strict --skip-setup
python scripts/homolog_validate.py --area software_architecture
python scripts/homolog_validate.py --area case_studies
```

---

## 📊 O que é avaliado?

Para cada query do `HOMOLOG_SUITE`, o script valida:

1. **Grounding** — resposta tem `has_grounding=true` (RAG recuperou fontes)?
2. **Mentions** — todas as `must_mention` aparecem na resposta?
3. **Latência** — < 10s/query com MiniMax M3 (1.9s p95 com stub)
4. **Custo** — estimado pelo tamanho da resposta × rate por provider
5. **Gate binário** — passa se ≥ 60% das menções + grounding OK

Relatório Markdown + JSON saem em:
- `eval/results/homolog_report.md`
- `eval/results/homolog_results.json`

Exemplo de saída:
```markdown
# Relatório de Homologação — LLM Real (minimax)

**Data**: 2026-08-24T12:34:56Z
**Provider**: `minimax`
**Casos**: 9/10 passaram
**Accuracy média**: 4.30
**Latência média**: 2150 ms
**Custo total estimado**: $0.0234
**Gate**: ❌ FALHOU

## Por knowledge area
| Area | N | Pass | Accuracy | Latência (ms) | Custo (USD) |
|---|---|---|---|---|---|
| aws | 2 | 2/2 | 4.50 | 2100 | $0.0048 |
| software_architecture | 4 | 4/4 | 4.75 | 2300 | $0.0100 |
| case_studies | 2 | 1/2 | 3.50 | 2050 | $0.0050 |
```

---

## 🆘 Troubleshooting

| Sintoma | Causa provável | Solução |
|---|---|---|
| `[FAIL] LLM_PROVIDER=stub detectado` | `.env` ainda em modo dev | `export LLM_PROVIDER=minimax` antes de rodar |
| `connectivity error` | API MiniMax fora do ar | Verificar `LLM_BASE_URL` ou usar Bedrock |
| Score baixo em `case_studies` | KB ainda sem chunks de case studies | Rodar `make ingest-forum-cases` antes |
| `no_grounding` frequente | Ingestão Round 22 não rodou | `make schema-migrate && make ingest` |
| Timeout em 60s | Provider lento / rede ruim | `LLM_TIMEOUT_S=120` no `.env` |
| Custo > $0.05/query | Resposta longa demais | Reduzir `LLM_MAX_TOKENS=1024` |

---

## 🔗 Comandos úteis relacionados

| Comando | Função |
|---|---|
| `make homolog` | Setup completo com stub LLM (fumaça) |
| `make homolog-fast` | Setup sem re-ingestão |
| `make homolog-real` | Validação completa com LLM real + 5 áreas |
| `make homolog-software-arch` | Só arquitetura de software |
| `make homolog-cases` | Só case studies |
| `make ingest-forum-cases` | Busca + ingest de postmortems de fóruns |
| `make forum-fetch` | Só busca URLs em HN/dev.to/Reddit (sem ingest) |
| `make schema-migrate` | Aplica migrations SQL pendentes |
| `make eval-strict` | Eval offline (sem LLM) — gate de qualidade estático |

---

## 🐳 Imagem do container (`target: homolog`)

O `docker-compose.yml` builda o `cip-api` com `target: homolog` (estágio
multi-stage do `Dockerfile`). Esse estágio estende o runtime enxuto (`base`)
com `eval/`, `tests/` e as dev deps (`pytest`), permitindo rodar
`preflight`, `eval-strict` e a suite de testes **dentro** do container — útil
no ambiente Podman/WSL, onde a porta do Postgres não é alcançável do host.

```bash
# rodar eval/testes dentro do container
podman compose exec cip-api pytest
podman compose exec cip-api python scripts/homolog_validate.py --strict
```

> Em **deploy real**, buildar o estágio `base` (imagem enxuta, sem artefatos
> de teste): `docker build --target base .`.

## 📚 Próximos passos

- Adicione suas próprias queries ao `HOMOLOG_SUITE` em
  `scripts/homolog_validate.py` para cobrir cenários do seu domínio.
- Integre `make homolog-real --strict` no CI noturno para validar
  qualidade antes de merges em main.
- Configure Langfuse (em `.env`) para tracing detalhado de cada query
  e comparar latência/custo entre MiniMax M3, Bedrock e OpenAI.
