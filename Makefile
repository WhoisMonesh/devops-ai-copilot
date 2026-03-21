.PHONY: help install dev agent gui docker-up docker-down lint test clean build-images push-images

PYTHON  ?= python3
PIP     ?= pip3
DOCKER  ?= docker
DC      ?= docker compose
IMG_AGENT   := ghcr.io/$(shell gh auth token 2>/dev/null && echo $(shell gh repo view --json owner --jq .owner.login 2>/dev/null || echo WHOISMONESH))/devops-ai-copilot/devops-ai-copilot-agent
IMG_GUI     := ghcr.io/$(shell gh auth token 2>/dev/null && echo $(shell gh repo view --json owner --jq .owner.login 2>/dev/null || echo WHOISMONESH))/devops-ai-copilot/devops-ai-copilot-gui
IMG_OLLAMA  := ghcr.io/$(shell gh auth token 2>/dev/null && echo $(shell gh repo view --json owner --jq .owner.login 2>/dev/null || echo WHOISMONESH))/devops-ai-copilot/devops-ai-copilot-ollama

## help: Show this help
help:
	@grep -E '^##' $(MAKEFILE_LIST) | sed 's/## //' | column -t -s ':'

## install: Install all Python dependencies
install:
	$(PIP) install -r agent/requirements.txt
	$(PIP) install -r gui/requirements.txt

## dev: Start agent + GUI in dev mode (requires .env)
dev: agent-dev gui-dev

## agent-dev: Start FastAPI agent in reload mode
agent-dev:
	@echo "Starting FastAPI agent on :8000 ..."
	cd agent && $(PYTHON) -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

## gui-dev: Start Streamlit GUI
gui-dev:
	@echo "Starting Streamlit GUI on :8501 ..."
	cd gui && $(PYTHON) -m streamlit run app.py --server.port 8501

## docker-up: Build and start all services via Docker Compose
docker-up:
	$(DC) -f deploy/docker-compose.yml up --build -d
	@echo "Agent: http://localhost:8000  GUI: http://localhost:8501  Ollama: http://localhost:11434"

## docker-down: Stop all Docker Compose services
docker-down:
	$(DC) -f deploy/docker-compose.yml down

## docker-build: Build all Docker images
docker-build:
	$(DC) -f deploy/docker-compose.yml build

## build-images: Build all 3 container images locally (agent, gui, ollama)
build-images:
	$(DOCKER) build -t devops-ai-copilot-agent:local -f deploy/Dockerfile.agent .
	$(DOCKER) build -t devops-ai-copilot-gui:local -f gui/Dockerfile gui/
	$(DOCKER) build -t devops-ai-copilot-ollama:local -f deploy/Dockerfile.ollama deploy/

## push-images: Push images to GHCR (requires gh auth and IMAGE_PREFIX set)
push-images:
	$(DOCKER) push $(IMG_AGENT):latest
	$(DOCKER) push $(IMG_GUI):latest
	$(DOCKER) push $(IMG_OLLAMA):latest

## lint: Run ruff linter
lint:
	$(PYTHON) -m ruff check agent/ gui/

## format: Auto-format code with ruff
format:
	$(PYTHON) -m ruff format agent/ gui/

## test: Run pytest
test:
	$(PYTHON) -m pytest tests/ -v

## clean: Remove .pyc files and __pycache__ dirs
clean:
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

## k8s-apply: Apply Kubernetes manifests
k8s-apply:
	kubectl apply -f deploy/k8s/

## k8s-delete: Delete Kubernetes resources
k8s-delete:
	kubectl delete -f deploy/k8s/

## logs-agent: Tail agent logs (docker compose)
logs-agent:
	$(DC) -f deploy/docker-compose.yml logs -f agent

## logs-gui: Tail GUI logs (docker compose)
logs-gui:
	$(DC) -f deploy/docker-compose.yml logs -f gui

## logs-ollama: Tail Ollama logs (docker compose)
logs-ollama:
	$(DC) -f deploy/docker-compose.yml logs -f ollama
