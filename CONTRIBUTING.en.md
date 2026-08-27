# Contributing to CIP

> Guide for new contributors. Welcome! 🎉

## How to contribute

1. **Issues**: Look for `good first issue` or `help wanted` labels
2. **PRs**: Fork → branch → commit → push → PR
3. **Discussions**: Use GitHub Discussions for design questions

## Development workflow

```bash
# 1. Setup
git clone <repo> && cd cip
make install

# 2. Create a branch
git checkout -b feature/minha-feature

# 3. Develop (with hot-reload if applicable)
# 4. Tests
make test-fast         # fast tests
make preflight         # 7 gates before PR
make test-react        # if you touch agents/react.py
make test-mock         # if you touch tools/ or mock/

# 5. Commit (Conventional Commits)
git commit -m "feat(tools): add GCP Cloud Run cost tool"
git commit -m "fix(orchestrator): handle empty specialists list"
git commit -m "docs(adr): add ADR-0007 for cache strategy"

# 6. Push + PR
git push origin feature/minha-feature
gh pr create  # or via GitHub UI
```

## Code conventions

### Python
- **Type hints** on public functions
- **Docstrings** on modules, classes, functions
- **PEP 8** enforced via `ruff check`
- **Line length** 100 (configured in `pyproject.toml`)

### Commits (Conventional Commits)
```
feat(scope): add new feature
fix(scope): bug fix
docs(scope): documentation only
test(scope): add/update tests
refactor(scope): code change that neither fixes bug nor adds feature
chore(scope): maintenance tasks
```

Examples:
- `feat(tools): add GCP Recommender for Cloud Run`
- `fix(orchestrator): ReAct mode falls back when LLM error`
- `docs(adr): add ADR-0007 cache strategy`

### Branches
- `main` — production (protected)
- `develop` — integration
- `feature/<desc>` — new feature
- `fix/<desc>` — bug fix
- `docs/<desc>` — docs only

### PRs
- 1 PR = 1 feature/fix
- Descriptive title
- Description: WHAT changed, WHY, and HOW to test
- Link to the issue (if any)
- CI must pass (tests + preflight + lint)

## Project structure

```
cip/
├── src/cip/                # main code (Python package)
│   ├── agents/            # orchestrator, router, specialists, ReAct
│   ├── api/               # FastAPI app, auth, health, schemas
│   ├── ingestion/         # KB ingestion pipeline
│   ├── inspection/        # Terraform/K8s rules
│   ├── observability/     # metrics, audit log
│   ├── prompts/           # system prompt + 8 specialists
│   ├── rag/               # RAG engine, embeddings, LLM
│   ├── tools/             # AWS/Azure/GCP clients + cache + mock
│   └── tracing.py         # Langfuse wrapper
├── tests/                 # 302 pytest tests
├── scripts/               # CLI, mock server, demo, preflight, etc.
├── eval/                  # 95 eval cases + run_eval.py
├── docs/                  # architecture, ADRs, runbook
├── db/schema.sql          # Postgres schema
└── docker-compose.yml     # dev environment
```

## Where to make changes

| If you want to... | Look at |
|---|---|
| Add a new cloud provider (e.g. Oracle) | `src/cip/tools/` + `src/cip/agents/router.py` (CLOUD_KEYWORDS) + `src/cip/prompts/specialists.py` (new SPECIALIST) |
| Add a new Inspection rule (TF or K8s) | `src/cip/inspection/{terraform,kubernetes}.py` + tests in `tests/test_inspection_rules.py` |
| Add a new specialist | `src/cip/prompts/specialists.py` + `src/cip/agents/router.py` (DOMAIN_KEYWORDS) |
| Add a new tool (e.g. kubectl, terraform validate) | `src/cip/tools/` + register in `src/cip/tools/registry.py` |
| Modify the orchestrator | `src/cip/agents/orchestrator.py` (static) or `src/cip/agents/react.py` (ReAct) |
| Add an API endpoint | `src/cip/api/app.py` + schema in `src/cip/api/schemas.py` |
| Modify the system prompt | `src/cip/prompts/system.py` |
| Add an eval case | `eval/test_cases.json` |
| Add an ADR | `docs/adr/NNNN-titulo-descritivo.md` (format: see existing) |

## Tests

### Structure of a test
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

### Run specific tests
```bash
# By file
pytest tests/test_inspection_rules.py -v

# By class
pytest tests/test_routes.py::TestClassifyIntent -v

# By name
pytest tests/ -k "test_aws_summarize" -v
```

### Common fixtures
- `temp_path_safe` (in `tests/test_documentation.py`) — Windows-safe temp path
- `mock_server` (in `tests/test_tools_mock_integration.py`) — mock cloud server in the background
- `reset_singletons` (in `tests/test_specialists.py`) — clears engine/orchestrator singletons

## Code patterns

### Imports
```python
# Stdlib first
import json
from typing import Any

# Third-party second
import httpx
from fastapi import HTTPException

# Local last
from cip.config import get_settings
from cip.logging import get_logger
```

### Logging
```python
from cip.logging import get_logger

log = get_logger(__name__)

# Levels
log.debug("detailed info")    # dev only
log.info("normal flow")        # default
log.warning("degraded mode")   # recoverable
log.error("operation failed", error=str(exc))  # failures
```

### Error handling
```python
# In tools (best-effort, never kills the response)
try:
    result = tool.execute()
except Exception as exc:
    log.warning("tool_failed", error=str(exc))
    return None  # or fallback message

# In the API (fail loud)
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
# Don't use os.environ directly
```

## Pre-flight checks

Before submitting a PR, always run:

```bash
make preflight
```

If it returns 1 (NO-GO), fix it before requesting review.

## Code review

- **1-2 reviewers** minimum
- **CI must pass** (tests + preflight)
- **Comments** must be addressed (resolve or explain)
- **Conversation** > defensiveness: it's a collaboration

## Releases

- **Versioning**: SemVer (MAJOR.MINOR.PATCH)
- **Changelog**: `docs/CHANGELOG.md` (TODO: create)
- **Tags**: `v0.1.0`, `v0.2.0`, etc.
- **Release notes**: highlights + breaking changes

## Support

- **GitHub Issues**: bugs, features, questions
- **GitHub Discussions**: design, architecture
- **Email**: maintainers (see `CODEOWNERS`)

## Code of Conduct

- **Be respectful**: critique code, not people
- **Be inclusive**: welcoming to all backgrounds
- **Be patient**: new contributors may have basic questions
- **Be curious**: ask before assuming

---

**Thanks for contributing! 🙏**

— CIP Team
