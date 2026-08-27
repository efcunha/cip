# Postmortem — GitLab.com Database Outage, 31 January 2017

> Fonte canónica: <https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/>
> Título oficial: "Postmortem of database outage of January 31".
> Cobertura/contexto adicional do mesmo incidente:
> - <https://about.gitlab.com/blog/gitlab-dot-com-database-incident/>

## Resumo executivo

Em 31 de janeiro de 2017, o GitLab.com sofreu uma **indisponibilidade** (outage)
de várias horas causada por uma sequência de erros operacionais durante a
mitigação de um ataque de **spam** e o desgaste (exaustão) de um servidor de
banco de dados. Durante uma operação de manutenção, um operador executou um
comando de remoção de diretório contra o servidor PRIMÁRIO (primary) do
**PostgreSQL** em vez de contra o servidor SECUNDÁRIO (secondary), provocando
perda de dados e forçando a recuperação a partir de backups. O relato público é
um exemplo canónico de **postmortem** blameless, com transparência sobre cada
passo e as correções aplicadas.

## O que aconteceu

- O GitLab.com vinha sofrendo um ataque coordenado de **spam** (criação abusiva
  de projetos/issues) que sobrecarregava o banco de dados e causava
  **replicação** atrasada (replication lag) entre o primary e o secondary.
- A equipa tentou mitigar o problema, mas durante a janela de mitigação o
  processo de limpeza de diretórios (**rm**/remoção de diretórios com a opção
  `--delete`) foi executado contra o diretório do **primary** em vez do
  **secondary**, apagando dados de produção.
- Isso, combinado com o estado já degradado (lag de replicação), resultou na
  perda de dados recentes e numa **indisponibilidade** prolongada enquanto a
  equipa restaurava a partir de backup.

## Dependências e agravantes

- O backup (snapshot) mais recente tinha deficiências de retenção/validação na
  prática, e parte da restauração dependia de dados que não estavam totalmente
  replicados — a recuperação exigiu reconstrução manual e a perda definitiva de
  algumas alterações (issues/comentários de usuários) feitas pouco antes do
  incidente.
- O incidente expôs fragilidades em: **backups** não testados, **replicação**
  sem monitoramento de drift amplo e falta de salvaguardas em comandos
  destrutivos contra o banco primário.

## Lições aprendidas e correções aplicadas

1. **Salvaguardas em comandos destrutivos** — proteger o banco primário de
   comandos `rm`/`--delete` acidentais (defesas contra remoção dirigida ao
   servidor errado).
2. **Backups testáveis e retenção** — garantir que snapshots são íntegros,
   retidos adequadamente e, sobretudo, **testados por restauração** (verify
   restores), em vez de assumir que existem.
3. **Monitoramento de replicação** — alertar sobre replication lag e
   inconsistências primary/secondary antes que se tornem críticos.
4. **Postmortem blameless** — o relato descreve causa, cronologia e ações
   corretivas sem atribuir culpa a indivíduos, tornando-se referência de
   cultura de postmortem (alinhada ao SRE book do Google).

## Resumo em uma frase

Durante a mitigação de um ataque de spam e o desgaste do banco, um comando
destrutivo foi executado contra o servidor PostgreSQL primário em vez do
secundário, causando perda de dados e horas de indisponibilidade no GitLab.com
— e o postmortem blameless resultante tornou-se referência sobre a importância
de backups testáveis, salvaguardas em comandos destrutivos e monitoramento de
replicação.
