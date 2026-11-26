# Calibracao de retrieval_min_score e endurecimento do eval

Dados: `eval/reports/ollama-retrieval-raw.json` (PT e EN, sem traducao), `deepinfra-gemma3-translation-retrieval-raw.json` (PT traduzido, "ON") e `deepinfra-gemma3-query-translation-{on,off}-raw.json`. Embedding `BAAI/bge-large-en-v1.5` (1024), prefixo `query: `, top_k=8. Nenhuma chamada nova (DeepInfra, banco ou SSH de dados).

## 1. Eval endurecido

Problema: `outcome == "valid"` so prova citacao valida e conteudo. O in-10 OFF respondeu sobre a aposentadoria do Azure Linux 2.0 com citacao valida, e `must_mention` (`node pool`, `aks|kubernetes`) batia por acaso (AKS e "pools de nos" aparecem no texto).

Mudancas (ids estaveis):
- `eval/ollama_questions.json`: in-10 passa a exigir `node pool|pool de nos|pools de nos` **e** `system|sistema|user pool|pool de usuario|scale set|vmss` (definicao de node pool, ausente na resposta fora de assunto). in-02 trocou `reliability` por `operational excellence` e in-11 trocou `entra` por `policy|policies|politica`: os termos antigos nao apareciam em respostas corretas (o contexto recuperado nao os continha), o que contaria resposta no assunto como falha.
- `eval/ollama_compare.py`: nova metrica `in_on_topic` = `valid` **e** todos os `must_mention` presentes, recalculada da resposta guardada (`is_on_topic`), mais coluna "In-RAG on-topic" no relatorio. Testes em `tests/test_ollama_compare_eval.py`.

Recontagem com os raw jsons existentes (gemma-3-27b-it, 3 runs, 16 perguntas in-RAG = 48 respostas; out-of-RAG e ambiguas nao mudam):

| Traducao | In-RAG valid (antes) | In-RAG on-topic (novo) | Respostas valid fora de assunto/parciais | Falsa recusa | Out-of-RAG recusada |
|---|---|---|---|---|---|
| ON | 39/48 = 81% | 38/48 = 79% | 1 (in-16 run 1: resposta sobre state sem citar backend) | 9/48 = 19% | 100% |
| OFF | 36/48 = 75% | 31/48 = 65% | 5 (in-10 x3 fora de assunto; in-02 run 3 e in-07 run 2 parciais) | 12/48 = 25% | 100% |

Efeito principal: o OFF cai de 75% para 65%; os 3 acertos do in-10 OFF eram resposta fora de assunto. Diferenca ON vs OFF real: 79% vs 65% (antes 81% vs 75%). As 3 falsas recusas in-RAG restantes (in-13, in-15, in-10 ON) seguem sendo content gap (ver `false-refusal-root-cause.md`).

## 2. Distribuicao dos scores (top-1, cosine)

| Modo | Grupo | n | min | mediana | max |
|---|---|---|---|---|---|
| ON (PT traduzido) | in-RAG | 16 | 0.700 | 0.791 | 0.822 |
| ON | out-of-RAG | 12 | 0.491 | 0.598 | 0.697 |
| ON | ambiguas | 8 | 0.628 | 0.678 | 0.735 |
| OFF (PT cru) | in-RAG | 16 | 0.607 | 0.722 | 0.748 |
| OFF | out-of-RAG | 12 | 0.562 | 0.642 | 0.668 |
| OFF | ambiguas | 8 | 0.628 | 0.663 | 0.698 |
| EN | in-RAG / out / amb | 16/12/8 | 0.700 / 0.487 / 0.628 | 0.790 / 0.598 / 0.676 | 0.822 / 0.697 / 0.735 |

Valores extremos ON: menor in-RAG = in-15 (0.6996, content gap); maior out-of-RAG = out-08 (0.6966). Separacao ON: 0.0030. OFF: sobreposicao (in-04 0.607 e in-08 0.659 abaixo do maior out-of-RAG 0.668).

Perguntas gateadas (top-1 < limiar), `in / out / ambiguas`:

| Limiar | ON | OFF |
|---|---|---|
| 0.50 (atual) | 0 / 1 / 0 | 0 / 0 / 0 |
| 0.55 | 0 / 3 / 0 | 0 / 0 / 0 |
| 0.60 | 0 / 6 / 0 | 0 / 3 / 0 |
| 0.65 | 0 / 9 / 3 | 1 / 8 / 2 |
| 0.68 | 0 / 9 / 4 | 3 / 12 / 7 |
| 0.70 | 1 / 12 / 6 | 4 / 12 / 8 |
| 0.75 | 2 / 12 / 8 | 16 / 12 / 8 |

Regra de margem (top-1 menos top-4): in-RAG 0.004 a 0.075 (mediana 0.039); out-of-RAG 0.001 a 0.024 (mediana 0.009). Sobrepoe (in-RAG min 0.004 < out max 0.024): nao discrimina sozinha, e dependeria do top-4 que muda com o corpus.

## 3. Recomendacao

**Manter o default 0.50.** Nao ha mudanca em `config.py` nem em `.env.example`; nao houve novo eval DeepInfra.

Motivos:
- Hoje a recusa out-of-RAG ja e 100% (ON e OFF) pelo modelo/prompt; o gate de score so adiciona defesa em profundidade, nao corrige um erro medido.
- Em ON um limiar de 0.65 gateia 9/12 out-of-RAG sem nova falsa recusa; em OFF a margem ate o in-RAG correto mais proximo (in-08 0.659) e de 0.009. Em 0.70 o in-15 (0.6996) ja cai por 0.0004 e, em OFF, in-10 (0.693) passaria de resposta a recusa. A amostra (16 / 12 / 8) e pequena demais para fixar o corte; qualquer valor acima de 0.60 seria ajuste fino ao conjunto.
- Ambiguas (0.628 a 0.735) ficam no meio: limiares >= 0.65 recusam parte delas, mudando comportamento visivel sem evidencia de que isso seja desejado.
- O corpus vai crescer com as 3 paginas ausentes: os top-1 in-13, in-15 e in-10 vao subir e os scores out-of-RAG podem mudar (mais chunks genericos de Kubernetes/Azure).

Proposta para decisao do usuario (sem aplicar): candidato 0.60 (ON gateia 6/12, OFF 3/12 out-of-RAG, 0 in-RAG nos dois modos, margem ~0.007 ate in-04 OFF 0.607; ver nota) ou 0.65 (so se o uso for sempre com traducao ON). Reavaliar apos a ingestao com: `ollama_compare.py retrieval` + `translate` e a tabela acima, e so entao mudar o default e re-rodar o eval DeepInfra (3 runs, ON) com antes/depois.

Nota 0.60: em OFF, in-04 (0.607) fica a 0.007 do corte, ja recusado pelo modelo no OFF; o risco e em perguntas PT sem traducao quando a traducao falha ou expira (5 s).

## 4. Config remota (somente leitura)

`/home/deploy/.config/cloudpilot/env/cip.env` define explicitamente `RETRIEVAL_MIN_SCORE=0.50` e `RETRIEVAL_TOP_K=8` (iguais ao default), `EMBED_MODEL=BAAI/bge-large-en-v1.5`, `EMBED_DIM=1024`, `LLM_PROVIDER=extractive`. Nao define `LLM_QUERY_TRANSLATION*`/`QUERY_TRANSLATION_*` (usa o default do codigo, `enabled=True`), nem `LLM_API_KEY`. Valores de segredo nao foram lidos. Se o limiar mudar, o `cip.env` remoto precisa ser alterado tambem, porque ele sobrescreve o default. O quadlet `cip-api.container` carrega so esse `EnvironmentFile`, sem `Environment=` extra.
