# Reingestão das 9 páginas com banner + LLM_CONTEXT_TOP_K 4 -> 5: medição final (DeepInfra gemma-3-27b-it)

- Data: 2026-11-27 (UTC). Branch `feat/cip-banner-reingest-context`, base `main` (0a93ffc).
- Medição: `eval/ollama_compare.py`, mesmo modelo (`google/gemma-3-27b-it` via DeepInfra), mesmas perguntas, 3 runs por pergunta, tradução de consulta ON, `max_tokens=1024`, `temperature=0.1`, `retrieval_min_score=0.50` (não alterado), embedding `BAAI/bge-large-en-v1.5` (não alterado). Geração com `--ctx-top-k 5 --chunk-chars 1200` (configuração final da VPS).
- Comandos (python de `venv/`, chave lida da variável de usuário do Windows só no processo, nunca gravada): `retrieval`; `translate --backend openai`; `generation --backend openai --models google/gemma-3-27b-it --translation on --runs 3 --ctx-top-k 5 --chunk-chars 1200`; `report`.
- Arquivos brutos: `deepinfra-gemma3-reingest-context-retrieval-raw.json`, `-translation-retrieval-raw.json`, `-generation-raw.json`; tabelas completas em `deepinfra-gemma3-reingest-context-eval.md`.
- Notas das partes A e B (sem segredos) ficam em `.agents/tasks/cip-banner-reingest-context/` (não versionadas).

## Veredito

- Guardrails mantidos: falsa recusa in-RAG 0%, out-of-RAG recusado 100%, 0 vazamentos off-topic (0/34 e 0/24 nas ambíguas), citação válida 100%. Nenhum rollback necessário.
- in-10 resolvido: system+user pools em 3/3 runs na medição final (baseline 1/3), sem aviso de aposentadoria. Em produção, 10/10 (ver Parte B).
- On-topic in-RAG caiu de 96% (46/48) para 92% (44/48). Não é guardrail, mas é um número pior: ver "Pontos de atenção".
- Latência desta medição ficou pior que o baseline (ver tabela). A medição da Parte B com o mesmo k=5 deu total mediana 3,20 s, então a diferença vem de variação do DeepInfra (tok/s 37 contra 51), não do k. Mesmo assim, o número desta rodada é o que está registrado.

## Antes / depois (tradução ON, 3 runs)

| Métrica | Baseline (answer-quality, k=4, antes da reingestão) | Final (k=5, 9 páginas reingeridas) |
|---|---|---|
| Falsa recusa in-RAG | 0% | 0% |
| On-topic in-RAG | 96% (46/48) | 92% (44/48) |
| Out-of-RAG recusado | 100% | 100% |
| Vazamentos off-topic (out-of-RAG) | 0/34 | 0/34 |
| Vazamentos nas ambíguas | 0/24 | 0/24 |
| Citação válida | 100% | 100% |
| Fallback extrativo (in-RAG) | 0% | 0% |
| TTFT mediana (respostas) | 0,65 s | 0,75 s |
| Total mediana / p95 (respostas) | 3,09 s / 7,60 s | 4,89 s / 10,03 s |
| in-10 com system+user pools | 1/3 | 3/3 (sem aviso de aposentadoria) |
| Recall@k retrieval (pt e5 / en e5) | 94% / 100% | 94% / 100% |

## Pontos de atenção (on-topic 96% -> 92%)

Perguntas que falharam o critério `must_mention` na medição final: in-07 em 3/3 runs e in-16 em 1/3 runs.
- in-07 (DynamoDB provisionada vs sob demanda): o modelo escreve "provisionado" (masculino), e o critério espera `provisioned|provisionada`. A resposta é correta e cita a fonte; é artefato do critério, também visto na Parte B (in-07 em k=5: 13/20 contra 20/20 em k=4). Os critérios do eval não foram alterados.
- in-16 (state file do Terraform): 1/3 runs sem mencionar `backend`; ruído do LLM (na medição da Parte B com k=5, 2/3 runs).
- Efeito líquido do k=5 no on-topic: in-10 ganhou 2 runs e in-07 perdeu 3 (artefato). O ganho real em in-10 é maior do que o número agregado sugere; o on-topic agregado piorou 4 pontos por causa do critério de flexão.

## Parte A: reingestão das 9 páginas (backup antes de escrever)

Imagem `ghcr.io/efcunha/cip-api:aa1277a` (a de produção, com o banner stripping do PR #4), one-shot `podman run --rm` na VPS, mesmo embedding (bge-large-en-v1.5, 1024 dims). Detector `find_notice_banners` em 271 URLs / 2973 chunks: 9 URLs com banner antes, 0 depois.

Backup: `/home/deploy/backups/cip/20261127T004625Z/` (`pg_dump -Fc` 17,4 MB, `pg_restore -l` OK; cópia das 133 linhas das 9 páginas; md5 de todas as 2973 linhas; `SHA256SUMS` verificado).

Método: por página, DELETE da URL + INSERT dos chunks novos na mesma transação, com asserts (linhas apagadas = linhas antigas, contagem final exata, dims = 1024); descarta chunks cujo `content_hash` já existe em outra URL (igual ao `ingest_entry`); aborta a página se a perda de texto passar de 25%. Uma página por vez, comparando o md5 de todas as outras linhas antes/depois.

| URL (abreviada) | Chunks antes->depois | Chars antes->depois | Perda | Banner depois | Outras linhas |
|---|---|---|---|---|---|
| azure openai/concepts/models | 63->63 | 68491->69568 | -1,6% | 0 | idênticas |
| azure load-balancer-overview | 8->8 | 7082->6607 | 6,7% | 0 | idênticas |
| aws glue what-is-glue | 7->7 | 6952->6888 | 0,9% | 0 | idênticas |
| azure virtual-machines/sizes/overview | 26->25 | 44476->43969 | 1,1% | 0 | idênticas |
| azure application-gateway/overview | 6->4 | 5920->5071 | 14,3% | 0 | idênticas |
| aws eks gpu-ami | 4->4 | 4134->4097 | 0,9% | 0 | idênticas |
| aws ecs-best-practices | 2->2 | 3350->3325 | 0,7% | 0 | idênticas |
| aws redshift welcome | 4->3 | 2742->2563 | 6,5% | 0 | idênticas |
| azure cache-for-redis/cache-overview | 13->13 | 12620->12581 | 0,3% | 0 | idênticas |

9 aplicadas, 0 puladas, 0 rollbacks. Total de linhas 2973 -> 2969 (chunks a menos vêm de duplicatas de outra URL e do aviso de fim de suporte de Python UDF no Redshift). Dims só 1024. Menções a `retire|deprecat|end of support|...` caíram em todas as páginas (por exemplo models 30->21, glue 2->0, app-gateway 8->3); o texto procedural permanece. `cip-api` não foi reiniciado nesta parte.

## Parte B: tamanho do contexto (k e chunk), suíte completa 3 runs, tradução ON

Estado: pós-Parte A, DeepInfra gemma-3-27b-it, mesmas perguntas; retrieval e tradução reaproveitados, só a geração varia. Chunks de 1600 e 2000 chars geram prompts idênticos (os chunks têm no máximo ~1600 chars), então a diferença entre eles é ruído.

| k @ chunk | in-10 completo (runs) | On-topic | Falsa recusa | Out-of-RAG recusado | Vazamentos | Citação | Total med / p95 (s) | Prompt tokens med / max |
|---|---|---|---|---|---|---|---|---|
| 4 @ 1200 (atual) | 1/3 | 96% | 0% | 100% | 0 | 100% | 2,30 / 9,79 | 1170 / 1484 |
| 4 @ 1600 | 2/3 | 94% | 0% | 100% | 0 | 100% | 1,21 / 8,62 | 1255 / 1723 |
| 4 @ 2000 | 1/3 | 96% | 0% | 100% | 0 | 100% | 1,24 / 6,30 | 1255 / 1723 |
| **5 @ 1200** | **3/3** | 96% | 0% | 100% | 0 | 100% | 1,08 / 4,36 | 1395 / 1732 |
| 6 @ 1200 | 3/3 | 92% | 0% | 100% | 0 | 100% | 2,15 / 12,95 | 1555 / 1942 |
| 6 @ 1600 | 2/3 | 88% | 0% | 100% | 0 | 100% | 1,99 / 7,97 | 1724 / 2234 |
| 8 @ 1200 | 3/3 | 88% | 0% | 100% | 0 | 100% | 2,61 / 16,24 | 2011 / 2506 |
| 8 @ 2000 | 3/3 | 88% | 0% | 100% | 0 | 100% | 1,13 / 4,57 | 2204 / 2881 |

Amostras extras de in-10 (8 a 20 runs): k=4 17/31 (55%); k=5 29/31 (94%); k>=6 8/8, mas in-02 (pilares do GCP) cai para 0/8 em k=6 e k=8 (resposta vira trecho em inglês ou troca os nomes dos pilares).

**Decisão: `LLM_CONTEXT_TOP_K=5`, `LLM_CONTEXT_CHUNK_CHARS=1200` inalterado.** É o menor valor que resolve in-10 de forma confiável, sem quebrar in-02 e sem regressão de guardrails. Prompt cresce ~19% na mediana (1395 contra 1170 tokens); pior caso 1732 + 1024 de saída = 2756, abaixo do contexto de 8192 da VPS. k>=6 e chunks maiores não trazem ganho.

Aplicação na VPS: só `LLM_CONTEXT_TOP_K` mudou em `cip.env` (4 -> 5); `LLM_API_KEY` e `retrieval_min_score` não foram tocados; backup `cip.env.bak-pre-20261127T023914Z`; um restart de `cip-api`. Smoke PT-BR: S3 e Cosmos DB respondidos com citação, "capital da França" recusado (sem fontes), `/ask/stream` OK, tradução ativa, 0 fallback. in-10 em produção: 10/10 com system+user pools (uma amostra anterior de 4 teve 2/4, variação do LLM). O default do repo passou de 4 para 5 (`src/cip/config.py`, `.env.example`, docs, CHANGELOG, teste); `ops/ollama/cip.env.ollama.example` fica em 4 (perfil Ollama pequeno, contexto 4096). A imagem em produção continua `aa1277a`; o novo default só entra na próxima imagem, até lá o valor vem do `cip.env`.

## Saúde da VPS na configuração final (2026-11-27 02:52Z)

- `sudo stackctl healthcheck`: ok=31 warn=0 fail=0 skip=2, resultado HEALTHY.
- `cip-api.service`: active (running); `LLM_CONTEXT_TOP_K=5` presente em `cip.env`.
- `https://api.cloudpilot.app.br/health`: 200.
- Nenhum serviço ou banco do CloudPilot foi tocado; nenhum rollback foi necessário.

## Rollback (se a decisão for reverter)

- Parte B: restaurar `cip.env.bak-pre-20261127T023914Z` sobre `cip.env` e `sudo stackctl restart cip-api`.
- Parte A: restaurar as linhas das 9 páginas a partir de `/home/deploy/backups/cip/20261127T004625Z/` (`pages_rows.copy.tsv` ou `pg_restore` do dump).
