# ADR 0003 — Tools read-only para dados ao vivo

- **Status:** Aceito
- **Data:** 2026-07-23

## Contexto
Preços e inventário de recursos mudam constantemente e são específicos de cada conta.
O modelo não pode "saber" isso de memória sem alucinar.

## Decisão
Todo dado sensível a tempo/conta vem de **tools read-only** ao vivo:
- AWS: Cost Explorer, Rightsizing, describe de recursos.
- Azure: Advisor, Cost Management.
- GCP: Recommender, Asset Inventory.

Trava global `CIP_READONLY=true` bloqueia qualquer operação mutante.

## Consequências
- (+) Zero preço inferido; recomendações baseadas em uso real.
- (+) Segurança: escopo IAM mínimo, sem risco de mutar produção.
- (−) Requer credenciais temporárias e cache (mitiga rate limit).
