# Analysis of the 3 recommendations and architecture decision

This document consolidates the analysis of the three proposals received (ChatGPT/CIP, Deep,
MiniMax) and justifies the architecture chosen for the Cloud Intelligence Platform.

## Product objective

An LLM that is **not generic** and that **fully understands AWS, GCP and Azure**, acting
as a senior cloud engineer: analyzes environments, reviews infrastructure and suggests
architecture and cost adjustments.

## Comparison

| Criterion | ChatGPT (CIP) | Deep | MiniMax |
|---|---|---|---|
| Central approach | Enterprise multi-agent (9 specialists) | Fine-tuning (LoRA/QLoRA) as the core | Hybrid RAG + tools; fine-tuning later |
| Level of technical detail | Conceptual, no code | Generic training code | Executable code, schema, API, IAM |
| Handling of volatile data (pricing) | Not addressed | High risk: price "learned" into the weights | Price always from a live tool |
| Time to first useful version | Undefined (product vision) | 1-2 months of training alone | MVP in 2-3 weeks |
| Maturity as a plan | Feature roadmap (phases 1-9) | Solid ML pipeline, wrong order | Engineering plan with risks/acceptance |

## Why NOT start with fine-tuning (Deep)

- The requirement to "fully understand the clouds" implies **volatile factual knowledge**:
  prices, quotas, new services change almost every week.
- Fine-tuning writes facts into the weights → the model **goes stale and hallucinates with confidence**,
  requiring continuous retraining (expensive and slow).
- Fine-tuning is the right tool for **persona, format and reasoning style** —
  not for facts that change. That is why it becomes **Phase 6 (optional)**, not phase 1.

## Why NOT start with the full multi-agent (ChatGPT/CIP)

- It is the **correct long-term vision** (Knowledge Graph, Cloud Maturity Score,
  controlled PR execution) and serves as the north star.
- But delivering 9 specialists + Inspection Engine + Resource Discovery + dashboards
  all at once is a feature list, not an executable plan in weeks.
- We adopt its **domain-specialist structure**, but introduced
  incrementally.

## Decision

**Backbone = MiniMax** (RAG-first, read-only tools, fine-tuning last)
**+ domain-specialist structure = ChatGPT/CIP**
**+ persona fine-tuning technique = Deep** (final phase, optional).

### How this delivers "not generic / fully understands"

1. **Forced retrieval**: no answer is generated without context retrieved from the official
   base (Well-Architected/CAF/Architecture Framework + service docs).
2. **Metadata by provider/service/category**: the retriever filters by `cloud`,
   `service` and `category`, so the answer is always anchored to the right provider.
3. **Service whitelist** in the system prompt prevents the model from inventing services.
4. **Live tools** validate hypotheses (real cost, inventory, native recommendations)
   before answering.
5. **Specialists** deepen per-domain reasoning (FinOps, Security, SRE, K8s, TF).

## Consequences

- Useful result in weeks, with predictable cost.
- Knowledge updates = monthly re-ingestion (cheap), not retraining.
- Clear evolution path toward the CIP enterprise vision.

See ADRs in [`adr/`](adr/) for the point decisions (vector DB, base LLM, chunking, etc.).
