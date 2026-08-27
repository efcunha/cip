# Contributing to CIP

> Guia para novos contribuidores. Bem-vindo! 🎉

## Como contribuir

1. **Issues**: Procure `good first issue` ou `help wanted` labels
2. **PRs**: Fork → branch → commit → push → PR
3. **Discussões**: Use GitHub Discussions para perguntas de design

## Workflow de desenvolvimento

```bash
# 1. Setup
git clone <repo> && cd cip
make install

# 2. Criar branch
git checkout -b feature/minha-feature

# 3. Desenvolver (com hot-reload se aplicável)
# 4. Testes
make test-fast         # testes rápidos
make preflight         # 7 gates antes de PR
make test-react        # se mexer em agents/react.py
make test-mock         # se mexer em tools/ ou mock/

# 5. Commit (Conventional Commits)
git commit -m "feat(tools): add GCP Cloud Run cost tool"
git commit -m "fix(orchestrator): handle empty specialists list"
git commit -m "docs(adr): add ADR-0007 for cache strategy"

# 6. Push + PR
git push origin feature/minha-feature
gh pr create  # ou via GitHub UI
```

## Convenções de código

### Python
- **Type hints** em funções públicas
- **Docstrings** em módulos, classes, funções
- **PEP 8** enforced via `ruff check`
- **Line length** 100 (configurado no `pyproject.toml`)

### Commits (Conventional Commits)
```
feat(scope): add new feature
fix(scope): bug fix
docs(scope): documentation only
test(scope): add/update tests
refactor(scope): code change that neither fixes bug nor adds feature
chore(scope): maintenance tasks
```

Exemplos:
- `feat(tools): add GCP Recommender for Cloud Run`
- `fix(orchestrator): ReAct mode falls back when LLM error`
- `docs(adr): add ADR-0007 cache strategy`

### Branches
- `main` — produção (protegido)
- `develop` — integração
- `feature/<desc>` — nova feature
- `fix/<desc>` — bug fix
- `docs/<desc>` — só docs

### PRs
- 1 PR = 1 feature/fix
- Título descritivo
- Descrição: O QUE mudou, POR QUÊ, e COMO testar
- Vincular a issue (se houver)
- CI deve passar (testes + preflight + lint)

## Estrutura do projeto

```
cip/
├── src/cip/                # código principal (pacote Python)
│   ├── agents/            # orchestrator, router, specialists, ReAct
│   ├── api/               # FastAPI app, auth, health, schemas
│   ├── ingestion/         # pipeline de ingestão da KB
│   ├── inspection/        # regras Terraform/K8s
│   ├── observability/     # metrics, audit log
│   ├── prompts/           # system prompt + 8 specialists
│   ├── rag/               # RAG engine, embeddings, LLM
│   ├── tools/             # AWS/Azure/GCP clients + cache + mock
│   └── tracing.py         # Langfuse wrapper
├── tests/                 # 302 testes pytest
├── scripts/               # CLI, mock server, demo, preflight, etc.
├── eval/                  # 95 casos de eval + run_eval.py
├── docs/                  # arquitetura, ADRs, runbook
├── db/schema.sql          # schema do Postgres
└── docker-compose.yml     # dev environment
```

## Onde mexer

| Se você quer... | Olhe em |
|---|---|
| Adicionar novo provedor cloud (ex: Oracle) | `src/cip/tools/` + `src/cip/agents/router.py` (CLOUD_KEYWORDS) + `src/cip/prompts/specialists.py` (novo SPECIALIST) |
| Adicionar nova regra Inspection (TF ou K8s) | `src/cip/inspection/{terraform,kubernetes}.py` + testes em `tests/test_inspection_rules.py` |
| Adicionar novo especialista | `src/cip/prompts/specialists.py` + `src/cip/agents/router.py` (DOMAIN_KEYWORDS) |
| Adicionar nova tool (ex: kubectl, terraform validate) | `src/cip/tools/` + registrar em `src/cip/tools/registry.py` |
| Modificar orchestrator | `src/cip/agents/orchestrator.py` (estático) ou `src/cip/agents/react.py` (ReAct) |
| Adicionar endpoint API | `src/cip/api/app.py` + schema em `src/cip/api/schemas.py` |
| Modificar prompt do sistema | `src/cip/prompts/system.py` |
| Adicionar caso de eval | `eval/test_cases.json` |
| Adicionar ADR | `docs/adr/NNNN-titulo-descritivo.md` (formato: ver existentes) |

## Testes

### Estrutura de um teste
```python
# tests/test_<module>.py
import pytest
from src.cip.<module> import <Component>

class TestComponent:
    def test_feature_works(self) -> None:
        # Arrange
        ...
        # Act
        result = component.do_thing()
        # Assert
        assert result == expected
```

### Rodar testes específicos
```bash
# Por arquivo
pytest tests/test_inspection_rules.py -v

# Por classe
pytest tests/test_routes.py::TestClassifyIntent -v

# Por nome
pytest tests/ -k "test_aws_summarize" -v
```

### Fixtures comuns
- `temp_path_safe` (em `tests/test_documentation.py`) — path temp Windows-safe
- `mock_server` (em `tests/test_tools_mock_integration.py`) — mock cloud server em background
- `reset_singletons` (em `tests/test_specialists.py`) — limpa engine/orchestrator singletons

## Padrões de código

### Imports
```python
# Stdlib primeiro
import json
from typing import Any

# Third-party segundo
import httpx
from fastapi import HTTPException

# Local por último
from cip.config import get_settings
from cip.logging import get_logger
```

### Logging
```python
from cip.logging import get_logger

log = get_logger(__name__)

# Níveis
log.debug("detailed info")    # dev only
log.info("normal flow")        # default
log.warning("degraded mode")   # recoverable
log.error("operation failed", error=str(exc))  # failures
```

### Error handling
```python
# Em tools (best-effort, nunca derruba a resposta)
try:
    result = tool.execute()
except Exception as exc:
    log.warning("tool_failed", error=str(exc))
    return None  # ou fallback message

# Em API (fail loud)
from fastapi import HTTPException
try:
    result = risky_op()
except SpecificError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
```

### Settings
```python
from cip.config import get_settings

settings = get_settings()
# Não usar os.environ direto
```

## Pre-flight checks

Antes de submeter PR, sempre rode:

```bash
make preflight
```

Se retornar 1 (NO-GO), conserte antes de pedir review.

## Code review

- **1-2 reviewers** mínimo
- **CI deve passar** (testes + preflight)
- **Comentários** devem ser addressed (resolve ou explique)
- **Conversa** > defensiveness: é uma colaboração

## Releases

- **Versioning**: SemVer (MAJOR.MINOR.PATCH)
- **Changelog**: `docs/CHANGELOG.md` (TODO: criar)
- **Tags**: `v0.1.0`, `v0.2.0`, etc.
- **Release notes**: highlights + breaking changes

## Suporte

- **GitHub Issues**: bugs, features, perguntas
- **GitHub Discussions**: design, arquitetura
- **Email**: maintainers (ver `CODEOWNERS`)

## Código de Conduta

- **Seja respeitoso**: critique código, não pessoas
- **Seja inclusivo**: welcoming to all backgrounds
- **Seja paciente**: novos contribuidores podem ter dúvidas básicas
- **Seja curioso**: pergunte antes de assumir

---

**Obrigado por contribuir! 🙏**

— Equipe CIP
