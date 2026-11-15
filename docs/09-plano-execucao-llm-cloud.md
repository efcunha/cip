# Plano de Execução — LLM Especialista AWS/GCP/Azure

> **Versão**: 1.0 | **Data**: 2026-08-19 | **Status**: APROVADO PARA EXECUÇÃO
> **Objetivo**: Operacionalizar o CIP como LLM especialista não-genérico para as 3 clouds, indo do estado atual (arquitetura pronta) até produção com score ≥ 4.0 e custo < $0.05/query.

---

## 1. 🎯 Objetivo Final

Colocar em produção um **LLM especialista em AWS, GCP e Azure** que:

- ✅ Responde perguntas técnicas com **citação obrigatória** de fonte oficial
- ✅ Analisa ambientes reais (custo, inventário) via **tools read-only** ao vivo
- ✅ Inspeciona código IaC (Terraform/HCL) e Kubernetes/Helm gerando **findings priorizados**
- ✅ Opera multi-tenant com **isolamento por `tenant_id`**
- ✅ Tem **score ≥ 4.0/5.0** em rubrica de arquitetos seniores
- ✅ Custa **< $0.05 por query**
- ✅ Latência **p95 < 5s** (MVP) / **< 8s** (com especialistas)
- ✅ **Zero preço inferido** (100% via tool ao vivo)

---

## 2. 🧭 Princípios Não-Negociáveis

1. **RAG-first, fine-tuning só para persona** (ADR-0001). Conhecimento factual nunca vai para os pesos — preços e serviços mudam semanalmente.
2. **Anti-alucinação obrigatória**: sem contexto recuperado (`min_score=0.80`) → responder "não encontrei referência confiável".
3. **Whitelist de serviços** no system prompt impede invenção de serviços.
4. **Tools read-only** com trava global `CIP_READONLY=true` (ADR-0003).
5. **Citação obrigatória** `[cloud, serviço, título, url]` em toda resposta.
6. **Pipeline local-first**: implementar → homologar local → validar E2E → subir.
7. **Gate humano** entre fases (revisão antes de avançar).

---

## 3. 📊 Estado Atual (Snapshot)

| Componente | Status | Gap |
|---|---|---|
| Config + Settings | ✅ Pronto | — |
| API FastAPI | ✅ Pronto | — |
| RAG Engine | ✅ Pronto | Falta popular `cloud_docs` |
| Pipeline de ingestão (estrutura) | ✅ Pronto | `sources.yaml` vazio |
| Router/Classificador | ✅ Pronto | — |
| Orquestrador | ✅ Pronto | Lógica básica; especialistas avançados pendentes |
| Tools AWS/Azure/GCP (wrappers) | ✅ Estrutura | Chamadas reais não implementadas |
| Inspection Engine (dispatch) | ✅ Estrutura | Regras TF/K8s funcionais pendentes |
| Schema SQL + pgvector | ✅ Pronto | HNSW index a criar |
| IAC (policies) | ✅ Pronto | — |
| Testes | ⚠️ 5 suítes | Cobertura básica, faltam testes integração |
| Eval suite | ⚠️ Placeholder | 60 cenários a expandir |
| Documentação | ✅ 18 docs | Plano mestre + 7 ADRs + roadmap |

---

## 4. 🛣️ Fases de Execução

```
[1A MVP funcional] ─┬─► [2 Tools ao vivo] ─► [3 Inspection] ─► [4 Especialistas] ─► [5 Eval] ─► [6 Produção] ─► [Produção Live]
                    │
                    └─► [1B Ingestão hardening] (paralelo)
                                                                                          └─► [7 Fine-tuning opcional]
```

### Legenda de prioridade
- 🔴 **Crítico** (bloqueador de produção)
- 🟡 **Importante** (diferenciação vs. concorrentes)
- 🟢 **Desejável** (qualidade de vida)

---

### 🔴 FASE 1A — MVP Funcional End-to-End (1-2 semanas)

**Objetivo:** `/ask` retorna respostas fundamentadas para as 3 clouds, com citação e latência aceitável.

#### Tarefas

| # | Tarefa | Esforço | Dependência | Entregável |
|---|---|---|---|---|
| 1A.1 | Popular `ingestion/sources.yaml` com URLs reais (Well-Architected AWS, Architecture Framework GCP, WAF Azure) | 4h | — | YAML com 50+ URLs priorizadas |
| 1A.2 | Subir Postgres+pgvector via `docker compose` (porta 5432 local) | 2h | — | DB rodando + HNSW index criado |
| 1A.3 | Configurar Bedrock no `.env` (ou fallback `stub` para dev) | 2h | AWS account | `LLM_PROVIDER=bedrock` respondendo |
| 1A.4 | Rodar `python -m cip.ingestion.ingest` com catálogo MVP | 4h | 1A.1, 1A.2 | ~5k chunks indexados |
| 1A.5 | Validar retrieval end-to-end (8 docs, score ≥ 0.80) | 2h | 1A.4 | Logs com scores |
| 1A.6 | Smoke test `/ask` com 20 perguntas (10 AWS, 5 GCP, 5 Azure) | 4h | 1A.5 | Respostas com citação em Markdown |
| 1A.7 | Documentar demo local no README | 2h | 1A.6 | `README.md` atualizado |

**Esforço total:** ~22h | **Duração:** 1 semana (1 dev full-time)

#### Critérios de Aceite

- [ ] 20 perguntas respondidas com fonte citada
- [ ] Latência p95 < 5s
- [ ] Zero resposta sem grounding
- [ ] `docker compose up` → demo local completa

---

### 🟢 FASE 1B — Hardening da Ingestão (paralela, 1 semana)

**Objetivo:** Ingestão confiável, idempotente e observável.

#### Tarefas

| # | Tarefa | Esforço | Entregável |
|---|---|---|---|
| 1B.1 | Implementar dedupe por `content_hash` no upsert | 3h | `ON CONFLICT (content_hash) DO UPDATE` |
| 1B.2 | Chunking markdown-aware (headers como boundaries) | 4h | Parser semântico testado |
| 1B.3 | Progress tracking + resume on failure | 4h | Checkpoint em JSON |
| 1B.4 | Modo `--dry-run` para validação | 2h | Flag CLI |
| 1B.5 | Cron mensal + detecção de drift via changelog diff | 4h | Job agendado + alerta |
| 1B.6 | Logs estruturados com contagem por source | 2h | structlog events |
| 1B.7 | Testes de regressão da ingestão | 3h | 5+ casos pytest |

**Esforço total:** ~22h | **Duração:** 1 semana (paralela à 1A)

#### Critérios de Aceite

- [ ] Re-ingestão idempotente (zero duplicatas)
- [ ] Falha parcial não corrompe índice
- [ ] Logs estruturados com métricas por source

---

### 🔴 FASE 2 — Tools Cloud Read-Only (2 semanas)

**Objetivo:** Dados reais de custo/inventário das contas AWS/Azure/GCP.

#### Tarefas

| # | Tarefa | Esforço | Cloud |
|---|---|---|---|
| 2.1 | `AWSCostTools.summarize()` → Cost Explorer real (30d) | 6h | AWS |
| 2.2 | AWS Rightsizing Recommendations | 4h | AWS |
| 2.3 | AWS Volumes/Snapshots órfãos | 3h | AWS |
| 2.4 | `AzureAdvisorTools.summarize()` → Advisor (Cost/Security/HA) | 6h | Azure |
| 2.5 | Azure Cost Management API | 4h | Azure |
| 2.6 | `GCPRecommenderTools.summarize()` → Recommender (idle, cost) | 6h | GCP |
| 2.7 | GCP Asset Inventory | 4h | GCP |
| 2.8 | Setup IAM sandbox validado (policies de `iac/`) | 3h | Multi |
| 2.9 | Degradação graceful: sem creds → skip, não crash | 3h | Multi |
| 2.10 | Cache + timeout (< 3s por tool) | 3h | Multi |
| 2.11 | Testes integração com sandbox accounts | 8h | Multi |

**Esforço total:** ~50h | **Duração:** 2 semanas

#### Critérios de Aceite

- [ ] "Onde economizar?" retorna **$ reais** (não inferência)
- [ ] Sem credenciais → resposta RAG pura (não 500)
- [ ] Tools executam em < 3s (cache quando aplicável)

---

### 🟡 FASE 3 — Inspection Engine (2 semanas)

**Objetivo:** Findings úteis a partir de arquivos Terraform/K8s.

#### Tarefas Terraform/HCL

| # | Regra | Severidade | Impacto $ |
|---|---|---|---|
| 3.T1 | Recursos públicos (S3, SG ingress 0.0.0.0/0) | Critical | Alto (dados/RCE) |
| 3.T2 | Sem criptografia (EBS, RDS, S3) | High | Médio (compliance) |
| 3.T3 | Sem tags obrigatórias (env, owner, cost-center) | Medium | Baixo (governança) |
| 3.T4 | Instâncias oversized (heurística por tipo/uso) | High | $$-$$$ |
| 3.T5 | Sem `lifecycle`/`prevent_destroy` em críticos | High | Médio (drift) |
| 3.T6 | RDS/Aurora sem Multi-AZ em produção | Medium | Médio (HA) |
| 3.T7 | NAT Gateway sem alarmes de custo | Medium | $ (egress) |

#### Tarefas Kubernetes

| # | Regra | Severidade | Impacto |
|---|---|---|---|
| 3.K1 | Containers privilegiados | Critical | Risco total |
| 3.K2 | Sem `resource.limits`/`requests` | High | Estabilidade |
| 3.K3 | `hostNetwork: true` | High | Segurança |
| 3.K4 | RBAC amplo (`ClusterRoleBinding` com `*`) | Critical | Risco total |
| 3.K5 | Sem `liveness`/`readiness` probes | Medium | Resiliência |
| 3.K6 | Imagem `:latest` ou sem tag | Medium | Reprodutibilidade |
| 3.K7 | Sem `securityContext` (runAsNonRoot) | Medium | Segurança |

#### Tarefas Transversais

| # | Tarefa | Esforço |
|---|---|---|
| 3.8 | Estimativa de severidade + impacto financeiro por regra | 8h |
| 3.9 | `/analyze` com payload IaC → findings priorizados | 6h |
| 3.10 | Testar com 10+ cenários TF e 10+ K8s reais | 8h |

**Esforço total:** ~50h | **Duração:** 2 semanas

#### Critérios de Aceite

- [ ] Dado `.tf` → findings com severidade + impacto $
- [ ] Dado manifest K8s → identifica ≥ 5 categorias de risco
- [ ] Zero false positive em baseline seguro

---

### 🟡 FASE 4 — Especialistas + Orquestração Avançada (2-3 semanas)

**Objetivo:** Análise profunda multi-domínio com roteamento inteligente.

#### Especialistas a implementar (prompts já existem em `prompts/specialists.py`)

| Especialista | Domínio | Filtro retrieval | Tools prioritárias |
|---|---|---|---|
| `aws_specialist` | AWS nativo | `cloud=aws` | AWS Cost, AWS Inventory |
| `gcp_specialist` | GCP nativo | `cloud=gcp` | GCP Recommender, Asset |
| `azure_specialist` | Azure nativo | `cloud=azure` | Azure Advisor, Cost Mgmt |
| `finops_specialist` | Custo multi-cloud | `category=pricing` | Cost tools (todas) |
| `security_specialist` | Segurança | `category=security` | Advisor Security |
| `sre_specialist` | Confiabilidade | `framework=well-architected` | Advisor HA |
| `k8s_specialist` | Kubernetes | categoria `compute` + service=k8s | Inspection K8s |
| `terraform_specialist` | IaC | categoria `governance` | Inspection TF |

#### Tarefas

| # | Tarefa | Esforço |
|---|---|---|
| 4.1 | Roteamento inteligente (1-3 especialistas por query, não todos) | 8h |
| 4.2 | Merge/dedupe de findings cross-domain | 6h |
| 4.3 | Priorização consolidada (severity × $ × effort) | 4h |
| 4.4 | Modo ReAct/function-calling (LlamaIndex AgentRunner) | 12h |
| 4.5 | Gestão de context window (truncar se exceder budget) | 4h |
| 4.6 | Testes de integração multi-especialista | 8h |

**Esforço total:** ~42h | **Duração:** 2-3 semanas

#### Critérios de Aceite

- [ ] Query multi-domínio → relatório com findings de 2+ especialistas
- [ ] Formato padrão mantido (resumo → riscos → plano → roadmap → refs)
- [ ] Latência p95 < 8s mesmo com 3 especialistas acionados

---

### 🔴 FASE 5 — Quality Gate (2 semanas)

**Objetivo:** Qualidade mensurável antes de produção.

#### Tarefas

| # | Tarefa | Esforço |
|---|---|---|
| 5.1 | Expandir `eval/test_cases.json` para 60 cenários reais (20/cloud) | 8h |
| 5.2 | Eval automatizado com rubrica: accuracy, grounding, format, citation | 8h |
| 5.3 | Revisão humana: 5 arquitetos × 20 cenários cada | 16h |
| 5.4 | Métrica de custo/query rastreada | 4h |
| 5.5 | Fix de regressões encontradas na avaliação | 12h |
| 5.6 | Relatório final com score médio e breakdown | 4h |

**Esforço total:** ~52h | **Duração:** 2 semanas

#### Critérios de Aceite (gate de produção)

- [ ] Score médio ≥ 4.0 em **todos** os critérios
- [ ] Custo por query < $0.05
- [ ] **Zero** preço inferido (100% via tool ou "não encontrei")
- [ ] Nenhum cenário com score < 3.0 em correção factual

---

### 🔴 FASE 6 — Production Hardening (2 semanas)

**Objetivo:** Deployável, observável, seguro.

#### Tarefas

| # | Tarefa | Esforço |
|---|---|---|
| 6.1 | Autenticação (API key + OAuth2) | 8h |
| 6.2 | Rate limiting + tenant isolation validado | 6h |
| 6.3 | Integração Langfuse (tracing RAG + custo/query) | 8h |
| 6.4 | Logs estruturados → CloudWatch/Datadog | 4h |
| 6.5 | Pipeline CI/CD (build + test + lint + deploy < 5min) | 8h |
| 6.6 | Cron mensal de re-ingestão (drift via changelog diff) | 4h |
| 6.7 | Health checks avançados + alertas (P0/P1) | 4h |
| 6.8 | Deploy staging + smoke tests | 4h |
| 6.9 | Deploy produção (com flags OFF inicialmente) | 4h |
| 6.10 | Runbook de incidentes | 4h |

**Esforço total:** ~52h | **Duração:** 2 semanas

#### Critérios de Aceite

- [ ] Deploy automatizado em < 5min após merge
- [ ] Dashboard com latência, custo, grounding rate, error rate
- [ ] Tenant A não vê dados de Tenant B (validado em teste)
- [ ] Re-ingestão mensal executando sem intervenção manual

---

### 🟢 FASE 7 — Fine-tuning de Persona (OPCIONAL, 1-2 meses)

**⚠️ Só executar se RAG validado ≥ 4.0.** Objetivo: refinar formato/tom, **NUNCA** gravar fatos.

#### Tarefas

| # | Tarefa | Esforço |
|---|---|---|
| 7.1 | Gerar dataset sintético (5–10k pares pergunta/raciocínio/resposta) | 16h |
| 7.2 | Revisão humana de 30% dos exemplos (descartar alucinações factuais) | 24h |
| 7.3 | Setup treino LoRA/QLoRA (PEFT + TRL `SFTTrainer`) | 8h |
| 7.4 | Hiperparâmetros: `r=64`, `alpha=128`, `dropout=0.05`, lr=2e-4, 3 épocas | 4h |
| 7.5 | Treino sobre Llama 3.3 70B (ou 8B para protótipo barato) | 24h GPU |
| 7.6 | Merge LoRA + deploy (vLLM/TGI ou SageMaker/Vertex/Azure ML) | 8h |
| 7.7 | Eval A/B (fine-tuned vs base) — só promover se melhorar sem regredir | 8h |

**Esforço:** ~92h + 24h GPU | **Duração:** 1-2 meses

#### Critérios de Aceite

- [ ] Melhora mensurável em consistência de formato (rubrica de estilo ≥ 4.5)
- [ ] **Zero regressão** factual (score ≥ 4.0 mantido)
- [ ] Custo de inference < 2× do modelo base

---

## 5. ⏱️ Cronograma Consolidado

```
Semana  1  ▓▓▓▓▓▓▓▓▓▓  Fase 1A (MVP funcional) + 1B (ingestão) [paralelo]
Semana  2  ▓▓▓▓▓▓▓▓▓▓  Fase 1A (conclusão) + 1B (conclusão)
Semana  3  ▓▓▓▓▓▓▓▓▓▓  Fase 2 (Tools AWS)
Semana  4  ▓▓▓▓▓▓▓▓▓▓  Fase 2 (Tools Azure + GCP + integração)
Semana  5  ▓▓▓▓▓▓▓▓▓▓  Fase 3 (Regras Terraform)
Semana  6  ▓▓▓▓▓▓▓▓▓▓  Fase 3 (Regras Kubernetes + integração)
Semana  7  ▓▓▓▓▓▓▓▓▓▓  Fase 4 (Especialistas)
Semana  8  ▓▓▓▓▓▓▓▓▓▓  Fase 4 (ReAct/function-calling)
Semana  9  ▓▓▓▓▓▓▓▓▓▓  Fase 5 (Quality gate)
Semana 10  ▓▓▓▓▓▓▓▓▓▓  Fase 5 (Revisão arquitetos)
Semana 11  ▓▓▓▓▓▓▓▓▓▓  Fase 6 (Auth + observabilidade)
Semana 12  ▓▓▓▓▓▓▓▓▓▓  Fase 6 (CI/CD + deploy produção)
Semana 13+ ░░░░░░░░░░  Fase 7 (Fine-tuning opcional, 4-8 semanas)
```

**Total até produção live:** 10-14 semanas (1 dev sênior full-time).

---

## 6. 💰 Custos Estimados

| Fase | Infra mensal | Horas dev | Custo dev |
|---|---|---|---|
| 1A + 1B | ~$80 (RDS pgvector local) | 44h | ~$3k |
| 2 | ~$150 (+ sandbox accounts) | 50h | ~$3.5k |
| 3 | ~$80 | 50h | ~$3.5k |
| 4 | ~$500–2000 (Bedrock) | 42h | ~$3k |
| 5 | ~$200 (eval runs) | 52h | ~$3.5k |
| 6 | ~$300 (CI/CD + obs) | 52h | ~$3.5k |
| 7 | ~$2000–5000 (GPU treino) | 92h + GPU | ~$8k+ |
| **Total produção** | **$1300–2800/mês** | **~290h** | **~$20k** |

---

## 7. ⚠️ Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| **Bedrock indisponível / quota excedida** | Média | Alto | Fallback `LLM_PROVIDER=local` (vLLM/Ollama) já implementado |
| **Ingestão falha por rate limit** | Alta | Médio | Retry exponencial + cache de headers + modo `--dry-run` |
| **Alucinação de preço por tool retornar cache antigo** | Média | Crítico | TTL curto (1h) + cabeçalho "dados ao vivo de DD/MM" |
| **Latência p95 > 5s** | Média | Alto | HNSW index + `top_k=8` + cache de tool responses |
| **Score eval < 4.0** | Média | Crítico | Gate de produção: bloqueia release até ≥ 4.0 |
| **Custo/query > $0.05** | Baixa | Médio | Reduzir `max_tokens` (default 2048), `top_k=6`, prompt caching |
| **Tools AWS/Azure/GCP sem credenciais no sandbox** | Alta | Médio | Degradação graceful → responde via RAG puro (sem 500) |
| **Fine-tuning regredir factual** | Média | Crítico | Só promover se eval A/B mantiver score ≥ 4.0 factual |

---

## 8. 🎯 Marcos de Validação (Gates)

| Marco | Definição | Bloqueia produção? |
|---|---|---|
| **M1** — MVP responde 20 perguntas | Fase 1A completa | Sim |
| **M2** — Re-ingestão idempotente | Fase 1B completa | Sim |
| **M3** — Tools retornam $ reais | Fase 2 completa | Sim |
| **M4** — Inspection detecta 5+ categorias | Fase 3 completa | Sim |
| **M5** — Multi-especialista orquestrado | Fase 4 completa | Sim |
| **M6** — Score eval ≥ 4.0 | Fase 5 completa | **BLOQUEIO CRÍTICO** |
| **M7** — Deploy produção observável | Fase 6 completa | Go-live |

---

## 9. 📌 Próximas Ações Imediatas (Esta Semana)

### 🟢 Ação 1 — Popular `sources.yaml` (CRÍTICO, 4h)

Adicionar URLs oficiais priorizadas em `ingestion/sources.yaml`:

**AWS (Well-Architected Framework):**
- https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/performance-efficiency-pillar/welcome.html
- https://docs.aws.amazon.com/wellarchitected/latest/sustainability-pillar/welcome.html

**GCP (Architecture Framework):**
- https://cloud.google.com/architecture/framework
- https://cloud.google.com/architecture/framework/system-design
- https://cloud.google.com/architecture/framework/security
- https://cloud.google.com/architecture/framework/reliability
- https://cloud.google.com/architecture/framework/cost-optimization
- https://cloud.google.com/architecture/framework/operational-excellence
- https://cloud.google.com/architecture/framework/performance-optimization

**Azure (Well-Architected Framework):**
- https://learn.microsoft.com/en-us/azure/well-architected/
- https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization
- https://learn.microsoft.com/en-us/azure/well-architected/security
- https://learn.microsoft.com/en-us/azure/well-architected/reliability
- https://learn.microsoft.com/en-us/azure/well-architected/operational-excellence
- https://learn.microsoft.com/en-us/azure/well-architected/performance-efficiency

### 🟢 Ação 2 — Subir Postgres+pgvector (2h)

```bash
cd D:\Projetos\cip
docker compose up -d postgres
docker exec -it cip-postgres psql -U cip -d cip -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker exec -i cip-postgres psql -U cip -d cip < db/schema.sql
```

### 🟢 Ação 3 — Configurar Bedrock (2h)

Criar `.env`:
```env
CIP_ENV=dev
CIP_READONLY=true
LLM_PROVIDER=bedrock
LLM_MODEL=anthropic.claude-sonnet-4-5-20250929-v1:0
EMBED_PROVIDER=local
EMBED_MODEL=intfloat/multilingual-e5-small
EMBED_DIM=384
DATABASE_URL=postgresql://cip:cip@localhost:5432/cip
```

### 🟢 Ação 4 — Rodar primeira ingestão (4h)

```bash
python -m cip.ingestion.ingest --catalog mvp
```

### 🟢 Ação 5 — Smoke test 20 perguntas (4h)

```bash
pytest tests/test_router.py -v
# Adicionar tests/test_smoke_ask.py com 20 casos
```

---

## 10. 📚 Documentos de Referência

| Doc | Propósito |
|---|---|
| `docs/01-analise-recomendacoes.md` | Justificativa arquitetural |
| `docs/02-arquitetura.md` | Diagrama + componentes |
| `docs/03-roadmap.md` | Roadmap original (alto nível) |
| `docs/04-modelo-de-dados.md` | Schema SQL + tabelas |
| `docs/05-fine-tuning.md` | Fase 7 detalhada |
| `docs/06-planejamento-proximas-fases.md` | Assessment + caminho crítico |
| `docs/adr/0001-rag-first-em-vez-de-fine-tuning.md` | ADR-0001 |
| `docs/adr/0002-pgvector-como-vector-db.md` | ADR-0002 |
| `docs/adr/0003-tools-read-only-para-dados-ao-vivo.md` | ADR-0003 |
| `docs/adr/0004-llm-base-e-embeddings.md` | ADR-0004 |

---

## 11. ✅ Resumo Executivo

| Pergunta | Resposta |
|---|---|
| O que precisa ser feito? | **Executar as 6 fases obrigatórias (10–14 semanas).** |
| Quanto custa? | **~$20k dev + $1.3k–2.8k/mês infra.** |
| Quando vai pra produção? | **Semana 12** (sem Fase 7). |
| Risco principal? | **Score eval < 4.0** — bloqueia go-live. |
| Próxima ação imediata? | **Popular `sources.yaml` com 50+ URLs reais (4h).** |
| Vale fine-tuning? | **Só após RAG ≥ 4.0.** É opcional, não obrigatório. |

**O plano está aprovado para execução. Iniciar pela Fase 1A.**