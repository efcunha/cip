# Planejamento de Próximas Fases — Cloud Intelligence Platform

> Baseado na análise do estado atual do código e no roadmap original (`03-roadmap.md`).
> Atualizado em: Julho 2026.

---

## Estado Atual (Assessment)

| Componente | Status |
|---|---|
| Config + Settings (pydantic-settings) | Implementado |
| API FastAPI (`/ask`, `/analyze`, `/health`) | Implementado |
| RAG Engine (retriever + filtros + anti-alucinação) | Implementado |
| Pipeline de ingestão (ingest.py, chunking, sources.yaml) | Estrutura pronta, fontes a popular |
| Router/Classificador (heurístico por keywords) | Implementado |
| Orquestrador (RAG + tools + inspeção) | Implementado |
| Cloud Tools (registry + wrappers AWS/Azure/GCP) | Estrutura pronta, chamadas reais pendentes |
| Inspection Engine (dispatch TF + K8s) | Estrutura pronta, regras pendentes |
| Modelos de domínio (Finding, Plan, Result) | Implementado |
| Schema SQL (pgvector + HNSW) | Implementado |
| IAC (policies read-only) | Implementado |
| Testes | 2 arquivos, cobertura básica |
| Eval suite | Estrutura pronta (60 cenários placeholder) |

**Resumo:** a arquitetura está montada ponta-a-ponta. O próximo passo é tornar cada
componente funcional com dados e integrações reais.

---

## Caminho Crítico

```
1A (MVP funcional) ──► 2 (Tools ao vivo) ──► 3 (Regras Inspection) ──► 4 (Especialistas) ──► 5 (Eval) ──► 6 (Produção)
       │
       └── 1B (Hardening ingestão, paralelo)
```

**Timeline total estimado:** 10-14 semanas até production-ready (excluindo Fase 7).

---

## Fase 1A — MVP Funcional (end-to-end rodando)

**Prazo:** 1-2 semanas  
**Objetivo:** `/ask` retorna respostas fundamentadas para as 3 clouds.

### Tarefas

1. Popular `sources.yaml` com URLs reais (Well-Architected AWS, Architecture Framework GCP, Well-Architected Azure).
2. Executar ingestão contra docs reais — validar chunking + embeddings.
3. Validar índice pgvector + HNSW com ~5k chunks.
4. Teste end-to-end: pergunta → retrieval → LLM → resposta com citação.
5. Integração Bedrock verificada (ou fallback OpenAI).
6. `docker compose up` → demo local completa funcionando.

### Critérios de Aceite

- 20 perguntas respondidas com fonte citada.
- Latência p95 < 5s.
- Zero resposta sem grounding (retorna "não encontrei" quando não há contexto).

---

## Fase 1B — Hardening do Pipeline de Ingestão

**Prazo:** 1 semana (paralelo com 1A)  
**Objetivo:** Ingestão confiável e repetível.

### Tarefas

1. Implementar dedupe por `content_hash` no upsert.
2. Chunking markdown-aware (headers como boundaries, não split arbitrário).
3. Progress tracking + resume on failure.
4. Testar com crawling real (tratar rate limits, links quebrados).
5. Adicionar modo `--dry-run` para validação antes de persistir.

### Critérios de Aceite

- Re-ingestão idempotente (sem duplicatas).
- Falha parcial não corrompe o índice existente.
- Logs estruturados com contagem de chunks por source.

---

## Fase 2 — Tools Cloud Read-Only (dados ao vivo)

**Prazo:** 2 semanas  
**Objetivo:** Dados reais de custo/inventário das contas AWS/Azure/GCP.

### Tarefas

1. `AWSCostTools.summarize()` → chamada real ao Cost Explorer (últimos 30 dias, top serviços).
2. `AzureAdvisorTools.summarize()` → recomendações reais do Advisor.
3. `GCPRecommenderTools.summarize()` → API Recommender real.
4. Setup IAM sandbox validado (usar policies de `iac/`).
5. Degradação graceful: credenciais ausentes → skip, não crash.
6. Teste de integração com conta real (sandbox).

### Critérios de Aceite

- Pergunta "onde economizar?" retorna números reais em $.
- Sem credenciais → resposta RAG pura (sem erro 500).
- Tools executam em < 3s (timeout + cache se necessário).

---

## Fase 3 — Regras do Inspection Engine

**Prazo:** 2 semanas  
**Objetivo:** Findings úteis a partir de arquivos Terraform/K8s.

### Tarefas

1. **Terraform rules:**
   - Recursos públicos (S3, SG ingress 0.0.0.0/0)
   - Sem criptografia (EBS, RDS, S3)
   - Sem tags obrigatórias
   - Instâncias oversized (heurística por tipo)
   - Sem lifecycle/prevent_destroy em recursos críticos
2. **Kubernetes rules:**
   - Containers privilegiados
   - Sem resource limits/requests
   - hostNetwork habilitado
   - RBAC amplo (ClusterRoleBinding com `*`)
   - Sem liveness/readiness probes
3. Estimativa de severidade + impacto financeiro por regra.
4. `/analyze` com payload IaC → findings priorizados.
5. Testar com manifests reais (10+ cenários TF, 10+ K8s).

### Critérios de Aceite

- Dado um `.tf`, retorna findings com severidade + impacto $.
- Dado um manifest K8s, identifica pelo menos 5 categorias de risco.
- Zero false positive em cenários de baseline segura.

---

## Fase 4 — Especialistas + Orquestração Avançada

**Prazo:** 2-3 semanas  
**Objetivo:** Análise profunda por domínio com múltiplos especialistas.

### Tarefas

1. Prompts de especialistas: `finops`, `security`, `sre`, `kubernetes`, `terraform`.
2. Cada especialista = system prompt focado + filtro de retrieval + tools opcionais.
3. Orquestrador roteia para 1-3 especialistas por query (não todos).
4. Lógica de consolidação: merge findings, dedupe, priorização cross-domain.
5. Modo agente ReAct/function-calling (LlamaIndex AgentRunner) para queries complexas.
6. Gestão de context window (truncar se exceder budget do LLM).

### Critérios de Aceite

- Query multi-domínio produz relatório estruturado com findings de 2+ especialistas.
- Formato padrão mantido (resumo executivo → riscos → plano → roadmap → referências).
- Latência p95 < 8s mesmo com 3 especialistas acionados.

---

## Fase 5 — Quality Gate + Validação

**Prazo:** 2 semanas  
**Objetivo:** Qualidade mensurável antes de produção.

### Tarefas

1. Expandir `eval/test_cases.json` para 60 cenários (20 por cloud).
2. Eval automatizado: `run_eval.py` com scores de accuracy, grounding, format, citation.
3. Rubrica 1-5: correção factual, acionabilidade, qualidade de citação, formato.
4. Revisão humana: 5 arquitetos avaliam 20 cenários cada.
5. Métrica de custo/query rastreada.
6. Fix de regressões encontradas na avaliação.

### Critérios de Aceite

- Score médio ≥ 4.0 em todos os critérios.
- Custo por query < $0.05.
- Zero preço inferido (100% via tool ou resposta "não encontrei").
- Nenhum cenário com score < 3.0 em correção factual.

---

## Fase 6 — Production Hardening

**Prazo:** 2 semanas  
**Objetivo:** Deployável, observável, seguro.

### Tarefas

1. Autenticação nos endpoints (API key ou OAuth2).
2. Rate limiting + isolamento por tenant.
3. Integração Langfuse para tracing (custo por query, breakdown de latência).
4. Logging estruturado → export para CloudWatch/Datadog.
5. Pipeline CI/CD (build, test, lint, deploy).
6. Cron de re-ingestão mensal (detecção de drift via changelog diff).
7. Health checks avançados + alertas (degradação de retrieval, LLM timeout, tool failure rate).

### Critérios de Aceite

- Deploy automatizado em < 5min após merge.
- Observabilidade: dashboard com latência, custo, grounding rate, error rate.
- Tenant isolation validado (tenant A não vê dados de tenant B).
- Re-ingestão mensal executando sem intervenção manual.

---

## Fase 7 (Opcional) — Fine-tuning de Persona

**Prazo:** 1-2 meses  
**Objetivo:** Consistência de formato/tom sem alterar camada factual.

### Tarefas

1. Gerar dataset sintético (5-10k exemplos de queries reais + respostas ideais).
2. Revisão humana de 30% dos exemplos.
3. LoRA/QLoRA sobre Llama 3.3 70B (ou equivalente da época).
4. Eval A/B: fine-tuned vs base → melhora em formato/consistência sem regressão factual.
5. Deploy como opção alternativa de modelo.

### Critérios de Aceite

- Melhora mensurável em consistência de formato (rubrica de estilo ≥ 4.5).
- Zero regressão em correção factual (score factual ≥ 4.0 mantido).
- Custo de inference < 2x do modelo base.

---

## Estimativa de Custo por Fase

| Fase | Infra mensal (estimada) | Horas dev |
|---|---|---|
| 1A + 1B | ~$80 (RDS pgvector + local dev) | 40-60h |
| 2 | ~$150 (+ sandbox accounts) | 30-40h |
| 3 | ~$80 (sem infra extra) | 30-40h |
| 4 | ~$500-2000 (LLM inference Bedrock) | 40-60h |
| 5 | ~$200 (eval runs + LLM) | 20-30h |
| 6 | ~$300 (CI/CD + observability) | 30-40h |
| 7 | ~$2000-5000 (GPU para treino) | 60-80h |

---

## Próxima Ação Imediata

**Fase 1A, Tarefa 1:** Popular `ingestion/sources.yaml` com URLs reais das documentações
Well-Architected das 3 clouds e executar primeira ingestão de teste.
