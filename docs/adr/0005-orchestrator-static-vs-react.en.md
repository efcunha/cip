# ADR 0005 — Orchestrator: Static Mode + ReAct as Opt-in

- **Status**: Accepted
- **Date**: 2026-08-24

## Context

The orchestrator is the "main agent" that combines RAG + tools + specialists + inspection. There are two paradigms for doing this:

1. **Static (fixed routing)**: classifier → runs N specialists in parallel → merge
2. **Dynamic (ReAct/function-calling)**: LLM reasons → chooses tool → executes → reasons again → ...

Each has trade-offs:
- Static: predictable latency, low cost, easy to test, but inflexible
- ReAct: complex multi-step queries, but variable latency, more tokens, harder debugging

## Decision

Implement **both** with static mode as the **default** and ReAct as **opt-in** via flag/env var.

```python
# Default mode (static)
result = await orch.handle("Como otimizar EC2?")
# Latency: ~2s, deterministic, cheap

# ReAct mode (opt-in)
result = await orch.handle("Como otimizar EC2?", react_mode=True)
# Latency: 5-15s, variable, more tokens, adaptive reasoning
```

**Selection criteria:**
- **Static default**: 95% of queries (direct knowledge, IAC review, simple comparison)
- **ReAct opt-in**: multi-step queries that require adaptive reasoning

**Enabling ReAct:**
```bash
# Via env var (global)
export CIP_REACT_MODE=true

# Via request parameter (per-query)
curl -d '{"question": "...", "react_mode": true}' /analyze
```

## Consequences

**Positive:**
- Backward compatible (default does not change)
- p95 latency < 5s maintained in static mode
- Complex queries gain reasoning
- Graceful fallback: ReAct failed → static mode
- Max 5 steps prevents infinite loops

**Negative:**
- ReAct requires a reliable LLM to generate well-formed JSON
- ReAct uses more tokens (cost ~3-5x that of static)
- LLM JSON parsing is fragile (needs fallback)
- ReAct mode needs a real LLM (does not work with stub)

**Mitigations:**
- Robust JSON parser (regex fallback)
- Fallback to static mode on any error
- Max 5 steps hard limit
- Tests cover error scenarios

## References

- [ReAct Paper](https://arxiv.org/abs/2210.03629) (Yao et al., 2022)
- [Function Calling Best Practices](https://platform.openai.com/docs/guides/function-calling) (OpenAI, 2024)
- `src/cip/agents/react.py` (implementation)
- `src/cip/agents/orchestrator.py` (integration)
