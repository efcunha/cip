# Recount on-topic (sem novas chamadas de API)

Fonte: eval/reports/deepinfra-gemma3-post-ingest-translation-{on,off}-raw.json, must_mention corrigidos.

| Modo | in_on_topic antes | in_on_topic depois |
|---|---|---|
| traducao ON | 79,2% (38/48) | 95,8% (46/48) |
| traducao OFF | 68,8% (33/48) | 83,3% (40/48) |

Correcoes: in-13 (5 niveis), in-15 (pdb + definicao), in-06 (standby|espera), in-11 (multifator|autentica).
Restam falhas reais: in-10 (2 de 3 runs sem system/user pools) e, em OFF, declines in-01/in-04.
