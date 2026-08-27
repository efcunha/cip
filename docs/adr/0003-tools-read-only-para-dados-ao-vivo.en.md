# ADR 0003 — Read-only tools for live data

- **Status:** Accepted
- **Date:** 2026-07-23

## Context
Prices and resource inventory change constantly and are specific to each account.
The model cannot "know" this from memory without hallucinating.

## Decision
Every time/account-sensitive datum comes from live **read-only tools**:
- AWS: Cost Explorer, Rightsizing, resource describe.
- Azure: Advisor, Cost Management.
- GCP: Recommender, Asset Inventory.

Global lock `CIP_READONLY=true` blocks any mutating operation.

## Consequences
- (+) Zero inferred pricing; recommendations based on real usage.
- (+) Security: minimal IAM scope, no risk of mutating production.
- (−) Requires temporary credentials and cache (mitigates rate limit).
