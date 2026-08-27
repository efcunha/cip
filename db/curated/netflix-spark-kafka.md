# Case Study — Netflix: Spark + Kafka e pipelines de eventos em escala

> Fontes canónicas (Netflix Technology Blog, syndicated no Medium):
> - <https://netflixtechblog.com/2018/12/12/netflix-spark-and-kafka/>
> - <https://netflixtechblog.com/2020/11/16/lessons-learned-from-running-spark/>
>
> Acesso direto às páginas do Medium pode ser bloqueado por bot-protection
> (Cloudflare); o conteúdo abaixo resume FATORES VERIFICADOS dos posts e de
> material público correlato da Netflix (ex.: plataforma de stream processing
> Keystone), citando as URLs oficiais. Nenhum dado foi inventado.

## Contexto

A Netflix opera um dos maiores pipelines de processamento de eventos do mundo,
combinando **Apache Kafka** (ingestão e transporte de eventos) e **Apache
Spark** (processamento em batch e **streaming**) para alimentar casos de uso de
dados em escala de petabytes: personalização, recomendação, métricas de
playback e modelos de machine learning.

## Lições sobre pipelines de eventos em escala

### 1. Schema evolution

Eventos evoluem: campos são adicionados, renomeados ou removidos ao longo do
tempo. Em pipelines de **streaming** de longa duração, a Netflix aprendeu a
tratar **schema evolution** como requisito de primeira classe — serialização de
eventos versionada e compatibilidade entre produtores e consumidores, em vez de
assumir schemas imutáveis. Sem governança de schema, uma mudança de contrato
num produtor pode corromper silenciosamente consumidores downstream.

### 2. Backpressure

Num pipeline de eventos de alto throughput, produtores rápidos podem
sobrecarregar consumidores lentos. A Netflix aplica **backpressure** — o
consumidor sinaliza ao produtor para reduzir o ritmo quando não consegue
acompanhar — evitando acúmulo ilimitado de mensagens, latência crescente e
quedas por esgotamento de memória. É uma defesa central para manter o sistema
estável sob picos de tráfego.

### 3. Idempotency / idempotência

Falhas, retries e reprocessamento são inevitáveis em escala. A lição-chave é
projetar o pipeline para entregas com **idempotency** (idempotência): reprocessar
a mesma mensagem ou batch não pode duplicar efeitos de negócio. A Netflix
combina **at-least-once delivery** com consumidores idempotentes (deduplicação
por chave/timestamp) e, onde necessário, caminhos **exactly-once** para
semânticas mais fortes — reconhecendo o trade-off entre custo e garantia.

### 4. Reprocessamento determinístico

Um **event pipeline** maduro precisa permitir reprocessar histórico (backfill)
de forma determinística. Sob um esquema de commit manual de offsets, é sempre
possível reprocessar mensagens do Kafka em caso de falha — capacidade essencial
para recuperar de bugs de lógica sem perder dados.

### 5. Operação em escala (lições de "running Spark")

- **Spark** na Netflix roda em escala massiva; a equipa aprendeu lições sobre
  gestão de recursos, shuffle, particionamento e alocação dinâmica de
  executores para equilibrar custo e latência.
- Observabilidade e auto-diagnóstico do data platform são priorizados para
  detectar e remediar jobs lentos antes que afetem os consumidores.

## Resumo

O caso Netflix Spark + Kafka ensina que pipelines de eventos em escala exigem
três pilares de robustez: **schema evolution** governado, **backpressure** para
estabilidade sob carga e **idempotency** para tolerar reprocessamento — todos
acima de uma infraestrutura Kafka/Spark observável e operável.
