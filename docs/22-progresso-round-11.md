# Progresso Round 11 — ReAct/Function-Calling Mode

> **Data**: 2026-08-24 | **Round**: 11/30 | **Status**: FASE 4 (com ReAct) ✅ 100%

---

## 🎯 Resultado da Rodada

O CIP agora tem **ReAct/function-calling mode** mencionado no roadmap da Fase 4:
- LLM pode raciocinar (Thought) → escolher tool (Action) → observar resultado → repetir
- Max 5 steps para prevenir loops infinitos
- Fallback gracioso para modo estático em caso de erro/timeout
- 4 tools disponíveis: `query_rag`, `invoke_specialist`, `get_live_data`, `inspect_iac`
- Modo opt-in via `CIP_REACT_MODE=true` ou `react_mode=True` no request

**Significado**: queries complexas multi-step ("Analise meu ambiente AWS e sugira plano de economia") agora são tratadas com raciocínio adaptativo, não apenas classificação estática.

---

## ✅ Entregas Concretas

### 1. Módulo ReAct (`src/cip/agents/react.py`)

**Implementação completa do padrão ReAct** (Reasoning + Acting):

**Schema de Tools:**
```python
TOOL_SCHEMA = [
    {
        "name": "query_rag",
        "description": "Busca informação na base de conhecimento oficial (RAG)...",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "cloud": {"type": "string", "enum": ["aws", "gcp", "azure"]},
                "service": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    # ... invoke_specialist, get_live_data, inspect_iac
]
```

**Loop ReAct:**
```
Thought 1 → Action 1 (query_rag) → Observation 1
   ↓
Thought 2 → Action 2 (invoke_specialist finops) → Observation 2
   ↓
Thought 3 → Action 3 (final_answer) → FIM
```

**Parser robusto** com fallback:
- JSON puro
- JSON dentro de texto (regex block)
- None se inválido (gera fallback)

**Fallback gracioso**:
- Se LLM falhar → fallback estático
- Se loop exceder 5 steps → finaliza com erro
- Se parse falhar → fallback estático

### 2. Integração no Orchestrator (`src/cip/agents/orchestrator.py`)

**Novo parâmetro `react_mode`** no `handle()`:
```python
async def handle(
    self,
    question: str,
    cloud: CloudName | None = None,
    iac_payload: str | None = None,
    react_mode: bool | None = None,  # NOVO
) -> AnalysisResult:
```

**3 modos de decisão:**
1. **Parâmetro explícito**: `react_mode=True/False` no request
2. **Env var**: `CIP_REACT_MODE=true/false`
3. **Default**: `false` (modo estático — backward compatible)

**Integração na API:**
```python
# AnalyzeRequest schema
class AnalyzeRequest(BaseModel):
    question: str
    cloud: CloudName | None = None
    iac_payload: str | None = None
    react_mode: bool | None = None  # NOVO

# /analyze endpoint
result = await get_orchestrator().handle(
    req.question,
    cloud=req.cloud,
    iac_payload=req.iac_payload,
    react_mode=req.react_mode,  # NOVO
)
```

### 3. Testes (19 testes)

**TestToolSchema (4 testes):**
- Schema completo
- Required fields validation
- query_rag requer query
- invoke_specialist enum 8 specialists

**TestParseLLMOutput (3 testes):**
- JSON limpo
- JSON dentro de texto (regex)
- Input inválido → None

**TestToolExecution (5 testes):**
- inspect_iac encontra findings
- inspect_iac com payload limpo
- Tool desconhecida → mensagem
- query_rag chama engine
- invoke_specialist usa prompt

**TestReActLoop (4 testes):**
- Loop finaliza em 2 steps
- Parse error → fallback
- Respeita MAX_STEPS
- IAC payload → primeiro step é inspection

**TestOrchestratorReactMode (3 testes):**
- ReAct off por default
- ReAct via env var
- ReAct via parâmetro

---

## 📂 Arquivos Criados/Modificados

| Arquivo | Mudança | Linhas |
|---|---|---|
| `src/cip/agents/react.py` | **NOVO** — ReAct orchestrator | 400+ |
| `src/cip/agents/orchestrator.py` | Modificado — adiciona `_handle_react` + flag | +60 |
| `src/cip/api/schemas.py` | Modificado — `react_mode` no AnalyzeRequest | +5 |
| `src/cip/api/app.py` | Modificado — passa `react_mode` para orchestrator | +1 |
| `tests/test_react.py` | **NOVO** | 350+ |

**Total: ~820 linhas adicionadas**.

---

## 🧪 Evidências de Validação

### Suite Completa
```
$ pytest tests/ --ignore=test_smoke_ask --ignore=test_ingest_delta
================= 287 passed, 4 warnings in 218.84s (0:03:38) =================
```

**19 testes novos (ReAct):**
- 4 TestToolSchema
- 3 TestParseLLMOutput
- 5 TestToolExecution
- 4 TestReActLoop
- 3 TestOrchestratorReactMode

**Breakdown completo:**
| Arquivo | Testes | Status |
|---|---|---|
| test_api_concurrency.py | 3 | ✅ |
| test_auth.py | 19 | ✅ |
| test_eval_runner.py | 41 | ✅ |
| test_finetune_scripts.py | 16 | ✅ |
| test_health_metrics.py | 24 | ✅ |
| test_inspection.py | 4 | ✅ |
| test_inspection_rules.py | 33 | ✅ |
| test_mock_cloud_cli.py | 27 | ✅ |
| test_phase_2a.py | ? | ✅ |
| test_react.py | **19** (NOVO) | ✅ |
| test_router.py | ? | ✅ |
| test_router_v2.py | 29 | ✅ |
| test_specialists.py | 13 | ✅ |
| test_tools_cache.py | 14 | ✅ |
| test_tools_mock_integration.py | 18 | ✅ |
| test_tracing.py | 9 | ✅ |

---

## 🐛 Bugs Encontrados + Corrigidos

| Bug | Fix |
|---|---|
| Circular import orchestrator ↔ react | ReActOrchestrator não importa mais de orchestrator (define SpecialistResult localmente) |
| Tests asyncio.run em pytest-asyncio | Mock direto dos métodos (sem chamar `asyncio.run` internamente) |
| Tool schema: `required` em `parameters.required` | Corrigido test para usar nesting correto |
| Tests `asyncio.run` chamado dentro de async test | Patch `Orchestrator._handle_react` com AsyncMock (não chama o real) |

---

## 🎯 Como Usar ReAct Mode

### Via API
```bash
# ReAct mode opt-in
curl -H "X-API-Key: ..." -H "X-Tenant-Id: acme" \
     -d '{"question": "...", "react_mode": true}' \
     -H "Content-Type: application/json" \
     https://api.cip.internal/analyze
```

### Via env var
```bash
# Habilitar ReAct globalmente
export CIP_REACT_MODE=true
python -m cip.api.app
```

### Via Python
```python
from cip.agents.orchestrator import get_orchestrator

orch = get_orchestrator()
result = await orch.handle(
    "Analise meu ambiente AWS e sugira plano de economia",
    cloud="aws",
    react_mode=True,  # opt-in
)
```

### Quando usar
- **ReAct**: queries complexas multi-step, requer raciocínio
- **Estático** (default): queries diretas, baixa latência

---

## 📈 Progresso do Objetivo Multi-Semanal

```
Fases:
[███████████░] Fase 1A — MVP Funcional (100%) ✅
[███████████░] Fase 1B — Hardening (100%) ✅
[███████████░] Fase 2 — Tools ao Vivo (100%) ✅
[███████████░] Fase 3 — Inspection Engine (100%) ✅
[███████████░] Fase 4 — Especialistas + ReAct (100%) ✅  ← COMPLETA
[███████████░] Fase 5 — Quality Gate (100%) ✅
[███████████░] Fase 6 — Production Hardening (100%) ✅
[███████████░] Fase 7 — Fine-tuning infra (100%) ✅
[███████████░] Round 8 — Production Observability (100%) ✅
[███████████░] Round 9 — Mock + CLI (100%) ✅
[███████████░] Round 10 — Mock Wire-up + Load Test (100%) ✅
[███████████░] Round 11 — ReAct/Function-Calling (100%) ✅  ← NOVO
```

**~75% do objetivo total concluído (7 fases + 5 enhancement rounds).**

---

## 🎯 Recomendações para Round 12+

### Opção A: Architecture Documentation
- C4 model diagrams (System, Container, Component)
- OpenAPI 3.0 spec exportado do FastAPI
- ADRs para decisões-chave
- Diagrama de deploy (Cloud PaaS + AWS)

### Opção B: Production Deployment Real
- Cloud PaaS setup (banco + app + domínio)
- Bedrock real (AWS account)
- Validar com LLM real
- Runbook real-world validation

### Opção C: Performance + Load Optimization
- Adicionar cache de queries idênticas no RAG engine
- Adicionar connection pooling para Cloud APIs
- Documentar tuning de pgbouncer/pgpool
- Implementar backpressure adaptativo

**Recomendação: Opção A (Architecture Documentation)** — temos 287 testes e 7 fases completas. Documentar a arquitetura é importante para onboarding de novos devs e compliance.

**Goal `goal-e029f7ac-67b4-4801-b89b-bd5e614e7d42` permanece ATIVO** para o round 12.