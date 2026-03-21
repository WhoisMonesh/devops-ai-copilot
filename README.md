# DevOps AI Copilot

> AI-powered natural language interface for your entire DevOps infrastructure.
> Ask questions in plain English - get instant answers from Kubernetes, Jenkins, Kibana, Artifactory, Nginx and more.

![CI](https://github.com/WhoisMonesh/devops-ai-copilot/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/github/license/WhoisMonesh/devops-ai-copilot)
![Python](https://img.shields.io/badge/python-3.11-blue)



---

## What is this?

DevOps AI Copilot is a self-hosted AI assistant that runs **inside your Kubernetes cluster** and connects to all your infrastructure tools. It uses **Ollama** (local LLM - no data leaves your cluster) to answer natural language questions about your infra.

**Example queries:**
- `Show me Nginx 5xx errors from the last hour`
- `What pods are in CrashLoopBackOff in production?`
- `List failed Jenkins jobs today`
- `Is the latest Docker image in Artifactory healthy?`
- `Show Kibana alerts for high CPU`

---

## Architecture

```
 +------------------+     +------------------+     +------------------+
 |  GUI Container   | --> |  Agent Container | --> | Ollama Container |
 |  Streamlit :8501 |     |  FastAPI  :8000  |     | Local LLM :11434|
 +------------------+     +--------+---------+     +------------------+
                                   |
              +--------------------+--------------------+--------------------+
              |          |         |          |         |                |
            Nginx     Kibana   Jenkins   Artifactory  K8s API     Prometheus
           (logs)   (alerts)   (jobs)   (artifacts) (pods/nodes)   (metrics)
```

![Architecture](Arch.png)

**3 Containers:**
| Container | Image | Port | Role |
|-----------|-------|------|------|
| `agent` | `ghcr.io/whoismonesh/devops-ai-copilot/agent` | 8000 | FastAPI brain - orchestrates tools + LLM (K8s, Jenkins, Kibana, Artifactory, Nginx, Prometheus) |
| `gui` | `ghcr.io/whoismonesh/devops-ai-copilot/gui` | 8501 | Streamlit UI - chat + config dashboard |
| `ollama` | `ollama/ollama` | 11434 | Local AI model server (Mistral default) |

---

## Features

- **Natural language queries** over all your DevOps tools
- **In-cluster deployment** - agent uses K8s ServiceAccount (no kubeconfig needed)
- **Local AI** - Ollama runs inside the cluster, zero data leakage
- **Hot-reload config** - change service URLs/credentials via GUI without restart
- **6 built-in tools**: Kubernetes, Jenkins, Kibana, Artifactory, Nginx, Prometheus
- **Extensible** - add new tools by dropping a file in `agent/tools/`
- **Streamlit GUI** with Chat, Configuration, Tools, and Dashboard pages
- **CI/CD** - GitHub Actions builds & pushes images, runs Trivy security scans
- **EKS/K8s ready** - full RBAC, ServiceAccount, PVC manifests included

---

## Quick Start (Docker Compose)

```bash
# 1. Clone the repo
git clone https://github.com/WhoisMonesh/devops-ai-copilot.git
cd devops-ai-copilot

# 2. Copy and fill in your config
cp .env.example .env
# Edit .env with your service URLs and credentials

# 3. Start all 3 containers
docker compose -f deploy/docker-compose.yml up -d

# 4. Pull the AI model (first time only)
docker exec ollama ollama pull mistral

# 5. Open the GUI
open http://localhost:8501
```

---

## Deploy to Kubernetes / EKS

```bash
# 1. Create namespace + RBAC + secrets
kubectl apply -f deploy/k8s/secrets.yaml

# 2. Edit secrets.yaml with your base64-encoded credentials
# kubectl create secret generic devops-copilot-secrets \
#   --from-env-file=.env -n devops-copilot

# 3. Apply ConfigMap
kubectl apply -f deploy/k8s/configmap.yaml

# 4. Deploy Ollama (local AI) + PVC
kubectl apply -f deploy/k8s/ollama-deployment.yaml

# 5. Deploy Agent
kubectl apply -f deploy/k8s/agent-deployment.yaml

# 6. Deploy GUI
kubectl apply -f deploy/k8s/gui-deployment.yaml

# 7. Check status
kubectl get pods -n devops-copilot
```

---

## Configuration

All configuration is available via:
1. **GUI** - open `http://<node-ip>:8501` → Configuration page → Save
2. **Environment variables** - see `.env.example` for all options
3. **K8s ConfigMap** - edit `deploy/k8s/configmap.yaml`

### Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama service URL |
| `OLLAMA_MODEL` | `mistral` | Model to use (mistral/llama2/codellama) |
| `NGINX_URL` | - | Nginx stub_status or log URL |
| `KIBANA_URL` | - | Kibana API URL |
| `JENKINS_URL` | - | Jenkins URL |
| `ARTIFACTORY_URL` | - | JFrog Artifactory URL |
| `PROMETHEUS_URL` | `http://prometheus.monitoring.svc:9090` | Prometheus service URL |
| `K8S_IN_CLUSTER` | `true` | Use in-cluster ServiceAccount auth |
| `K8S_NAMESPACE` | `default` | Default namespace to query |

---

## Project Structure

```
devops-ai-copilot/
├── agent/                    # FastAPI AI agent backend
│   ├── main.py               # API entry point (/query, /health, /config, /tools)
│   ├── orchestrator.py       # LLM + tool orchestration engine
│   ├── ollama_client.py      # Ollama HTTP client + model management
│   ├── config.py             # Central config (env + hot-reload)
│   ├── requirements.txt
│   └── tools/
│       ├── k8s_tool.py       # Kubernetes pods/nodes/deployments
│       ├── jenkins_tool.py   # Jenkins jobs, builds, logs
│       ├── kibana_tool.py    # Kibana alerts, search, dashboards
│       ├── artifactory_tool.py # JFrog artifacts, repos
│       ├── nginx_tool.py     # Nginx access/error logs
│       └── prometheus_tools.py # Prometheus metrics queries
├── gui/                      # Streamlit frontend
│   ├── app.py                # Chat, Config, Tools, Dashboard pages
│   ├── requirements.txt
│   └── Dockerfile
├── deploy/
│   ├── Dockerfile.agent      # Multi-stage agent container
│   ├── docker-compose.yml    # 3-container local setup
│   └── k8s/
│       ├── secrets.yaml      # RBAC + ServiceAccount + Secrets template
│       ├── configmap.yaml    # Non-sensitive config
│       ├── agent-deployment.yaml
│       ├── gui-deployment.yaml
│       └── ollama-deployment.yaml  # Ollama + PVC (GPU-ready)
├── .github/workflows/
│   └── ci.yml                # Lint -> Test -> Build -> Push -> Trivy scan
├── .env.example
├── Makefile                  # make dev / make docker-up / make k8s-deploy
└── README.md
```

---

## Development

```bash
# Install dependencies
make install

# Run agent locally (needs Ollama running)
make dev

# Run GUI locally
make gui

# Build Docker images
make docker-build

# Full stack with Docker Compose
make docker-up

# Lint
make lint

# Tests
make test
```

---

## Adding New Tools

Create `agent/tools/mytool_tool.py`:

```python
from .base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Query MyService for X, Y, Z"

    def run(self, query: str) -> str:
        # your logic here
        return "result"
```

The tool is auto-discovered on next startup (hot-reload supported).

---

## License

MIT - see [LICENSE](LICENSE)
