# CIP — Cloud Intelligence Platform
# Makefile para os targets mais comuns do dev workflow
# Uso: make <target>

.PHONY: help install test test-fast test-suite test-react test-mock lint format \
        preflight preflight-fast demo demo-mock demo-react bench mock-server \
        up down clean docs clean-logs ci-test ci-preflight ci-eval \
        homolog homolog-fast homolog-real homolog-software-arch homolog-cases \
        ingest-forum-cases schema-migrate forum-fetch

# ─────────────────────────────────────────────────────────────────────────
# Default + Help
# ─────────────────────────────────────────────────────────────────────────

help:  ## Mostra esta ajuda
	@echo "CIP — Makefile targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Exemplos:"
	@echo "  make install         # Instala deps"
	@echo "  make test-fast       # Roda testes rápidos (sem smoke/ingest)"
	@echo "  make preflight       # Valida 7 gates antes de deploy"
	@echo "  make demo-mock       # Demo com mock cloud (recomendado em dev)"
	@echo "  make docs            # Gera OpenAPI spec"

# ─────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────

install:  ## Instala o pacote + deps de dev
	pip install -e ".[dev]"

clean:  ## Limpa caches e temp files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .tmp_test 2>/dev/null || true
	rm -f src/cip.egg-info/PKG-INFO

# ─────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────

test:  ## Roda suite completa de testes
	pytest tests/ -v

test-fast:  ## Roda suite sem smoke/ingest (CI rápido)
	pytest tests/ --ignore=tests/test_smoke_ask.py --ignore=tests/test_ingest_delta.py

test-suite:  ## Roda só os testes de unidade + integração
	pytest tests/test_*.py -k "not smoke and not ingest_delta" -v

test-react:  ## Roda testes do ReAct mode
	pytest tests/test_react.py -v

test-mock:  ## Roda testes do mock cloud + integração
	pytest tests/test_mock_cloud_cli.py tests/test_tools_mock_integration.py -v

# ─────────────────────────────────────────────────────────────────────────
# Lint / Format
# ─────────────────────────────────────────────────────────────────────────

lint:  ## Roda ruff check
	ruff check src/ tests/ eval/ scripts/

format:  ## Formata código com ruff
	ruff format src/ tests/ eval/ scripts/

# ─────────────────────────────────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────────────────────────────────

demo:  ## Roda demo end-to-end (6 queries showcase)
	python scripts/demo.py

demo-mock:  ## Demo com mock cloud (CIP_USE_MOCK_CLOUDS=true)
	@echo "ATENCAO: Certifique-se que o mock server esta rodando (make mock-server)"
	CIP_USE_MOCK_CLOUDS=true python scripts/demo.py

demo-react:  ## Demo com ReAct mode habilitado
	python scripts/demo.py --react

bench:  ## Roda benchmark de performance (50 queries)
	python scripts/load_test.py --n 50

# ─────────────────────────────────────────────────────────────────────────
# Mock server (dev/CI)
# ─────────────────────────────────────────────────────────────────────────

mock-server:  ## Sobe mock cloud server em background (porta 8888)
	python scripts/mock_cloud_server.py --port 8888 &

# ─────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────

schema:  ## Aplica schema.sql no DB (DATABASE_URL env)
	@if [ -z "$$DATABASE_URL" ]; then \
		echo "ERROR: DATABASE_URL nao definida"; exit 1; \
	fi
	psql $$DATABASE_URL -f db/schema.sql

ingest:  ## Roda ingestao MVP (~245 URLs -> ~237 chunks)
	python -m cip.ingestion.ingest --scope mvp

ingest-full:  ## Ingestao FULL (245 URLs + expand)
	python -m cip.ingestion.ingest --scope full --expand

ingest-dry:  ## Dry-run da ingestao (nao persiste)
	python -m cip.ingestion.ingest --scope mvp --dry-run

# ─────────────────────────────────────────────────────────────────────────
# Quality Gate (eval)
# ─────────────────────────────────────────────────────────────────────────

eval:  ## Roda eval suite (gate de qualidade)
	python eval/run_eval.py --offline --report-md

eval-strict:  ## Eval com --strict (bloqueia se gate falhar)
	python eval/run_eval.py --offline --report-md --strict

preflight:  ## Roda pre-flight check (7 gates antes de deploy)
	python scripts/preflight.py

preflight-fast:  ## Pre-flight sem test suite (CI rapido)
	python scripts/preflight.py --skip-tests

# ─────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────

up:  ## Sobe a API em background (porta 8000)
	@echo "Iniciando API na porta 8000..."
	uvicorn cip.api.app:app --host 0.0.0.0 --port 8000 &

down:  ## Para a API (mata processos uvicorn)
	@pkill -f "uvicorn cip.api.app" 2>/dev/null || echo "Nenhum processo uvicorn encontrado"

# ─────────────────────────────────────────────────────────────────────────
# Web UI (Playground local — Round 17)
# ─────────────────────────────────────────────────────────────────────────

web:  ## Serve a Web UI (Playground) em http://localhost:8080
	@echo "Web UI rodando em http://localhost:8080"
	@echo "Certifique-se que a API está rodando: make up (em outro terminal)"
	python scripts/serve_web.py --port 8080

web-no-open:  ## Web UI sem abrir browser
	python scripts/serve_web.py --port 8080 --no-browser

# ─────────────────────────────────────────────────────────────────────────
# Cron / Manutencao
# ─────────────────────────────────────────────────────────────────────────

drift:  ## Detecta drift na documentacao
	python scripts/monthly_reingest.py --detect-only

cron:  ## Roda cron mensal completo (drift + re-ingest se necessario)
	python scripts/monthly_cron.py

# ─────────────────────────────────────────────────────────────────────────
# Homologacao Local (Round 20)
# ─────────────────────────────────────────────────────────────────────────

homolog:  ## Setup completo do ambiente de homologacao local (podman)
	@echo "Iniciando setup de homologacao..."
	python scripts/setup_homolog.py

homolog-fast:  ## Setup rapido (sem ingestion, assume KB ja populada)
	python scripts/setup_homolog.py --skip-ingest

smoke:  ## Roda smoke tests contra API rodando
	python scripts/smoke_test.py --url http://localhost:8000

smoke-verbose:  ## Smoke tests com detalhes
	python scripts/smoke_test.py --url http://localhost:8000 --verbose

# ─────────────────────────────────────────────────────────────────────────
# Homologação com LLM REAL (MiniMax M3, Bedrock, OpenAI)
# ─────────────────────────────────────────────────────────────────────────

homolog-real:  ## Homolog end-to-end com LLM real (LLM_PROVIDER=minimax padrao, --runs 3 por maioria)
	@echo "Validando homolog com LLM real (--runs 3 por maioria)..."
	@if [ "$$LLM_PROVIDER" = "stub" ] || [ -z "$$LLM_PROVIDER" ]; then \
		echo "  [WARN] LLM_PROVIDER=stub detectado. Use LLM_PROVIDER=minimax para homolog real."; \
	fi
	python scripts/homolog_validate.py --strict --runs 3

homolog-software-arch:  ## Homolog focado em software architecture patterns
	python scripts/homolog_validate.py --area software_architecture --strict

homolog-cases:  ## Homolog focado em case studies / postmortems
	python scripts/homolog_validate.py --area case_studies --strict

# ─────────────────────────────────────────────────────────────────────────
# Forum case studies (HackerNews, dev.to, Reddit)
# ─────────────────────────────────────────────────────────────────────────

forum-fetch:  ## Busca URLs de postmortems em HackerNews/dev.to/Reddit
	python scripts/ingest_forum_cases.py --fetch-only

ingest-forum-cases:  ## Busca + ingere postmortems de fóruns (adiciona à KB)
	python scripts/ingest_forum_cases.py

# ─────────────────────────────────────────────────────────────────────────
# Schema migrations
# ─────────────────────────────────────────────────────────────────────────

schema-migrate:  ## Aplica migrations SQL pendentes (idempotente)
	python scripts/apply_migrations.py

# ─────────────────────────────────────────────────────────────────────────
# Documentation
# ─────────────────────────────────────────────────────────────────────────

docs:  ## Exporta OpenAPI spec para docs/openapi.json
	python scripts/export_openapi.py --output docs/openapi.json
	@echo "OpenAPI spec exportado para docs/openapi.json"

docs-yaml:  ## Exporta OpenAPI spec em YAML (requer pyyaml)
	python scripts/export_openapi.py --output docs/openapi.yaml --format yaml

clean-logs:  ## Limpa audit log
	rm -f .audit/audit.jsonl

# ─────────────────────────────────────────────────────────────────────────
# CI / Lint helpers
# ─────────────────────────────────────────────────────────────────────────

ci-test:  ## CI test: skip slow tests, report
	pytest tests/ \
		--ignore=tests/test_smoke_ask.py \
		--ignore=tests/test_ingest_delta.py \
		--tb=short -q

ci-preflight:  ## CI pre-flight sem test suite
	python scripts/preflight.py --skip-tests --strict

ci-eval:  ## CI eval gate (offline/Inspection Engine — determinístico, sem --runs)
	python eval/run_eval.py --offline --strict
