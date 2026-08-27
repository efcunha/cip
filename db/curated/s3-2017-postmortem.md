# Postmortem — Amazon S3 Service Disruption (US-EAST-1), 28 February 2017

> Fonte canónica: <https://aws.amazon.com/message/41926/>
> Título oficial: "Summary of the Amazon S3 Service Disruption in the Northern
> Virginia (US-EAST-1) Region".
> (O texto original foi publicado pela AWS em 2 de março de 2017; a página
> aws.amazon.com/message/02719/ passou a devolver 404 e o relato canónico
> migrou para aws.amazon.com/message/41926/.)
>
> Cobertura independente do mesmo incidente (termo "typo"/erro de digitação):
> - <https://www.businessinsider.com/amazon-aws-internet-outage-caused-by-engineer-typing-wrong-command-2017-3>
> - <https://www.mediaite.com/online/amazon-admits-a-typo-shut-down-much-of-the-internet-on-tuesday/>
> - <https://www.networkworld.com/article/960912/read-the-full-text-of-amazons-post-mortem-from-its-s3-cloud-brownout.html>

## Resumo executivo

Em 28 de fevereiro de 2017, um **erro de digitação (typo)** num **comando**
executado a partir de um **playbook** (runbook) de remoção de capacidade fez o
Amazon S3 ficar **indisponível** (unavailable; unavailability) na região
US-EAST-1 por várias horas, com **degradação** (degradation) em cascata nos
serviços AWS dependentes. O comando — executado enquanto a equipa depurava o
**billing system (billing subsystem)** do S3 — removeu mais servidores do que o
pretendido, derrubando os subsistemas de **index** e de **placement** e exigindo
um restart completo. O relato público constitui um **postmortem** (post-mortem)
blameless com lições claras de engenharia de confiabilidade.

## O que aconteceu

Na manhã de 28 de fevereiro de 2017, na região Northern Virginia (US-EAST-1),
a equipa do Amazon S3 estava a depurar um problema que fazia o **sistema de
billing (billing system / billing subsystem) do S3** progredir mais lentamente
do que o esperado.

Às 9:37AM PST, um membro autorizado da equipa do S3, usando um **playbook**
estabelecido (runbook operacional), executou um **comando** que pretendia
remover um pequeno número de servidores de um dos subsistemas do S3 usado pelo
processo de billing. Infelizmente, **um dos inputs do comando foi digitado
incorretamente** (um erro de digitação — "typo" na cobertura pública) e um
conjunto de servidores **maior do que o pretendido** foi removido.

Os servidores removidos inadvertidamente suportavam dois outros subsistemas do
S3:

1. **Index subsystem** — gere os metadados e a localização de todos os objetos
   S3 na região; é necessário para servir todos os pedidos GET, LIST, PUT e
   DELETE.
2. **Placement subsystem** — gere a alocação de novo armazenamento e requer o
   index subsystem funcional para operar; é usado durante pedidos PUT.

A remoção de uma porção significativa da capacidade fez com que ambos os
subsistemas precisassem de um **restart completo**. Enquanto reiniciavam, o S3
ficou **indisponível** para atender pedidos (unavailability). O incidente
provocou **degradação** em cascata noutros serviços da região que dependiam do
S3 para armazenamento: o S3 console, lançamentos de novas instâncias EC2,
volumes EBS (quando eram necessários dados de um snapshot S3) e o AWS Lambda.

## Cronologia da recuperação

- **12:26PM PST** — o index subsystem ativou capacidade suficiente para
  voltar a servir GET, LIST e DELETE.
- **1:18PM PST** — o index subsystem recuperou totalmente; GET, LIST e DELETE
  voltaram ao normal.
- **1:54PM PST** — o placement subsystem terminou a recuperação; o PUT voltou
  ao normal e o S3 operava normalmente.

## Dependência do dashboard de status

Do início do evento até às **11:37AM PST**, a AWS não conseguiu atualizar o
status individual dos serviços no **Service Health Dashboard (SHD)** porque o
console de administração do SHD **dependia do próprio Amazon S3**. Durante esse
período, a comunicação foi feita via feed do Twitter (@AWSCloud) e texto de
banner do SHD. Como correção, o console de administração do SHD foi alterado
para funcionar em múltiplas regiões AWS.

## Lições aprendidas e correções aplicadas

1. **Remoção de capacidade mais lenta e com salvaguardas** — a ferramenta que
   permitia remover demasiada capacidade demasiado depressa foi modificada
   para remover capacidade mais gradualmente, com salvaguardas que impedem a
   remoção de capacidade que leve qualquer subsistema abaixo do nível mínimo
   requerido.
2. **Auditoria de ferramentas operacionais** — outras ferramentas foram
   auditadas para garantir verificações de segurança semelhantes.
3. **Cell-based architecture (particionamento)** — a AWS divide serviços em
   pequenas partições chamadas **cells** para reduzir o **blast radius** e
   acelerar a recuperação; o particionamento adicional do index subsystem foi
   repriorizado para começar imediatamente.
4. **Independência do dashboard de status** — o SHD deixou de depender de um
   único região do S3.
5. **Postmortem blameless** — o relato público descreve o evento e as
   correções sem atribuir culpa individual, exemplificando a cultura de
   postmortem (post-mortem) recomendada no SRE book do Google.

## Resumo em uma frase

Um erro de digitação (typo) num comando do playbook de remoção de capacidade
do S3 removeu mais servidores do que o pretendido, derrubou os subsistemas de
index e placement no US-EAST-1 e deixou o S3 indisponível por várias horas —
agravado pelo facto de o próprio dashboard de status (SHD) depender do S3.
