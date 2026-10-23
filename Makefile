# PreciseCapture developer commands. Every target documented in CLAUDE.md lives here.
# Python runs through uv (apps/api/.venv); JS through pnpm workspaces.

SHELL := /bin/bash
COMPOSE := docker compose -f infra/docker/docker-compose.dev.yml $(if $(wildcard .env),--env-file .env,)
API_DIR := apps/api
API := cd $(API_DIR) && uv run
WEB_DIR := apps/web
SCHEMA_DIR := packages/schema

.DEFAULT_GOAL := help

.PHONY: help dev-up dev-down dev-logs dev-reset api-install api-migrate api-makemigrations api-run \
        api-worker api-shell api-test api-test-integration api-lint api-format contract mock \
        web-dev web-test web-lint schema-build schema-test check

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Local services ------------------------------------------------------------

dev-up: ## Start Postgres/PostGIS, Redis, MinIO, Martin, Mailpit
	$(COMPOSE) up -d

dev-down: ## Stop the local services (data volumes are kept)
	$(COMPOSE) down

dev-logs: ## Tail service logs
	$(COMPOSE) logs -f --tail=100

dev-reset: ## Stop services AND delete their data volumes (asks first)
	@read -p "This deletes the local database and MinIO data. Continue? [y/N] " a && [[ $$a == y ]]
	$(COMPOSE) down -v

# --- API (Django) --------------------------------------------------------------

api-install: ## uv sync (creates apps/api/.venv)
	cd $(API_DIR) && uv sync

api-migrate: ## Run migrations as pc_owner on the `migrations` alias
	$(API) python manage.py migrate --database=migrations

api-makemigrations: ## Create migrations for changed models
	$(API) python manage.py makemigrations

api-run: ## Dev server on :8000  (docs at /api/v1/docs)
	$(API) python manage.py runserver 0.0.0.0:8000

api-worker: ## Celery worker
	$(API) celery -A config worker --loglevel=info

api-shell: ## Django shell
	$(API) python manage.py shell

api-test: ## pytest (unit + API tests; integration tests need `make dev-up`)
	$(API) pytest

api-test-integration: ## Only the tests marked `integration` (need the docker services)
	$(API) pytest -m integration

api-lint: ## ruff check + ruff format --check + mypy
	$(API) ruff check .
	$(API) ruff format --check .
	$(API) mypy .

api-format: ## ruff format + autofix
	$(API) ruff check --fix .
	$(API) ruff format .

# --- Contract ------------------------------------------------------------------

contract: ## Export OpenAPI to contract/openapi.json and regenerate packages/api-client
	$(API) python manage.py export_openapi_schema --api config.api.api --output ../../contract/openapi.json --indent 2
	@if [ -f packages/api-client/package.json ]; then pnpm --filter @precisecapture/api-client generate; \
	 else echo "packages/api-client not created yet (M4); contract/openapi.json exported."; fi

mock: ## Prism mock server of the contract on :4010 (for the mobile app)
	pnpm dlx @stoplight/prism-cli@5 mock contract/openapi.json --port 4010 --dynamic

# --- Web (React) ---------------------------------------------------------------

web-dev: ## pnpm --filter web dev
	@if [ -f $(WEB_DIR)/package.json ]; then pnpm --filter web dev; else echo "apps/web not created yet (M8)"; fi

web-test: ## vitest
	@if [ -f $(WEB_DIR)/package.json ]; then pnpm --filter web test; else echo "apps/web not created yet (M8)"; fi

web-lint: ## eslint + prettier + tsc
	@if [ -f $(WEB_DIR)/package.json ]; then pnpm --filter web lint; else echo "apps/web not created yet (M8)"; fi

# --- Shared schema -------------------------------------------------------------

schema-build: ## Build packages/schema (dist/)
	pnpm --filter @precisecapture/schema build

schema-test: ## Validate examples against JSON Schemas; run the shared test vectors (TS + Python)
	pnpm --filter @precisecapture/schema lint
	pnpm --filter @precisecapture/schema test
	$(API) pytest tests/schema

check: api-lint api-test ## Everything CI runs for the API
