# Re-measure after answer-quality deploy: DeepInfra gemma-3-27b-it, cip-api aa1277a + AKS page re-ingested
- Generated: 2026-11-26 (UTC 23:5x). 3 runs per question, max_tokens=1024, temperature=0.1, top_k=8, min_score=0.5, embedding BAAI/bge-large-en-v1.5. Same `eval/ollama_compare.py`, same questions file (corrected `must_mention`), same model, `retrieval_min_score` untouched (0.50).
- Raw files: `deepinfra-gemma3-answer-quality-retrieval-raw.json`, `-translation-retrieval-raw.json`, `-translation-on-raw.json`, `-translation-off-raw.json`.
- Commands (key read from the Windows user env var into the process only; python from `venv/` because `.venv` has no torch): `ollama_compare.py retrieval`; `translate --backend openai --translation-raw ...`; `generation --backend openai --models google/gemma-3-27b-it --runs 3 --translation on|off --out ...`. The retrieval phase writes `ollama-retrieval-raw.json`; it was copied to the answer-quality file and the tracked original restored.
- "Old raw" = `deepinfra-gemma3-post-ingest-translation-{on,off}-raw.json` recomputed with the corrected `must_mention` (see `.agents/tasks/cip-answer-quality/recount.md`: ON 79.2% -> 95.8% (46/48), OFF 68.8% -> 83.3% (40/48)). "New" = this run.

## Verdict
- Guardrails: in-RAG false refusal 0% (ON), out-of-RAG refusal 100%, 0 off-topic leaks, citation validity 100%. No regression. **No rollback was done.**
- In-RAG on-topic ON: 95.8% (46/48) both before (corrected) and after. The deploy did not move this number; the gain over the 79% in the older report comes from the corrected `must_mention`.
- in-10: no retirement/OS Guard notice in any of the 3 answers. Mentions system/user pools in only 1 of 3 runs (run 3). Not clean on the second criterion.
- OFF mode on-topic fell 83% -> 75% with the same false refusal (12%, in-01/in-04 declines); it is not the production mode and the guardrails held.

## Metrics
### translation ON (production mode)

| Metric | Old raw (recount, corrected must_mention) | New (answer-quality deploy) |
|---|---|---|
| In-RAG false refusal | 0% | 0% |
| In-RAG valid answers | 100% | 100% |
| In-RAG on-topic (valid + must_mention corrigido) | 96% | 96% |
| In-RAG fallback (citacao invalida) | 0% | 0% |
| Out-of-RAG refusal | 100% | 100% |
| Out-of-RAG answered with citation | 0% | 0% |
| Out-of-RAG off-topic leaks (respostas com termo proibido) | 0 | 0 |
| Ambiguous acceptable | 100% | 100% |
| Ambiguous off-topic leaks | 0 | 0 |
| Citation validity (answered) | 100% | 100% |
| Answer TTFT median (s) | 0.74 | 0.65 |
| Answer TTFT p95 (s) | 1.21 | 1.05 |
| Answer total median (s) | 2.67 | 3.09 |
| Answer total p95 (s) | 5.78 | 7.60 |
| Answers (valid) count | 55 | 57 |
| LLM errors | 0 | 0 |

### translation OFF (PT-BR raw query)

| Metric | Old raw (recount, corrected must_mention) | New (answer-quality deploy) |
|---|---|---|
| In-RAG false refusal | 12% | 12% |
| In-RAG valid answers | 88% | 88% |
| In-RAG on-topic (valid + must_mention corrigido) | 83% | 75% |
| In-RAG fallback (citacao invalida) | 0% | 0% |
| Out-of-RAG refusal | 100% | 100% |
| Out-of-RAG answered with citation | 0% | 0% |
| Out-of-RAG off-topic leaks (respostas com termo proibido) | 0 | 0 |
| Ambiguous acceptable | 100% | 100% |
| Ambiguous off-topic leaks | 0 | 0 |
| Citation validity (answered) | 100% | 100% |
| Answer TTFT median (s) | 0.77 | 0.64 |
| Answer TTFT p95 (s) | 1.26 | 1.18 |
| Answer total median (s) | 3.56 | 2.60 |
| Answer total p95 (s) | 7.93 | 6.34 |
| Answers (valid) count | 45 | 45 |
| LLM errors | 0 | 0 |

### Per-question in-RAG outcome, translation ON (old raw -> new; refused / valid / on-topic of 3)

| id | old | new |
|---|---|---|
| in-01 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-02 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-03 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-04 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-05 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-06 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-07 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-08 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-09 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-10 | 0/3 / 3/3 / 1/3 | 0/3 / 3/3 / 1/3 |
| in-11 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-12 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-13 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-14 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-15 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |
| in-16 | 0/3 / 3/3 / 3/3 | 0/3 / 3/3 / 3/3 |

### Failing in-RAG records (new, ON)

- in-10 run 1: outcome=valid reason=None mention=1/2
- in-10 run 2: outcome=valid reason=None mention=1/2

### in-10 answers, verbatim (translation ON, new)

Question: Como funcionam os node pools no Azure Kubernetes Service?
must_mention: ['node pool|pool de nos|pools de nos', 'system|sistema|user pool|pool de usuario|scale set|vmss']

**Run 1** (outcome=valid, mention 1/2, retirement-notice terms present: False)

```
Você pode criar um ou mais node pools em um cluster AKS [1]. A criação e o gerenciamento de múltiplos node pools requer comandos separados para criar/atualizar/deletar (CRUD) [1]. Anteriormente, as operações de cluster usavam a API managedCluster e eram as únicas opções para alterar o control plane e um único node pool [1]. A funcionalidade expõe um conjunto de operações separado para agent pools através da API agentPool e requer o uso do conjunto de comandos az aks nodepool [1]. Quando você adiciona um taint, label ou tag, todos os nodes dentro daquele node pool também recebem o taint, label ou tag [2]. É recomendado aplicar essas propriedades a todo um node pool em vez de nodes individuais [2].
```

**Run 2** (outcome=valid, mention 1/2, retirement-notice terms present: False)

```
Você pode criar um ou mais node pools em um cluster AKS [1]. A criação e gerenciamento de múltiplos node pools requer comandos separados para criar/atualizar/deletar (CRUD) [1]. Anteriormente, as operações de cluster usavam a API managedCluster e eram as únicas opções para alterar o control plane e um único node pool [1]. A funcionalidade expõe um conjunto de operações separado para agent pools através da API agentPool e requer o uso do conjunto de comandos az aks nodepool [1]. Quando você adiciona um taint, label ou tag, todos os nodes dentro daquele node pool também recebem o taint, label ou tag [2]. É recomendado aplicar essas propriedades a todo um node pool em vez de nodes individuais [2].
```

**Run 3** (outcome=valid, mention 2/2, retirement-notice terms present: False)

```
Você pode criar um ou mais node pools em um cluster AKS [1]. Essa funcionalidade permite mais controle sobre a criação e gerenciamento de múltiplos node pools e requer comandos separados para operações de CRUD (criar/atualizar/excluir) [1]. Anteriormente, as operações de cluster usavam a API managedCluster e eram as únicas opções para alterar o control plane e um único node pool [1]. Ao adicionar um taint, label ou tag, todos os nodes dentro do node pool também recebem o taint, label ou tag [2]. É recomendado aplicar essas propriedades a todo um node pool em vez de nodes individuais [2]. System pools devem conter pelo menos dois nodes, e user node pools podem conter zero ou mais nodes [3]. Se você criar um cluster com um único node pool, o tipo de SO deve ser Linux [3].
```


## Evidence: deploy (`.agents/tasks/cip-answer-quality/deploy.md`)
- Image `ghcr.io/efcunha/cip-api:aa1277a` (previous tag `19407e0`), built and pushed, single restart of `cip-api` at 23:25:13Z, `/health/ready` 200 after about 1.5 min, 2973 chunks. Backups of `cip.env` and `cip-api.container` taken before the change. `LLM_API_KEY` and `cip.env` contents not touched.
- Remote validation PASS: S3 and Cosmos DB questions answered with citations (2.82 s / 1.94 s), out-of-RAG refusal with 0 sources, stream OK, 3 `query_translated` events, 18 DeepInfra 200 calls, `llm_fallback_extractive`=0, 401=0, CloudPilot healthcheck HEALTHY (ok=31 warn=0 fail=0). Rollback was prepared but not executed.

## Evidence: re-ingest of AKS use-multiple-node-pools (`.agents/tasks/cip-answer-quality/reingest.md`)
| Check | Before | After |
|---|---|---|
| Total rows | 2973 | 2973 |
| Page rows | 18 (ids 3117-3134) | 18 (ids 3135-3152) |
| Chunks with banner (detector or `OS Guard retirement`) | old chunk 3117 had it | 0 |
| Other 2955 rows (md5 snapshot) | - | identical |
- Backup before writing: `/home/deploy/backups/cip/20261126T233218Z/` (dump, page rows, md5s, SHA256SUMS verified). DELETE + INSERT in one transaction. The re-ingest was not rolled back.

## Other documents flagged by the banner detector (reported only, not touched)
Detector over all 2973 chunks: 9 URLs. Most look like real content (dated retirement facts), not page banners. None is an AKS OS Guard banner.
| Chunks | URL |
|---|---|
| 7 | learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models |
| 3 | learn.microsoft.com/en-us/azure/load-balancer/load-balancer-overview |
| 2 | docs.aws.amazon.com/glue/latest/dg/what-is-glue.html |
| 2 | learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview |
| 2 | learn.microsoft.com/en-us/azure/application-gateway/overview |
| 1 | docs.aws.amazon.com/eks/latest/userguide/gpu-ami.html |
| 1 | docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-best-practices.html |
| 1 | docs.aws.amazon.com/redshift/latest/mgmt/welcome.html |
| 1 | learn.microsoft.com/en-us/azure/azure-cache-for-redis/cache-overview |

## Open points for the user
- Re-ingesting other pages that carry the banner pattern.
- Final `retrieval_min_score` (still 0.50).
- Merge of the PR.
