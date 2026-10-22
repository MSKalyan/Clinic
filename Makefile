# Common tasks for the Clinic Operations Assistant.
#   make help    — list everything
#   make dev     — full local stack in Docker
#   make test    — backend tests + frontend typecheck

SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
COMPOSE := docker compose
PROD_COMPOSE := docker compose -f docker-compose.yml -f docker-compose.prod.yml
VENV := .venv/bin

.DEFAULT_GOAL := help
.PHONY: help dev dev-fg stop down logs logs-backend logs-frontend \
        build rebuild migrate makemigrations seed shell dbshell \
        test test-backend test-frontend typecheck lint format \
        prod-build prod-up prod-down prod-logs check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- development ---------------------------------------------------------

dev: ## Start the development stack (Postgres, Redis, API, workers, UI)
	$(COMPOSE) up --build

dev-fg: ## Start the development stack in the foreground
	$(COMPOSE) up --build

stop: ## Stop the development stack
	$(COMPOSE) stop

down: ## Stop the development stack and remove its volumes
	$(COMPOSE) down -v

logs: ## Tail all development logs
	$(COMPOSE) logs -f

logs-backend: ## Tail the API logs
	$(COMPOSE) logs -f backend

logs-frontend: ## Tail the dashboard logs
	$(COMPOSE) logs -f frontend

shell: ## Open a Django shell in the backend container
	$(COMPOSE) exec backend python manage.py shell

dbshell: ## Open a psql session
	$(COMPOSE) exec postgres psql -U clinic_app -d clinic

# --- database ------------------------------------------------------------

migrate: ## Apply database migrations
	$(COMPOSE) exec backend python manage.py migrate

makemigrations: ## Generate new migrations
	$(COMPOSE) exec backend python manage.py makemigrations

seed: ## Load demo data
	$(COMPOSE) exec backend python manage.py seed_demo

# --- build ---------------------------------------------------------------

build: ## Build all images
	$(COMPOSE) build

rebuild: ## Rebuild all images from scratch
	$(COMPOSE) build --no-cache

# --- production ----------------------------------------------------------

prod-build: ## Build the production images
	$(PROD_COMPOSE) build

prod-up: ## Start the production stack
	$(PROD_COMPOSE) up -d

prod-down: ## Stop the production stack
	$(PROD_COMPOSE) down

prod-logs: ## Tail production logs
	$(PROD_COMPOSE) logs -f

# --- quality -------------------------------------------------------------

test: test-backend typecheck ## Run every check

test-backend: ## Run the backend test suite
	cd $(BACKEND) && ../$(VENV)/python -m pytest -q

test-frontend: ## Run the frontend test suite
	cd $(FRONTEND) && npm test --if-present

typecheck: ## Type-check the frontend
	cd $(FRONTEND) && npm run typecheck

lint: ## Lint the backend
	cd $(BACKEND) && ../$(VENV)/python -m ruff check apps config tests

format: ## Format the backend
	cd $(BACKEND) && ../$(VENV)/python -m ruff format apps config tests

check: lint test typecheck ## Lint, test and type-check everything

clean: ## Remove caches and build artefacts
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete
	rm -rf $(FRONTEND)/.next $(FRONTEND)/node_modules/.cache
	rm -rf .pytest_cache $(BACKEND)/.pytest_cache
