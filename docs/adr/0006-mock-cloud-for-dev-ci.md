# ADR 0006 — Mock Cloud APIs para Dev/CI (sem credenciais)

- **Status**: Aceito
- **Data**: 2026-08-24

## Contexto

Tools cloud (AWS Cost Explorer, Azure Advisor, GCP Recommender) requerem credenciais reais para testes integrados. Isso causa problemas:

1. **CI/CD lento**: chamadas reais à AWS/Azure/GCP adicionam 2-5s por teste
2. **Custo**: cada execução de CI consome quota (cumulativo no mês)
3. **Flakiness**: rate limits, timeouts, mudanças de API quebram testes
4. **Onboarding lento**: novos devs precisam configurar credenciais antes de primeiro teste
5. **Offline**: impossível trabalhar sem internet

## Decisão

Criar **Mock Cloud API Server** (`scripts/mock_cloud_server.py`) que emula os endpoints reais das 3 clouds com respostas realistas e determinísticas.

**Configuração:**
```bash
# .env (dev/CI)
CIP_USE_MOCK_CLOUDS=true
CIP_MOCK_CLOUD_URL=http://127.0.0.1:8888

# .env (prod)
CIP_USE_MOCK_CLOUDS=false
# + credenciais reais AWS_ACCESS_KEY_ID, etc.
```

**Fluxo:**
- Tools AWS/Azure/GCP detectam `CIP_USE_MOCK_CLOUDS=true` no `__init__`
- Em modo mock, fazem HTTP para o mock server em vez de boto3/azure-sdk/google-cloud
- Mock retorna estrutura JSON fiel à API oficial
- Determinístico por seed (mesmo request → mesma response)
- Latência simulada (~200-700ms)

**Endpoints emulados:**
- AWS: `/aws/ce/cost-and-usage`, `/aws/ce/rightsizing`, `/aws/ce/savings-plans`, `/aws/ec2/volumes`, `/aws/ec2/elastic-ips`
- Azure: `/azure/advisor/recommendations`
- GCP: `/gcp/recommender/<recommender_id>`

## Consequências

**Positivas:**
- CI/CD rápido e determinístico (~5s vs ~30s com chamadas reais)
- Sem custo (zero chamadas reais)
- Onboarding: novo dev roda `cip preflight` sem credenciais
- Testes reproduzíveis (mesmo seed = mesmo output)
- Trabalhar offline (mock local)

**Negativas:**
- Mock pode divergir da API real ao longo do tempo
- Não captura todos os edge cases (ex: paginação complexa)
- Respostas sintéticas podem dar falsa confiança
- Precisa manter mock atualizado quando API real muda

**Mitigações:**
- Testes integrados com credenciais reais opcionais (smoke test prod)
- Documentar limitações do mock no `mock_cloud_server.py`
- Versionar mock com data de "última sync com API real"
- Smoke test em staging com LLM + cloud reais (não mock)

## Referências

- `scripts/mock_cloud_server.py` (350+ linhas, 7 endpoints)
- `src/cip/tools/mock_client.py` (cliente HTTP)
- `tests/test_mock_cloud_cli.py` (27 testes do mock)
- `tests/test_tools_mock_integration.py` (18 testes de integração)
