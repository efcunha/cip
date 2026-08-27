# ADR 0006 — Mock Cloud APIs for Dev/CI (without credentials)

- **Status**: Accepted
- **Date**: 2026-08-24

## Context

Cloud tools (AWS Cost Explorer, Azure Advisor, GCP Recommender) require real credentials for integration tests. This causes problems:

1. **Slow CI/CD**: real calls to AWS/Azure/GCP add 2-5s per test
2. **Cost**: each CI run consumes quota (cumulative over the month)
3. **Flakiness**: rate limits, timeouts, API changes break tests
4. **Slow onboarding**: new devs must configure credentials before their first test
5. **Offline**: impossible to work without internet

## Decision

Create a **Mock Cloud API Server** (`scripts/mock_cloud_server.py`) that emulates the real endpoints of the 3 clouds with realistic and deterministic responses.

**Configuration:**
```bash
# .env (dev/CI)
CIP_USE_MOCK_CLOUDS=true
CIP_MOCK_CLOUD_URL=http://127.0.0.1:8888

# .env (prod)
CIP_USE_MOCK_CLOUDS=false
# + real credentials AWS_ACCESS_KEY_ID, etc.
```

**Flow:**
- AWS/Azure/GCP tools detect `CIP_USE_MOCK_CLOUDS=true` in `__init__`
- In mock mode, they make HTTP requests to the mock server instead of boto3/azure-sdk/google-cloud
- Mock returns a JSON structure faithful to the official API
- Deterministic by seed (same request → same response)
- Simulated latency (~200-700ms)

**Emulated endpoints:**
- AWS: `/aws/ce/cost-and-usage`, `/aws/ce/rightsizing`, `/aws/ce/savings-plans`, `/aws/ec2/volumes`, `/aws/ec2/elastic-ips`
- Azure: `/azure/advisor/recommendations`
- GCP: `/gcp/recommender/<recommender_id>`

## Consequences

**Positive:**
- Fast and deterministic CI/CD (~5s vs ~30s with real calls)
- Zero cost (no real calls)
- Onboarding: a new dev runs `cip preflight` without credentials
- Reproducible tests (same seed = same output)
- Work offline (local mock)

**Negative:**
- Mock may diverge from the real API over time
- Does not capture all edge cases (e.g., complex pagination)
- Synthetic responses may give false confidence
- Must keep the mock updated when the real API changes

**Mitigations:**
- Integration tests with real credentials optional (prod smoke test)
- Document the mock's limitations in `mock_cloud_server.py`
- Version the mock with a "last sync with real API" date
- Smoke test in staging with real LLM + cloud (not mock)

## References

- `scripts/mock_cloud_server.py` (350+ lines, 7 endpoints)
- `src/cip/tools/mock_client.py` (HTTP client)
- `tests/test_mock_cloud_cli.py` (27 mock tests)
- `tests/test_tools_mock_integration.py` (18 integration tests)
