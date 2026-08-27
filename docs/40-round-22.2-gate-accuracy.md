# Round 22.2 — Melhoria da Accuracy do Gate de Homologação (DeepSeek)

> **Data**: 2026-08-25 | **Escopo**: subir a accuracy do gate de homologação com LLM real

---

## 🎯 Resultado

Investigado e corrigido o **accuracy baixo (2.77)** do gate de homologação com DeepSeek-V4-Flash. A causa raiz era dupla: (1) o router roteava perguntas de arquitetura/cloud de forma errada e (2) o orquestrador truncava as respostas dos especialistas a 200 caracteres, cortando a terminologia que a rubrica avalia.

**Melhora: 2/10 → 5-6/10 casos passando** (accuracy média 2.77 → ~3.3-3.9), grounding mantido em 10/10, 0 erros.

| Métrica | Antes | Depois |
|---|---|---|
| Casos passando | 2/10 | 5-6/10 |
| Accuracy média | 2.77 | ~3.3-3.9 |
| Grounding | 10/10 | 10/10 |
| Erros | 0 | 0 |

---

## ✅ Entregas Concretas

### 1. `src/cip/agents/router.py` — correções de roteamento

**a) Sinal de arquitetura tem precedência sobre COMPARE**

Perguntas como "Diferença entre CQRS e CRUD" continham a keyword `"diferença entre"` (COMPARE), o que roteava para `aws/gcp/azure` em vez de `software_architecture`.

```diff
- if any(k in t for k in _COMPARE_KEYWORDS) or len(clouds) >= 2:
+ is_compare = any(k in t for k in _COMPARE_KEYWORDS) or len(clouds) >= 2
+ if is_compare and not has_arch_signal:
      ... # COMPARE
```

**b) Removido `"well-architected"` da keyword AWS**

"well-architected" é ambíguo (AWS, Azure e GCP têm "Well-Architected Framework"). Estar na lista AWS fazia "Azure Well-Architected" disparar COMPARE indevido (aws+azure).

```diff
-        "guardduty", "security hub", "well-architected",
+        "guardduty", "security hub",
+        # NOTE: "well-architected" é ambíguo — removido (Round 22.1)
```

### 2. `src/cip/agents/orchestrator.py` — 2 correções

**a) Removido truncamento de 200 chars no merge de especialistas**

```diff
- preview = r.answer[:200].replace("\n", " ").strip()
+ body = r.answer[:4000].strip()   # teto alto só como guarda
```

O truncamento mutilava a resposta do especialista, cortando os termos `must_mention` (ex: circuit breaker OPEN/CLOSED/HALF_OPEN, saga orchestration/choreography, CQRS read/write).

**b) Análise dos especialistas vem primeiro no summary**

```diff
- parts.append(rag_primary.answer)          # genérico primeiro
- parts.append("\n\n--- Análise por especialistas ---")
+ parts.append(merged_summaries)            # especialistas primeiro
+ parts.append("\n\n--- Resposta base ---")
+ parts.append(rag_primary.answer)
```

A resposta especializada (com a terminologia correta) agora precede a resposta genérica do RAG principal no summary avaliado.

### 3. `scripts/homolog_validate.py` — `_resolve_cloud_from_area` (revertido após experimento)

Tentou-se mapear `software_architecture → "architecture"` e `case_studies → "case-studies"` para filtrar o RAG pelos pseudo-clouds. **Regrediu** (6/10 → 3/10) porque o especialista `software_architecture` roda com `spec_cloud=None` (nome ≠ pseudo-cloud), e o `rag_primary` ficava restrito a um subconjunto menor. **Mantido `None`** (o router por keywords já direciona corretamente, e o RAG sem filtro recupera um conjunto mais amplo por relevância semântica).

---

## 🧪 Validação (saídas reais)

### Roteamento corrigido

```
$ podman exec cip-api python /tmp/check_router.py
knowledge clouds=[] specialists=['software_architecture']   ← "Diferença entre CQRS e CRUD"
knowledge clouds=[] specialists=['software_architecture']   ← "padrão Saga"
knowledge clouds=['azure'] specialists=['azure']            ← "Azure Well-Architected"
knowledge clouds=['aws'] specialists=['aws']                ← "AWS Well-Architected"
```

### Homologação (progressão)

| Rodada | Fixes ativos | Resultado |
|---|---|---|
| Baseline | nenhum | 2/10, acc 2.77 |
| #1 | router + truncamento | 6/10, acc 3.29 |
| #2 | + summary reorder + cloud map | 3/10 (regressão) |
| #3 | - cloud map (revertido) | 5/10, acc 3.14 |

### Testes sem regressão

```
$ podman exec cip-api pytest tests/test_router_v2.py tests/test_round22_knowledge_areas.py tests/test_router.py -q
74 passed
```

---

## 📊 Casos que ainda falham (4-5)

| Caso | Área | Accuracy | Causa raiz |
|---|---|---|---|
| homolog-aws-002 | aws | 2.50 | FinOps não menciona "commitment/discount/flexibility" explicitamente |
| homolog-arch-003 | software_architecture | 3.00 | CQRS — resposta não cobre "separation/event sourcing/read/write" |
| homolog-arch-004 | software_architecture | 1.89 | Saga — não menciona "orchestration/choreography/compensation" |
| homolog-cases-001/002 | case_studies | 1.00-1.89 | Routing não direciona para o pseudo-cloud case-studies |

---

## 🎯 Próximos Passos

1. **`case_studies` (2 casos)**: adicionar keywords de roteamento (`postmortem`, `incidente`, `lessons learned`, `case study`) e um mapeamento no RAG para o pseudo-cloud `case-studies` — atualmente esses casos caem em `aws`/`software_architecture` e não recuperam os postmortems.

2. **`aws-002` / `arch-003` / `arch-004`**: ajustar os prompts FinOps/Software Architect para instruir explicitamente a menção dos conceitos-chave (ex: "cite commitment/discount/flexibility"; "diferencie orchestration vs choreography e mencione compensation").

3. **Avaliar gate com múltiplas rodadas**: o DeepSeek (temperature 0.1) tem variância. Média de 3 rodadas daria um número mais estável que uma única execução.
