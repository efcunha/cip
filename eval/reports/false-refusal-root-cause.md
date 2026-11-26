# Falsa recusa in-RAG: causa raiz (gemma-3-27b-it, DeepInfra)

Veredito: **content_gap**. Nenhuma das 3 perguntas e falsa recusa de codigo; o corpus nao tem a resposta e o modelo responde `NAO_ENCONTRADO` como manda o prompt. Detalhes: `.agents/tasks/cip-false-refusal/report.md` (nao versionado).

| id | pergunta | o que o top-4 contem | pagina que faltaria | gate |
|---|---|---|---|---|
| in-13 | niveis de consistencia do Cosmos DB | visao geral/introducao; so link de navegacao "Mapping consistency levels"; 0 chunks com "bounded staleness" | `cosmos-db/consistency-levels` | recusa do modelo (3/3 ON e OFF) |
| in-15 | PodDisruptionBudget no Kubernetes | indice scheduling-eviction e ponteiro "Read about PodDisruptionBudget" no Deployment | `concepts/workloads/pods/disruptions` | recusa do modelo (3/3 ON e OFF) |
| in-10 | node pools no AKS | secao Nodes, aviso de aposentadoria Azure Linux 2.0, namespaces, Service do K8s | pagina dedicada a node pools | recusa do modelo ON; OFF era aceitacao falsa |

- Gate de score, validacao de citacao, fallback extrativo e corte de contexto (4x1200) nao participaram: `n_above=8`, outcome `declined`, `reason=None`, e o trecho relevante cabe nos 1200 chars.
- in-10 "regressao" (OFF 0/3 -> ON 3/3): no OFF o modelo respondeu sobre a aposentadoria do Azure Linux 2.0 com citacao valida (resposta fora de assunto que o eval contou como valida, porque `must_mention` bate por acaso). No ON a traducao poe 3 chunks AKS no topo e o modelo recusa de forma correta. A taxa OFF estava inflada.
- Sem essas 3 perguntas sem cobertura, a falsa recusa in-RAG (ON) e 0%.
- Correcao proposta: ingerir as 3 paginas e reavaliar (requer autorizacao de re-ingestao); opcional endurecer o eval contra resposta valida mas fora de assunto. Nenhuma mudanca de codigo ou prompt e necessaria.

## Paginas a ingerir (proposta para aprovacao)
| id | URL de origem sugerida | motivo |
|---|---|---|
| in-13 | https://learn.microsoft.com/azure/cosmos-db/consistency-levels | lista os 5 niveis (strong, bounded staleness, session, consistent prefix, eventual); 0 chunks com "bounded staleness" hoje |
| in-15 | https://kubernetes.io/docs/concepts/workloads/pods/disruptions/ | define PodDisruptionBudget; hoje so ponteiro no Deployment e item de lista em scheduling-eviction |
| in-10 | https://learn.microsoft.com/azure/aks/use-multiple-node-pools (alternativa: https://learn.microsoft.com/azure/aks/manage-node-pools) | define node pools; `concepts-clusters-workloads` ingerida cobre so a visao geral |

## Evidencia de chunking
- Nenhum chunk existente contem a definicao: o tema aparece so em links de navegacao (cosmos-db/nosql/), item de lista (scheduling-eviction, 949 chars) e ponteiro na posicao 1430 do chunk do Deployment. O corte de contexto (4 chunks x 1200 chars) nao esconde conteudo: o trecho relevante, quando existe, esta dentro dos 1200 chars.
- Os `*-raw.json` guardam `left(text,1500)`; contagens vieram desse texto e de regex SELECT no banco remoto (somente leitura).

## Resultado desta etapa
- Nenhum codigo, prompt, DB ou eval alterado; eval nao re-executado (sem mudanca que o justifique). Metricas vigentes (ON, 3 runs): falsa recusa in-RAG 19% (3/16 perguntas sem cobertura; 0% sem elas), recusa out-of-RAG 100%, 0 vazamento de termos off-topic, citacao valida 100%.
- Antes = depois (sem mudanca de codigo).

## Para aprovar
1. Re-ingerir as 3 paginas acima (nao autorizado nesta etapa: requer escrita no DB) e re-medir com `eval/ollama_compare.py --backend openai`, 3 runs, traducao ON.
2. Opcional: endurecer `must_mention` do in-10 (termos de definicao de node pool, ex. "node pool" + "system|user") para o eval nao contar resposta fora de assunto como valida.
3. Opcional: calibrar `retrieval_min_score` antes de subir (todos os top-1 >= 0.70; o gate atual nao discrimina).
