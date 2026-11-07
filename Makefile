# MoneyShift: run `make help` for the common tasks.
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend and frontend dependencies
	cd backend && uv sync
	cd frontend && npm ci

build: ## Build the Angular app (served by the backend)
	cd frontend && npm run build

run: build ## Build the app and start the host server (players join over Wi-Fi)
	cd backend && uv run python -m app

serve: ## Start the host server without rebuilding the frontend
	cd backend && uv run python -m app

dev-backend: ## Backend with auto-reload on http://localhost:8000
	cd backend && uv run uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Angular dev server on http://localhost:4200 (proxies /api to :8000)
	cd frontend && npm start -- --host 0.0.0.0

test: ## Run backend and frontend tests
	cd backend && uv run pytest -q
	cd frontend && npx ng test --watch=false

lint: ## Lint backend (ruff) and frontend (eslint)
	cd backend && uv run ruff check .
	cd frontend && npx ng lint

clean: ## Remove the built frontend (use if old build files pile up)
	rm -rf frontend/dist

.PHONY: help clean setup build run serve dev-backend dev-frontend test lint
