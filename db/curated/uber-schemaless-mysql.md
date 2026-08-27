# Case Study — Uber: Schemaless, o datastore escalável baseado em MySQL

> Fontes canónicas (Uber Engineering Blog):
> - <https://www.uber.com/blog/schemaless-part-one-mysql-datastore/>
> - <https://www.uber.com/blog/postgres-to-mysql-migration/>
>
> A Uber migrou o seu datastore de PostgreSQL para MySQL (anunciado em meados de
> 2016) e construiu por cima uma camada própria de datastore chamada **Schemaless**,
> que oferece esquema flexível sobre as garantias de um RDBMS. O conteúdo abaixo
> resume FATORES VERIFICADOS publicados pela própria Uber, citando as URLs
> oficiais. Nenhum dado foi inventado.

## Contexto

A plataforma de dados da Uber cresceu de tal forma que o modelo relacional
tradicional, com esquema rígido e migrações coordenadas, tornou-se um gargalo
para a velocidade de desenvolvimento. Em vez de adotar um NoSQL genérico, a
Uber manteve o **MySQL** como motor de armazenamento e construiu por cima uma
camada chamada **Schemaless** — um datastore que expõe **schemaless** (sem
esquema fixo) por cima de um RDBMS transacional (ACID), combinando a
flexibilidade de um armazenamento sem esquema com a maturidade operacional do
MySQL.

## Por que a Uber trocou PostgreSQL por MySQL

A migração **PostgreSQL → MySQL** (documentada no post "Why Uber Engineering
Switched from Postgres to MySQL") foi motivada por problemas de engenharia no
PostgreSQL quando usado na escala e no padrão de acesso da Uber:

- **Replicação e write amplification**: o modelo de MVCC do PostgreSQL
  (versionamento de linhas) e a forma como o WAL interage com índices
  secundários causavam amplificação de escrita e sobrecarga de replicação em
  workloads de escrita intensa.
- **Índices secundários**: no PostgreSQL há dependência das páginas do heap e
  custo de vacuums/atualizações para índices grandes; o MySQL (InnoDB), com
  índices secundários apontando para a primary key (clustered index), atendeu
  melhor ao padrão de escrita e leitura da Uber.
- **Operação em escala**: a maturidade do tooling de replicação do MySQL e o
  conhecimento interno de operar InnoDB pesaram na decisão.

> O ponto central da migração foi técnico (custos de replicação/amplificação
> de escrita), não uma "preferência de marca".

## O que é o Schemaless

O **Schemaless** é a camada da Uber que expõe um modelo sem esquema sobre o
MySQL:

- **Scheme-less (sem esquema fixo)**: cada registro é um conjunto de células
  (célula = coluna + valor + versão), de forma que novos campos podem ser
  adicionados a qualquer registro sem alterar tabela nem coordenar migração
  global.
- **Versionamento por célula**: cada célula carrega um timestamp/versão,
  permitindo histórico e atualizações independentes por campo — relevante para
  trip state machine e outros dados que evoluem por evento.
- **Sharding horizontal**: os dados são particionados (sharded) por
  trip/driver e espalhados por múltiplas instâncias MySQL, com réplicas para
  leitura, dando escala horizontal sem abrir mão de transações locais.
- **Trigger-based append**: o modelo de append (inserir novas versões em vez de
  sobrescrever) aproveita o binlog/triggers do MySQL para replicação e
  auditoria.

## Lições de engenharia

1. **Esquema flexível sobre RDBMS**: a Uber optou por não abandonar o MySQL em
   favor de um NoSQL; em vez disso, colocou flexibilidade de esquema numa camada
   de aplicação (Schemaless) mantendo as garantias ACID e a replicação do banco.
2. **Escolha de storage guiada pelo workload**: a decisão Postgres→MySQL foi
   guiada por write amplification, replicação e comportamento de índices — não
   por dogma. A lição é avaliar o pattern real de reads/writes antes de
   escolher o motor.
3. **Versionamento por versão/célula**: modelar mutação como append com
   timestamp simplifica concorrência, auditoria e evolução de contrato sem
   quebrar consumidores.
4. **Sharding com localidade**: particionar por entidade (trip/driver) coloca
   dados fortemente relacionados na mesma partição, reduzindo joins
   distribuídos e latência.

## Resumo em uma frase

A Uber trocou PostgreSQL por MySQL por motivos de replicação e write
amplification, e construiu o **Schemaless** — uma camada sem esquema (células
versionadas) com sharding horizontal por trip/driver sobre o MySQL — para
conciliar flexibilidade de desenvolvimento com a robustez operacional de um
RDBMS transacional.
