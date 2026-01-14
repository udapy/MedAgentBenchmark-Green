.PHONY: help install dev test verify verify-e2e verify-e2e-docker clean docker-up docker-down docker-logs

help: ## Show this help message
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies using uv
	uv sync --all-extras

dev: ## Run local dev server with hot reload
	@echo "Starting Development Server..."
	uv run uvicorn src.a2a_adapter.server:create_server --factory --reload --host 0.0.0.0 --port 8000

test: ## Run unit tests
	uv run pytest tests/

verify: ## Run internal agent self-verification (unit/integration)
	uv run verify_agent.py task1_1

verify-e2e: ## Run E2E verification against LOCAL process (spawns Green Agent locally)
	uv run scripts/verify_e2e.py

verify-e2e-docker: ## Run E2E verification against DOCKER containers (requires 'make docker-up')
	export EXTERNAL_GREEN_AGENT_URL="http://localhost:9009" && uv run scripts/verify_e2e.py

docker-up: ## Start Docker services (detached + build)
	docker compose up -d --build

docker-down: ## Stop Docker services
	docker compose down

docker-logs: ## Follow Docker logs
	docker compose logs -f

clean: ## Clean up cache and temp files
	rm -rf __pycache__ .pytest_cache .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
