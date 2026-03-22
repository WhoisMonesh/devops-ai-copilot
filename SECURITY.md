# Security Policy

## Supported Versions

The following versions of DevOps AI Copilot receive security updates.

| Version | Supported          |
| ------- | ------------------ |
| `main`  | :white_check_mark: |
| older   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in DevOps AI Copilot, please report it responsibly.

**Please do NOT report security vulnerabilities through public GitHub Issues.**

Instead, please follow one of these methods:

### Method 1 — GitHub Private Vulnerability Reporting (Preferred)

1. Go to the **Security** tab of this repository
2. Click **"Report a vulnerability"**
3. Fill out the vulnerability report form

This allows you to report vulnerabilities privately and directly to the maintainers without making the details public.

### Method 2 — Email

Send an email to the maintainers with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fixes (optional)

## Security Updates

Security patches are applied to the `main` branch and released as part of the CI pipeline. New container images are built and pushed to GHCR automatically after each passing security scan.

Critical and high-severity vulnerabilities detected in our dependencies are tracked via Trivy scans run on every push to `main`. Scan results are published in the [Security Scan section](../README.md#security-scan) of the README.

## Container Image Security

All container images are scanned with [Trivy](https://github.com/aquasecurity/trivy) on every build:

| Image | Registry | Description |
|-------|----------|-------------|
| `devops-ai-copilot-agent` | `ghcr.io/whoismonesh/devops-ai-copilot/devops-ai-copilot-agent` | FastAPI agent backend |
| `devops-ai-copilot-gui` | `ghcr.io/whoismonesh/devops-ai-copilot/devops-ai-copilot-gui` | Streamlit frontend |
| `devops-ai-copilot-ollama` | `ghcr.io/whoismonesh/devops-ai-copilot/devops-ai-copilot-ollama` | Ollama LLM server |

### Best Practices for Running This Software

- **Keep images updated** — Always use the latest `latest` tag or pin to a specific SHA
- **Network isolation** — The agent, GUI, and Ollama containers should run in an isolated network segment
- **Credentials** — Store all integration credentials (Jenkins, Artifactory, AWS, etc.) in Kubernetes Secrets or AWS Secrets Manager — never in ConfigMaps or environment variables in plain text
- **Ollama models** — Model files are downloaded at build time; verify model integrity if using custom models
- **ServiceAccount** — In Kubernetes, the agent uses a dedicated ServiceAccount with minimal RBAC permissions required for its queries
- **TLS** — All integrations (Jenkins, Kibana, Artifactory, etc.) should be accessed over HTTPS

## Dependency Security

This project uses Python's standard dependency management. We rely on:

- **Ollama** (local LLM) — no external data transmission
- **FastAPI** — API framework
- **Streamlit** — GUI framework
- **LangChain** — LLM tool orchestration
- **kubernetes-python-client** — K8s API
- **boto3** — AWS SDK

All Python dependencies are scanned as part of the Trivy OS and library vulnerability scan. Development dependencies (test/lint) are excluded from production images via multi-stage builds.
