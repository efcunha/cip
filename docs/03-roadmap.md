# Roadmap de implementação

Baseado na espinha dorsal RAG-first (MiniMax) com estrutura de especialistas (CIP) e
fine-tuning de persona (Deep) como fase final opcional.

## Fase 1 — MVP RAG (2-3 semanas)
**Objetivo:** assistente que responde perguntas sobre as 3 clouds com citação de fonte.
- Provisionar Postgres+pgvector, criar schema.
- Ingerir Well-Architected (AWS), Architecture Framework (GCP), Well-Architected (Azure).
- Subir API `/ask` com filtro por cloud/serviço.
- **Aceite:** responde 20 perguntas de conhecimento com fonte citada; latência p95 < 5s.

## Fase 2 — Pipeline de ingestão completo (1-2 semanas, paralelo)
**Objetivo:** cobertura dos top 50 serviços por cloud.
- `sources.yaml` com fontes priorizadas; chunking markdown-aware + semântico.
- Re-ingestão mensal agendada + detecção de drift (diff de changelog).
- **Aceite:** ~30k páginas indexadas; dedupe por `content_hash` funcionando.

## Fase 3 — Tools cloud read-only (1-2 semanas)
**Objetivo:** dados ao vivo de custo/inventário.
- Wrappers AWS/Azure/GCP (Cost Explorer, Advisor, Recommender).
- IAM read-only aplicado em sandbox (ver `iac/`).
- **Aceite:** pergunta "onde economizar?" retorna números reais de custo, não inferência.

## Fase 4 — Especialistas + Inspection Engine (2-3 semanas)
**Objetivo:** análise profunda por domínio e de arquivos IaC/K8s.
- Orquestrador + roteamento; especialistas FinOps, Security, K8s, Terraform.
- Inspection Engine: regras Terraform/HCL e Kubernetes.
- **Aceite:** dado um `.tf`, retorna findings priorizados com severidade + impacto $.

## Fase 5 — Validação com arquitetos (2 semanas)
**Objetivo:** garantir qualidade antes de produção.
- Suíte de 60 cenários; rubrica 1-5; 5 arquitetos revisam.
- **Aceite:** score médio ≥ 4.0 em todos os critérios; custo/query < $0.05.

## Fase 6 — Fine-tuning de persona (1-2 meses, OPCIONAL)
**Objetivo:** refinar formato/persona (NÃO conhecimento).
- Dataset sintético curado (5-10k exemplos, revisão humana de 30%).
- LoRA/QLoRA sobre Llama 3.3 70B ou modelo equivalente.
- **Aceite:** melhora mensurável em formato/consistência sem regressão factual.

## Critérios globais de "pronto para produção"
- Score rubrica ≥ 4.0 (todos critérios).
- Latência p95 < 5s.
- Custo por query < $0.05.
- Zero preço inferido (100% via tool ao vivo, verificado em auditoria).
- Cobertura de re-ingestão mensal ativa.

## Cronograma e custo (referência)

| Componente | MVP (managed) | Produção (self-hosted 70B) |
|---|---|---|
| Vector DB (RDS pgvector) | ~$80/mês | ~$400/mês |
| Embeddings (CPU/GPU) | ~$50/mês | ~$200/mês |
| LLM inference | ~$500-2000/mês (Bedrock) | ~$1500-3000/mês (2×A100) |
| Storage + observabilidade + tools | ~$80/mês | ~$250/mês |
| **Total aprox.** | **$700-2200/mês** | **$2300-3800/mês** |

> Comece managed (Bedrock + RDS); migre para self-hosted quando o volume justificar.
