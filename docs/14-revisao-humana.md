# Processo de Revisão Humana — CIP Quality Gate

> **Data**: 2026-08-24 | **Versão**: 1.0
> **Fase**: 5 — Quality Gate
> **Documento complementar**: `docs/09-plano-execucao-llm-cloud.md`

---

## 🎯 Objetivo

Garantir que a LLM especialista do CIP atinja score ≥ 4.0 em todos os critérios da rubrica antes do go-live, combinando **scoring automatizado** (5 critérios, run_eval.py) com **revisão humana** por arquitetos seniores cloud (complementar e auditoria).

---

## 👥 Time de Revisores

| Papel | Responsabilidade | Quantidade |
|---|---|---|
| Arquiteto Cloud AWS | Revisão de cenários AWS + FinOps/Security | 1-2 |
| Arquiteto Cloud GCP | Revisão de cenários GCP + SRE | 1 |
| Arquiteto Cloud Azure | Revisão de cenários Azure | 1 |
| Arquiteto Multi-Cloud | Comparações e trade-offs cross-cloud | 1 |
| Engenheiro DevOps/K8s | Cenários IAC + Kubernetes | 1 |

**Total**: 5 arquitetos × 20 cenários cada = 100 avaliações humanas (5-arquitetos avaliam cada cenário, com pesos).

---

## 📋 Rubrica de Avaliação Humana

Cada arquiteto avalia 20 cenários usando **exatamente a mesma rubrica** do scoring automatizado (1-5 por critério):

| Critério | Definição | 1 (Péssimo) | 5 (Excelente) |
|---|---|---|---|
| **Accuracy** | Correção técnica do conteúdo | Fatos errados ou inventados | 100% correto, sem alucinação |
| **Grounding** | Resposta ancorada em fonte oficial | Sem fonte, "achismo" | Citou URL oficial + framework |
| **Citation** | Citações no formato `[cloud, service, title, url]` | Sem citações | ≥3 citações bem formadas |
| **Format** | Estrutura da resposta | Texto corrido, sem ordem | Resumo + achados + plano + referências |
| **Zero-Price** | Sem preços inferidos de memória | Citou $ específico sem tool ao vivo | Nenhum preço (ou só de tool) |

### Escala Comportamental

```
1 — Péssimo:   Resposta inutilizável, erros graves ou alucinações
2 — Ruim:      Resposta falha no básico, requer reescrita completa
3 — OK:        Resposta utilizável mas com gaps significativos
4 — Bom:       Resposta sólida, pequenos ajustes necessários
5 — Excelente: Resposta exemplar, pode ir direto para produção
```

---

## 📊 Workflow de Revisão

### Passo 1: Scoring Automatizado
```bash
python eval/run_eval.py --api http://api.cip.internal --report-md --strict
```
- Executa 95 casos (60 knowledge + 10 IAC + 5 compare + 10 sec + 10 cost)
- Calcula scores automatizados
- **Gate**: bloqueia se algum critério < 4.0 OU > 5% violações zero-price

### Passo 2: Atribuição de Cenários
Cada arquiteto recebe 20 casos balanceados:
- 7-8 casos de **conhecimento** (cloud-aligned com sua especialidade)
- 4-5 casos de **IAC review**
- 3 casos de **comparação multi-cloud**
- 2-3 casos de **custo**
- 2 casos de **segurança**

**Distribuição**: 5 arquitetos × 20 casos = 100 revisões humanas (cada caso avaliado por 1 arquiteto especialista + média ponderada).

### Passo 3: Avaliação Manual
Para cada caso, o arquiteto:
1. Lê a pergunta + payload (se houver)
2. Analisa a resposta gerada pela LLM
3. Marca scores 1-5 para cada critério
4. Comenta observações qualitativas (opcional)
5. Submete via formulário (Google Forms / Notion / GitHub PR)

### Passo 4: Consolidação
```python
# Pseudo-código de consolidação
for case in cases:
    auto_score = auto_eval[case.id]
    human_scores = [r.score for r in human_reviews[case.id]]
    
    # Média ponderada: 60% humano, 40% automático
    final_score = weighted_mean(human_scores, weight=0.6) + \
                  weighted_mean(auto_score, weight=0.4)
    
    # Flag para revisão adicional se divergência > 1.0
    if abs(human_avg - auto_score.avg) > 1.0:
        flag_for_extra_review(case.id)
```

### Passo 5: Gate Final
| Critério | Score final | Status |
|---|---|---|
| Accuracy ≥ 4.0 (todos os casos) | Computado | Go/No-Go |
| Grounding ≥ 4.0 | Computado | Go/No-Go |
| Citation ≥ 4.0 | Computado | Go/No-Go |
| Format ≥ 4.0 | Computado | Go/No-Go |
| Zero-Price ≥ 4.0 | Computado | Go/No-Go |
| Custo mediano < $0.05 | Computado | Go/No-Go |
| Nenhum caso com accuracy < 3.0 | Computado | Go/No-Go |

**Bloqueio**: qualquer critério falha → **NO-GO** até regressão resolvida.

---

## 📈 Critérios de Aceitação por Categoria

### Knowledge (60 casos)
- ≥90% das respostas devem citar fonte oficial (URL clicável)
- Accuracy ≥ 4.5 (conhecimento factual é mais fácil de validar)
- Trade-offs devem ser explícitos quando relevantes
- **Trade-off**: comparação multi-cloud deve usar tabela

### IAC Review (10 casos)
- ≥80% dos findings devem ter severidade correta
- Pelo menos 1 finding crítico para payloads com problemas graves
- Recomendações devem ser acionáveis (não genéricas)
- Estimativa de impacto $ quando relevante (FinOps)

### Comparação (5 casos)
- Tabela obrigatória quando comparando 3+ opções
- Trade-offs devem cobrir: custo, complexidade, resiliência, vendor lock-in
- Cada cloud deve ter ≥2 features específicas mencionadas

### Custo (10 casos)
- ≥80% das respostas devem ter orientação para coleta via tool ao vivo
- Quando tools não disponíveis: declarar explicitamente e sugerir como coletar
- Estimativas de $ range são aceitáveis (não preço exato)

### Segurança (10 casos)
- Recomendações devem citar framework (WAF, CIS Benchmarks, etc.)
- Severidade deve seguir padrão CVSS / OWASP quando aplicável
- Trade-off entre segurança e usabilidade deve ser mencionado

---

## 🔧 Formato de Submissão

Para cada caso, o arquiteto preenche:

```yaml
case_id: know-001
reviewer: arq-aws-01
review_date: 2026-08-25

scores:
  accuracy: 5
  grounding: 4
  citation: 5
  format: 4
  zero_price: 5

comments: |
  Resposta cobriu Savings Plans e Reserved Instances com clareza.
  Poderia ter mencionado Saving Plans flexibility (Compute vs EC2 Instance).

notes:
  - "Excelente uso de [aws, ec2, Savings Plans] como citação"
  - "Faltou menção explícita ao Compute Savings Plans vs EC2 Instance SP"

flag_for_revision: false
```

Submissão via:
- **GitHub PR**: arquivo em `eval/reviews/<reviewer>/<case_id>.yaml`
- **CI gate**: workflow valida que ≥5 arquitetos submeteram antes de fechar release

---

## 🔄 Processo de Iteração

Quando o gate falha:

1. **Análise de causa raiz**: padrão de falha (sempre mesmo critério? mesmo cloud?)
2. **Fix targeted**:
   - Accuracy < 4.0 → revisar ingestion + adicionar fonte oficial
   - Grounding < 4.0 → ajustar retrieval_min_score ou expandir base
   - Citation < 4.0 → reforçar system prompt
   - Format < 4.0 → revisar template de resposta
   - Zero-Price violações → bloquear tools-only em perguntas de preço
3. **Re-rodar eval**: gate deve passar para promover

---

## 📊 Histórico de Rodadas

| Rodada | Data | Score Médio | Gate | Aprovado por |
|---|---|---|---|---|
| Round 5 | 2026-08-24 | 3.30 (offline) | FAIL | — (placeholder) |
| (futuro) | — | — | — | — |

**Nota**: O score 3.30 do Round 5 é em modo offline (sem LLM). O score real virá quando integrado com Bedrock/Claude e revisores humanos.

---

## 🎯 Cronograma de Revisão Humana

| Etapa | Duração | Owner |
|---|---|---|
| Atribuição de 100 cenários a 5 arquitetos | 1 dia | Tech Lead |
| Submissão de reviews (5 × 20 = 100) | 5 dias úteis | Arquitetos |
| Consolidação + flag de divergências | 1 dia | QA Lead |
| Review adicional de casos divergentes | 1 dia | Tech Lead + Arquiteto sênior |
| Decisão final go/no-go | 1 dia | Engenheiro Sênior |

**Total**: 9-10 dias úteis para 1 ciclo completo.

---

## ✅ Checklist de Pronto para Produção

- [ ] Round automatizado: todos os critérios ≥ 4.0 (gate passou)
- [ ] 100 reviews humanas submetidas
- [ ] Score final (60% humano + 40% auto) ≥ 4.0 em todos os critérios
- [ ] Nenhum caso com accuracy < 3.0 (humano)
- [ ] Divergência humano/auto ≤ 1.0 ponto
- [ ] Custo mediano < $0.05/query
- [ ] 100% zero-price compliance
- [ ] Relatório final publicado em `eval/results/final_eval_report.md`

---

## 📌 Próximas Ações

1. **Imediato**: rodar `python eval/run_eval.py --api $API_URL --strict` em staging
2. **Esta semana**: contratar 5 arquitetos seniores cloud para revisão
3. **Próximas 2 semanas**: executar 100 reviews humanas + consolidação
4. **Gate final**: se passar, promover para produção (Fase 6)

---

**Status atual**: infraestrutura de eval (run_eval.py, test_cases.json, gate automatizado) 100% implementada. Aguardando LLM real + revisores humanos para primeira rodada completa.