.PHONY: help install dev test build run-container clean

# Project variables
IMAGE_NAME := medagent-green
TAG := latest
CONTAINER_NAME := medagent-green-container

help:  ## Show this help message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## Install dependencies using uv
	uv sync --all-extras

dev: ## Run the local development server
	uv run src/server.py

test: ## Run tests using pytest
	uv run pytest

build: ## Build the Docker image
	docker build -t $(IMAGE_NAME):$(TAG) .

run-container: ## Run the built Docker container
	docker run --rm -it -p 8080:8080 -p 9009:9009 --name $(CONTAINER_NAME) $(IMAGE_NAME):$(TAG)

clean: ## Remove build artifacts and cache
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
