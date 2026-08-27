# ADR 0005 — Orchestrator: Modo Estático + ReAct como Opt-in

- **Status**: Aceito
- **Data**: 2026-08-24

## Contexto

O orchestrator é o "agente principal" que combina RAG + tools + specialists + inspection. Existem dois paradigmas para fazer isso:

1. **Estático (roteamento fixo)**: classificador → executa N specialists em paralelo → merge
2. **Dinâmico (ReAct/function-calling)**: LLM raciocina → escolhe tool → executa → raciocina novamente → ...

Cada um tem trade-offs:
- Estático: latência previsível, baixo custo, fácil de testar, mas inflexível
- ReAct: queries complexas multi-step, mas latência variável, mais tokens, debugging difícil

## Decisão

Implementar **ambos** com modo estático como **default** e ReAct como **opt-in** via flag/env var.

```python
# Modo padrão (estático)
result = await orch.handle("Como otimizar EC2?")
# Latência: ~2s, determinístico, barato

# Modo ReAct (opt-in)
result = await orch.handle("Como otimizar EC2?", react_mode=True)
# Latência: 5-15s, variável, mais tokens, raciocínio adaptativo
```

**Critérios de seleção:**
- **Default estático**: 95% das queries (conhecimento direto, IAC review, comparacao simples)
- **ReAct opt-in**: queries multi-step que requerem raciocínio adaptativo

**Ativação do ReAct:**
```bash
# Via env var (global)
export CIP_REACT_MODE=true

# Via request parameter (per-query)
curl -d '{"question": "...", "react_mode": true}' /analyze
```

## Consequências

**Positivas:**
- Backward compatible (default não muda)
- Latência p95 < 5s mantida no modo estático
- Queries complexas ganham raciocínio
- Fallback gracioso: ReAct falhou → modo estático
- Max 5 steps previne loops infinitos

**Negativas:**
- ReAct requer LLM confiável para gerar JSON bem-formado
- ReAct usa mais tokens (custo ~3-5x do estático)
- Parsing de JSON do LLM é fragil (precisa fallback)
- Modo ReAct precisa de LLM real (não funciona com stub)

**Mitigações:**
- Parser JSON robusto (regex fallback)
- Fallback para modo estático em qualquer erro
- Max 5 steps hard limit
- Testes cobrem cenários de erro

## Referências

- [ReAct Paper](https://arxiv.org/abs/2210.03629) (Yao et al., 2022)
- [Function Calling Best Practices](https://platform.openai.com/docs/guides/function-calling) (OpenAI, 2024)
- `src/cip/agents/react.py` (implementação)
- `src/cip/agents/orchestrator.py` (integração)
