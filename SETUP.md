# DevOps AI Copilot - Complete Setup Guide

A comprehensive guide to configure, deploy, and operate the DevOps AI Copilot from scratch to advanced production setups.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start (Docker Compose)](#quick-start-docker-compose)
4. [Architecture](#architecture)
5. [Environment Configuration](#environment-configuration)
6. [AWS Secrets Manager Setup](#aws-secrets-manager-setup)
7. [Kubernetes Deployment](#kubernetes-deployment)
8. [Local Development Setup](#local-development-setup)
9. [LLM Provider Configuration](#llm-provider-configuration)
10. [Tool Integrations](#tool-integrations)
11. [Security Configuration](#security-configuration)
12. [Monitoring and Observability](#monitoring-and-observability)
13. [Troubleshooting](#troubleshooting)
14. [Advanced Configuration](#advanced-configuration)

---

## Overview

**DevOps AI Copilot** is a self-hosted AI assistant that runs inside your infrastructure and connects to your DevOps tools. It uses local LLMs (via Ollama) or cloud providers (Vertex AI, AWS Bedrock) to understand natural language queries and translates them into targeted API calls.

### Key Features

- **Zero data leaves your cluster** - All processing happens locally
- **17 tools across 14 integrations** - Kubernetes, Jenkins, Prometheus, Grafana, and more
- **Hot-reload configuration** - Change settings without restarts
- **Kubernetes-native** - Full RBAC, IRSA, and observability support
- **Multiple LLM providers** - Ollama, Vertex AI, AWS Bedrock
- **Permission modes** - Read-only, read-write, and safe mode with audit logging

---

## Prerequisites

### For All Deployments

| Requirement | Version | Description |
|-------------|---------|-------------|
| Docker | 24.0+ | Container runtime |
| Docker Compose | 2.20+ | Multi-container orchestration |
| Git | 2.40+ | Source control |
| OpenSSL | 3.0+ | For generating API keys |

### For Kubernetes Deployment

| Requirement | Version | Description |
|-------------|---------|-------------|
| Kubernetes | 1.28+ | Container orchestration |
| kubectl | 1.28+ | K8s CLI |
| AWS CLI | 2.15+ | AWS management (for EKS) |
| Helm | 3.14+ | Package manager (optional) |

### For Local Development

| Requirement | Version | Description |
|-------------|---------|-------------|
| Python | 3.12+ | Runtime |
| uv | 0.1+ | Package manager |
| Ollama | 0.1+ | Local LLM (or cloud provider) |

---

## Quick Start (Docker Compose)

### Step 1: Clone the Repository

```bash
git clone https://github.com/WhoisMonesh/devops-ai-copilot.git
cd devops-ai-copilot
```

### Step 2: Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your configuration. See [Environment Configuration](#environment-configuration) for details.

### Step 3: Start Services

```bash
docker compose -f deploy/docker-compose.yml up -d
```

### Step 4: Access the Application

| Service | URL | Description |
|---------|-----|-------------|
| GUI | http://localhost:8501 | Streamlit chat interface |
| Agent API | http://localhost:8000 | FastAPI backend |
| Ollama | http://localhost:11434 | LLM API |

### Step 5: Verify Installation

```bash
# Check service health
curl http://localhost:8000/health

# Check available tools
curl http://localhost:8000/tools
```

---

## Architecture

### Container Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose / K8s                     │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │     GUI      │  │    Agent     │  │   Ollama (LLM)    │  │
│  │  (Streamlit) │──│  (FastAPI)   │──│  Qwen2.5 / Mistral│  │
│  │   Port 8501  │  │   Port 8000 │  │    Port 11434     │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Service Responsibilities

| Service | Technology | Role |
|---------|------------|------|
| **GUI** | Streamlit | Chat interface, configuration, tool explorer |
| **Agent** | FastAPI + LangChain | LLM orchestration, tool execution, caching |
| **Ollama** | Ollama + LLM | Local inference engine |

### Directory Structure

```
devops-ai-copilot/
├── agent/                    # FastAPI backend
│   ├── main.py             # API endpoints
│   ├── orchestrator.py      # LangChain ReAct agent
│   ├── llm_client.py       # Multi-provider LLM client
│   ├── config.py           # Hot-reload configuration
│   ├── secrets.py          # AWS Secrets Manager integration
│   ├── cache.py            # Query and result caching
│   ├── permissions.py      # Operation modes
│   ├── metrics.py          # Prometheus metrics
│   ├── observability.py    # Audit logging
│   ├── knowledge_base.py   # RAG knowledge base
│   └── tools/              # 17 tool implementations
├── gui/                     # Streamlit frontend
│   └── app.py              # Chat, config, tools explorer
├── deploy/
│   ├── docker-compose.yml  # Local deployment
│   ├── Dockerfile.agent    # Agent container
│   ├── Dockerfile.ollama   # Ollama container
│   └── k8s/                # Kubernetes manifests
├── tests/                  # pytest test suite
├── Makefile               # Development commands
└── .env.example           # Environment template
```

---

## Environment Configuration

### Essential Variables

Create your `.env` file from the example:

```bash
cp .env.example .env
```

#### LLM Provider Configuration

**Option A: Ollama (Local - Recommended for DevOps)**

```bash
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=mistral
OLLAMA_TIMEOUT=120
```

**Option B: Google Vertex AI**

```bash
LLM_PROVIDER=vertexai
VERTEXAI_PROJECT=my-gcp-project
VERTEXAI_LOCATION=us-central1
VERTEXAI_MODEL=gemini-1.5-pro
```

**Option C: AWS Bedrock**

```bash
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL=anthropic.claude-3-sonnet
```

#### Service URLs

```bash
# Kubernetes
K8S_IN_CLUSTER=true
K8S_NAMESPACE=production

# Jenkins
JENKINS_URL=https://jenkins.internal.io

# Kibana / Elasticsearch
KIBANA_URL=https://kibana.internal.io
ELASTICSEARCH_URL=https://elasticsearch.internal.io

# Prometheus & Grafana
PROMETHEUS_URL=http://prometheus.monitoring:9090
GRAFANA_URL=https://grafana.internal.io
GRAFANA_API_KEY=glp_xxxxxxxxxxxxx

# Artifactory
ARTIFACTORY_URL=https://artifactory.internal.io

# Nginx Logs
NGINX_ACCESS_LOG=/var/log/nginx/access.log
NGINX_ERROR_LOG=/var/log/nginx/error.log
```

#### Security

```bash
# Generate API key
openssl rand -hex 32

API_KEY=your_generated_api_key_here
```

#### GUI Configuration

```bash
AGENT_API_URL=http://localhost:8000
AGENT_API_KEY=your_generated_api_key_here
```

#### Caching

```bash
SECRET_CACHE_TTL=300
```

### AWS Secrets Manager Variables

```bash
SECRET_ID_JENKINS=devops-copilot/jenkins
SECRET_ID_KIBANA=devops-copilot/kibana
SECRET_ID_ARTIFACTORY=devops-copilot/artifactory
SECRET_ID_NGINX=devops-copilot/nginx
```

---

## AWS Secrets Manager Setup

All credentials are stored as JSON in AWS Secrets Manager for secure access.

### Creating Secrets

#### Jenkins Credentials

```bash
aws secretsmanager create-secret \
  --name devops-copilot/jenkins \
  --secret-string '{"url":"https://jenkins.internal.io","username":"admin","api_token":"your_api_token"}'
```

#### Kibana Credentials

```bash
aws secretsmanager create-secret \
  --name devops-copilot/kibana \
  --secret-string '{"url":"https://kibana.internal.io","username":"elastic","password":"your_password","elasticsearch_url":"https://elasticsearch.internal.io"}'
```

#### Artifactory Credentials

```bash
aws secretsmanager create-secret \
  --name devops-copilot/artifactory \
  --secret-string '{"url":"https://artifactory.internal.io","username":"admin","api_key":"your_api_key"}'
```

#### Nginx Configuration

```bash
aws secretsmanager create-secret \
  --name devops-copilot/nginx \
  --secret-string '{"url":"https://nginx.internal.io","access_log":"/var/log/nginx/access.log","error_log":"/var/log/nginx/error.log"}'
```

### IRSA (IAM Roles for Service Accounts) for EKS

For EKS clusters, use IRSA to grant pods access to Secrets Manager:

```yaml
# Add to your pod annotation
apiVersion: v1
kind: ServiceAccount
metadata:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/devops-copilot-secrets-reader
```

Create the IAM role:

```bash
# Create IAM role
aws iam create-role \
  --role-name devops-copilot-secrets-reader \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::123456789:role/eks-node-role"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach secrets policy
aws iam put-role-policy \
  --role-name devops-copilot-secrets-reader \
  --policy-name SecretsReader \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": ["arn:aws:secretsmanager:us-east-1:123456789:secret:devops-copilot/*"]
    }]
  }'
```

---

## Kubernetes Deployment

### Namespace and RBAC

```bash
# Create namespace
kubectl create namespace devops-copilot

# Apply RBAC and secrets
kubectl apply -f deploy/k8s/secrets.yaml

# Apply configuration
kubectl apply -f deploy/k8s/configmap.yaml
```

### Deploy Ollama

```bash
kubectl apply -f deploy/k8s/ollama-deployment.yaml
```

### Deploy Agent

```bash
kubectl apply -f deploy/k8s/agent-deployment.yaml
```

### Deploy GUI

```bash
kubectl apply -f deploy/k8s/gui-deployment.yaml
```

### Verify Deployment

```bash
# Check pods
kubectl get pods -n devops-copilot

# View logs
kubectl logs -n devops-copilot -l app=agent
kubectl logs -n devops-copilot -l app=gui
kubectl logs -n devops-copilot -l app=ollama

# Port-forward for local access
kubectl port-forward -n devops-copilot svc/agent 8000:8000
kubectl port-forward -n devops-copilot svc/gui 8501:8501
```

### Kubernetes Secrets Template

Edit `deploy/k8s/secrets.yaml` with your base64-encoded credentials:

```bash
# Encode credentials
echo -n '{"username":"admin","api_token":"token"}' | base64
```

---

## Local Development Setup

### Install Dependencies

```bash
make install
```

### Run with Ollama

First, install and start Ollama:

```bash
# Install Ollama (macOS)
brew install ollama

# Start Ollama service
ollama serve

# Pull a model (in another terminal)
ollama pull mistral
```

### Start Agent

```bash
make dev
```

### Start GUI (in another terminal)

```bash
make gui
```

### Available Make Commands

| Command | Description |
|---------|-------------|
| `make install` | Install Python dependencies |
| `make dev` | Start agent in development mode |
| `make gui` | Start GUI in development mode |
| `make test` | Run pytest suite |
| `make lint` | Run ruff linter |
| `make format` | Auto-format code |
| `make docker-up` | Start via Docker Compose |
| `make docker-down` | Stop Docker Compose |
| `make docker-build` | Build container images |
| `make k8s-apply` | Apply K8s manifests |
| `make k8s-delete` | Delete K8s resources |
| `make logs-agent` | Tail agent logs |
| `make logs-gui` | Tail GUI logs |
| `make logs-ollama` | Tail Ollama logs |

---

## LLM Provider Configuration

### Ollama (Local)

Ollama runs models locally, ensuring no data leaves your infrastructure.

#### Supported Models

| Model | Size | VRAM | Best For |
|-------|------|------|----------|
| mistral | 7B | 8GB | General DevOps tasks |
| qwen2.5:3b | 3B | 4GB | Lightweight tasks, faster responses |
| llama3.2 | 3B | 4GB | Alternative lightweight option |
| llama3.1:8b | 8B | 12GB | More capable, slower |

#### Pull a Model

```bash
ollama pull mistral
ollama pull qwen2.5:3b
```

#### Configure Multiple Models

```bash
OLLAMA_MODEL=mistral
```

The agent can use different models for different tasks.

### Vertex AI (Google Cloud)

```bash
LLM_PROVIDER=vertexai
VERTEXAI_PROJECT=my-gcp-project
VERTEXAI_LOCATION=us-central1
VERTEXAI_MODEL=gemini-1.5-pro
```

Set up authentication:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project my-gcp-project
```

### AWS Bedrock

```bash
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL=anthropic.claude-3-sonnet-20240229-v1:0
```

Configure AWS credentials:

```bash
aws configure
```

---

## Tool Integrations

### Kubernetes Tools

**Prerequisites:**
- `KUBECONFIG` or in-cluster service account
- `K8S_IN_CLUSTER=true` for Pod-level access
- `K8S_NAMESPACE=default` for default namespace

**Capabilities:**
- List/get pods, deployments, services
- Get pod logs
- Describe resources
- Scale deployments
- Delete pods

### Jenkins Tools

**Prerequisites:**
- Jenkins URL and credentials in AWS Secrets Manager

**Capabilities:**
- List jobs
- Get build status
- Trigger builds
- View console output

### Prometheus Tools

**Prerequisites:**
- Prometheus URL (must be reachable from agent)

**Capabilities:**
- Execute PromQL queries
- List alerts
- Get alert states

### Grafana Tools

**Prerequisites:**
- Grafana URL and API key

**Capabilities:**
- List dashboards
- Get dashboard data
- List alerts
- Query panels

### Kibana/Elasticsearch Tools

**Prerequisites:**
- Kibana/ES credentials in AWS Secrets Manager

**Capabilities:**
- Search logs
- Get index patterns
- View dashboards

### SSL/TLS Tools

**Prerequisites:**
- Domain access for checks

**Capabilities:**
- Check SSL certificate expiry
- DNS lookups
- HTTP header inspection

### AWS Tools

**Prerequisites:**
- AWS credentials or IRSA role

**Capabilities:**
- List EC2 instances
- List ELB targets
- List Auto Scaling Groups

---

## Security Configuration

### Permission Modes

The agent supports three operation modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| `read_only` | Only read operations | Production monitoring |
| `read_write` | Read and write operations | Full automation |
| `safe_mode` | Blocked destructive operations | CI/CD pipelines |

### Rate Limiting

Default: 60 requests per minute per IP

Configure in `.env`:

```bash
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW=60
```

### API Key Authentication

Generate a secure API key:

```bash
openssl rand -hex 32
```

Use for:
- GUI to Agent communication
- External client authentication

### Audit Logging

All operations are logged with:
- Timestamp
- User/IP
- Operation type
- Tool used
- Result status

Logs available at:
```bash
kubectl logs -n devops-copilot -l app=agent | grep AUDIT
```

---

## Monitoring and Observability

### Prometheus Metrics

Metrics endpoint: `http://localhost:8000/metrics`

Available metrics:
- `agent_requests_total` - Total requests by endpoint
- `agent_request_duration_seconds` - Request latency
- `agent_tool_invocations_total` - Tool usage count
- `agent_cache_hits_total` - Cache hit rate
- `agent_errors_total` - Error count

### Health Checks

```bash
# Liveness probe
curl http://localhost:8000/health

# Readiness probe
curl http://localhost:8000/ready
```

### Structured Logging

Logs are output in JSON format for log aggregation:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "message": "Query processed",
  "request_id": "uuid",
  "tool": "kubernetes",
  "duration_ms": 234
}
```

---

## Troubleshooting

### Common Issues

#### Ollama Not Responding

```bash
# Check Ollama status
curl http://localhost:11434/api/version

# Pull model
ollama pull mistral

# Check model list
ollama list
```

#### Authentication Failures

1. Verify AWS Secrets Manager credentials
2. Check IRSA annotations on service account
3. Validate API keys in `.env`

#### Kubernetes Connection Issues

```bash
# Verify kubeconfig
kubectl config current-context

# Test cluster access
kubectl auth can-i get pods --namespace=default
```

#### Container Crashes

```bash
# View crash logs
kubectl logs -n devops-copilot <pod-name> --previous

# Describe pod
kubectl describe pod -n devops-copilot <pod-name>
```

### Debug Mode

Enable verbose logging:

```bash
LOG_LEVEL=DEBUG
```

### Reset Configuration

To reset to defaults:

```bash
# Stop services
make docker-down

# Remove volumes
docker compose -f deploy/docker-compose.yml down -v

# Restart
make docker-up
```

---

## Advanced Configuration

### Query Caching

Configure cache TTL:

```bash
SECRET_CACHE_TTL=300  # 5 minutes (default)
```

### Hot Configuration Reload

The agent supports runtime configuration changes via the API:

```bash
# Update service URL
curl -X POST http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{"key": "JENKINS_URL", "value": "https://new-jenkins.internal.io"}'
```

### Knowledge Base (RAG)

Configure vector store for runbooks and SOPs:

```bash
# Knowledge base directory (local filesystem)
KNOWLEDGE_BASE_PATH=/var/lib/devops-copilot/knowledge

# Embedding model
KNOWLEDGE_BASE_EMBEDDING_MODEL=nomic-embed-text
```

### Multi-Model Routing

Configure different models for different task types:

```bash
# Default model
OLLAMA_MODEL=mistral

# Fast model for simple queries
OLLAMA_FAST_MODEL=qwen2.5:3b
```

### Resource Limits

#### Kubernetes Resources

Edit `deploy/k8s/agent-deployment.yaml`:

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "2Gi"
    cpu: "1000m"
```

### Custom Tools

Add custom tools by implementing the `Tool` interface:

```python
from langchain_core.tools import tool

@tool
def custom_tool(query: str) -> str:
    """Description of what the tool does."""
    # Implementation
    return result
```

### TLS Configuration

For production, always use TLS:

```bash
# Agent API
UVICORN_SSL_KEYFILE=/path/to/key.pem
UVICORN_SSL_CERTFILE=/path/to/cert.pem
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Clone repository
- [ ] Configure `.env` file
- [ ] Set up AWS Secrets Manager
- [ ] Configure TLS certificates
- [ ] Set up Kubernetes cluster (if applicable)

### Deployment

- [ ] Build container images
- [ ] Push to container registry
- [ ] Apply Kubernetes manifests
- [ ] Verify all pods are running
- [ ] Check health endpoints
- [ ] Test with sample queries

### Post-Deployment

- [ ] Configure monitoring/alerting
- [ ] Set up log aggregation
- [ ] Configure backup strategy
- [ ] Document emergency contacts
- [ ] Train team on usage

---

## Support

For issues and feature requests:
- GitHub Issues: https://github.com/WhoisMonesh/devops-ai-copilot/issues
- Documentation: https://github.com/WhoisMonesh/devops-ai-copilot#readme

---

## License

See [LICENSE](LICENSE) file for details.
