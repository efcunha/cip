FROM python:3.13-slim AS base

# Python 3.13 (NÃO 3.14) — evita bug asyncpg pool + event loop que mata o
# orchestrator após ~3 queries pesadas com compare intent. Bug não existe
# em 3.12/3.13 mas aparece em 3.14 (verified Round 22).

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Deps do sistema: libpq-dev (psycopg), curl (healthcheck), gcc (build wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# ── Código + metadata (editable install exige o pacote `src/` presente) ──
# `pip install -e .` resolve [tool.setuptools.packages.find] where=["src"],
# então `src/` precisa existir ANTES do install (não depois).
COPY pyproject.toml README.md ./
COPY src ./src
COPY db ./db
COPY scripts ./scripts
RUN pip install --upgrade pip && pip install -e .

# ── Usuário não-root (segurança) ───────────────────────────────────
RUN useradd -m cip && chown -R cip:cip /app
USER cip

# ── Healthcheck (Docker sabe se o container está saudável) ────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

EXPOSE 8000

# ── Defaults (sobreponíveis via env ou docker-compose) ─────────────
ENV LLM_PROVIDER=minimax \
    LLM_MODEL=MiniMax-M3 \
    LLM_BASE_URL=https://api.minimax.io/v1 \
    LLM_CONTEXT_SIZE=1000000 \
    LLM_MAX_TOKENS=131072 \
    LLM_TIMEOUT_S=60 \
    LLM_MAX_RETRIES=2 \
    EMBED_PROVIDER=local \
    EMBED_MODEL=BAAI/bge-large-en-v1.5 \
    EMBED_DIM=1024 \
    EMBED_DEVICE=cpu \
    CIP_ENV=production \
    CIP_READONLY=true \
    LOG_LEVEL=INFO \
    PORT=8000

# ── CMD: uvicorn com 1 worker + loop uvloop (default) ──────────────
CMD ["uvicorn", "cip.api.app:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]

# ═══════════════════════════════════════════════════════════════════
# Estágio de HOMOLOGAÇÃO (opcional) — NÃO usado em produção.
# Estende o runtime enxuto com eval/, tests/ e as dev deps (pytest etc.)
# para permitir rodar `preflight`, `eval-strict` e a suite de testes DENTRO
# do container (necessário no ambiente Podman/WSL, onde a porta do Postgres
# não é alcançável do host). Build: `docker build --target homolog .`
# ou no compose: `build: { target: homolog }`.
# A imagem default (estágio `base`) continua sem esses artefatos.
# ═══════════════════════════════════════════════════════════════════
FROM base AS homolog

USER root
# O estágio homolog copia o REPO INTEIRO do build context (excluindo o que o
# .dockerignore já filtra: .env, caches, .venv etc.), porque a suíte completa
# de testes referencia artefatos de build/CI espalhados pela raiz:
#   - Makefile (targets), docker-compose.yml, Dockerfile
#   - CHANGELOG.md, CONTRIBUTING.md, QUICKSTART.md, .env.example
#   - docs/, ops/ (dashboard Grafana), .github/ (templates PR), .devcontainer/
#   - web/, eval/, tests/
# Sem isso, `pytest` DENTRO do container falha com FileNotFoundError.
# O estágio `base` permanece enxuto (só src/ + db/ + scripts/).
COPY . ./
RUN pip install -e ".[dev]" && chown -R cip:cip /app
USER cip
