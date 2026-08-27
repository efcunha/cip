# Relatório de Avaliação CIP

**Data**: 2026-08-24T18:12:22.739841+00:00
**Casos avaliados**: 95
**Pass rate**: 3/95 (3.2%)
**Gate de produção**: ❌ FALHOU

## Scores médios por critério (target ≥ 4.0)

- ❌ **accuracy**: 3.30
- ✅ **grounding**: 5.00
- ✅ **citation**: 5.00
- ❌ **format**: 1.00
- ✅ **zero_price**: 5.00

## Custo e compliance
- **Custo mediano por query**: $0.0000 (target < $0.05)
- **Violações zero-price**: 0 (0.0% dos casos)

## Falhas do gate

- ❌ accuracy: avg 3.30 < target 4.0
- ❌ format: avg 1.00 < target 4.0
- ❌ 85 casos com accuracy < 3.0: know-001, know-002, know-003, know-004, know-005

## Por categoria

| Categoria | N | Avg Score | Pass Rate |
|---|---|---|---|
| iac_review | 10 | 3.86 | 30% |

## Por cloud

| Cloud | N | Avg Score | Pass Rate |
|---|---|---|---|
| aws | 33 | 3.85 | 3% |
| azure | 28 | 3.87 | 4% |
| gcp | 28 | 3.80 | 0% |
| multi | 1 | 4.00 | 100% |

## Casos que falharam (92)

- **know-001** (conhecimento/aws): avg=0.00 accuracy=0.00 grounding=0.00
- **know-002** (conhecimento/aws): avg=0.00 accuracy=0.00 grounding=0.00
- **know-003** (conhecimento/gcp): avg=0.00 accuracy=0.00 grounding=0.00
- **know-004** (conhecimento/azure): avg=0.00 accuracy=0.00 grounding=0.00
- **know-005** (conhecimento/aws): avg=0.00 accuracy=0.00 grounding=0.00
- **know-006** (conhecimento/gcp): avg=0.00 accuracy=0.00 grounding=0.00
- **know-007** (conhecimento/azure): avg=0.00 accuracy=0.00 grounding=0.00
- **know-008** (conhecimento/aws): avg=0.00 accuracy=0.00 grounding=0.00
- **know-009** (conhecimento/gcp): avg=0.00 accuracy=0.00 grounding=0.00
- **know-010** (conhecimento/azure): avg=0.00 accuracy=0.00 grounding=0.00
- ... e mais 82
