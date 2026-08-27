# Análise das 3 recomendações e decisão de arquitetura

Este documento consolida a análise das três propostas recebidas (ChatGPT/CIP, Deep,
MiniMax) e justifica a arquitetura escolhida para a Cloud Intelligence Platform.

## Objetivo do produto

Uma LLM que **não seja genérica** e que **entenda totalmente AWS, GCP e Azure**, atuando
como engenheiro de cloud sênior: analisa ambientes, revisa infraestrutura e sugere
ajustes de arquitetura e custo.

## Comparação

| Critério | ChatGPT (CIP) | Deep | MiniMax |
|---|---|---|---|
| Abordagem central | Multi-agente enterprise (9 especialistas) | Fine-tuning (LoRA/QLoRA) como núcleo | RAG híbrido + tools; fine-tuning depois |
| Nível de detalhe técnico | Conceitual, sem código | Código de treino genérico | Código executável, schema, API, IAM |
| Tratamento de dados voláteis (preço) | Não trata | Alto risco: preço "aprendido" nos pesos | Preço sempre de tool ao vivo |
| Tempo até 1ª versão útil | Indefinido (visão de produto) | 1-2 meses só de treino | MVP em 2-3 semanas |
| Maturidade como plano | Roadmap de features (fase 1-9) | Pipeline de ML sólido, ordem errada | Plano de engenharia com riscos/aceite |

## Por que NÃO começar por fine-tuning (Deep)

- O requisito "entender totalmente as clouds" implica **conhecimento factual volátil**:
  preços, quotas, novos serviços mudam quase toda semana.
- Fine-tuning grava fatos nos pesos → o modelo **desatualiza e alucina com confiança**,
  exigindo retreino contínuo (caro e lento).
- Fine-tuning é a ferramenta certa para **persona, formato e estilo de raciocínio** —
  não para fatos que mudam. Por isso vira a **Fase 6 (opcional)**, não a fase 1.

## Por que NÃO começar pelo multi-agente completo (ChatGPT/CIP)

- É a **visão de longo prazo correta** (Knowledge Graph, Cloud Maturity Score,
  execução controlada de PRs) e serve de norte.
- Mas entregar 9 especialistas + Inspection Engine + Resource Discovery + dashboards
  de uma vez é uma lista de features, não um plano executável em semanas.
- Adotamos a **estrutura de especialistas por domínio** dele, porém introduzida
  incrementalmente.

## Decisão

**Espinha dorsal = MiniMax** (RAG-first, tools read-only, fine-tuning por último)
**+ estrutura de especialistas por domínio = ChatGPT/CIP**
**+ técnica de fine-tuning de persona = Deep** (fase final, opcional).

### Como isso atende "não genérico / entende totalmente"

1. **Retrieval forçado**: nenhuma resposta é gerada sem contexto recuperado da base
   oficial (Well-Architected/CAF/Architecture Framework + docs de serviço).
2. **Metadados por provedor/serviço/categoria**: o retriever filtra por `cloud`,
   `service` e `category`, então a resposta é sempre ancorada no provedor certo.
3. **Whitelist de serviços** no system prompt evita que o modelo invente serviços.
4. **Tools ao vivo** validam hipóteses (custo real, inventário, recomendações nativas)
   antes de responder.
5. **Especialistas** aprofundam o raciocínio por domínio (FinOps, Security, SRE, K8s, TF).

## Consequências

- Resultado útil em semanas, com custo previsível.
- Atualização de conhecimento = re-ingestão mensal (barata), não retreino.
- Caminho de evolução claro até a visão enterprise do CIP.

Ver ADRs em [`adr/`](adr/) para as decisões pontuais (vector DB, LLM base, chunking, etc.).
