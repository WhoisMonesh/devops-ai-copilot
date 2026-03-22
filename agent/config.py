# agent/config.py - Central configuration
# 
# SECURITY MODEL:
#   - Non-sensitive config (URLs, region, model names, flags) -> environment variables
#   - ALL credentials (passwords, tokens, API keys, JSON certs) -> AWS Secrets Manager
#     via secrets.py (fetched at runtime, TTL-cached, IRSA-based inside EKS)
#
# Only these env vars are needed to bootstrap:
#   SECRET_ID_JENKINS, SECRET_ID_KIBANA, SECRET_ID_ARTIFACTORY,
#   SECRET_ID_NGINX, SECRET_ID_VERTEXAI, SECRET_ID_BEDROCK
#
# Supports 3 LLM providers: ollama | vertexai | bedrock  (LLM_PROVIDER env var)

import os
from dataclasses import dataclass, field

from . import secrets as _sm  # our AWS Secrets Manager module


# ---------------------------------------------------------------------------
# Env helpers (non-sensitive values only)
# ---------------------------------------------------------------------------
def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)

def _env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default

def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")

def _env_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# LLM Config  (non-sensitive params from env; secrets from Secrets Manager)
# ---------------------------------------------------------------------------
@dataclass
class LLMConfig:
    # Provider selector
    provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "ollama"))

    # ---- Provider 1: Ollama (local in-cluster, no credentials needed) ----
    ollama_base_url: str  = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://ollama:11434"))
    ollama_model: str     = field(default_factory=lambda: _env("OLLAMA_MODEL", "mistral:7b"))
    ollama_temperature: float = field(default_factory=lambda: _env_float("OLLAMA_TEMPERATURE", 0.7))
    ollama_max_tokens: int    = field(default_factory=lambda: _env_int("OLLAMA_MAX_TOKENS", 2048))
    ollama_timeout: int       = field(default_factory=lambda: _env_int("OLLAMA_TIMEOUT", 120))
    ollama_num_ctx: int       = field(default_factory=lambda: _env_int("OLLAMA_NUM_CTX", 4096))

    # ---- Provider 2: Vertex AI / Gemini ----
    # Non-sensitive: project, location, model -> env vars
    # Sensitive: service-account JSON         -> SECRET_ID_VERTEXAI in Secrets Manager
    vertexai_project: str  = field(default_factory=lambda: _env("VERTEXAI_PROJECT", ""))
    vertexai_location: str = field(default_factory=lambda: _env("VERTEXAI_LOCATION", "us-central1"))
    vertexai_model: str    = field(default_factory=lambda: _env("VERTEXAI_MODEL", "gemini-1.5-pro"))
    vertexai_temperature: float = field(default_factory=lambda: _env_float("VERTEXAI_TEMPERATURE", 0.7))
    vertexai_max_tokens: int    = field(default_factory=lambda: _env_int("VERTEXAI_MAX_TOKENS", 2048))
    # Credentials: JSON string env var (raw) OR path to mounted file
    vertexai_credentials_json: str  = field(default_factory=lambda: _env("VERTEXAI_CREDENTIALS_JSON", ""))
    vertexai_credentials_file: str  = field(default_factory=lambda: _env("GOOGLE_APPLICATION_CREDENTIALS", ""))

    # ---- Provider 3: AWS Bedrock (IRSA role-based) ----
    # Non-sensitive: region, model_id -> env vars (or Secrets Manager fallback)
    # Sensitive: static keys stored in Secrets Manager if needed
    bedrock_region: str   = field(default_factory=lambda: _env("AWS_REGION", "us-east-1"))
    bedrock_model_id: str = field(default_factory=lambda: _env("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"))
    bedrock_temperature: float = field(default_factory=lambda: _env_float("BEDROCK_TEMPERATURE", 0.7))
    bedrock_max_tokens: int    = field(default_factory=lambda: _env_int("BEDROCK_MAX_TOKENS", 2048))
    # Explicit AWS credentials (leave empty to use IRSA / instance role)
    aws_access_key_id: str     = field(default_factory=lambda: _env("AWS_ACCESS_KEY_ID", ""))
    aws_secret_access_key: str  = field(default_factory=lambda: _env("AWS_SECRET_ACCESS_KEY", ""))
    aws_session_token: str     = field(default_factory=lambda: _env("AWS_SESSION_TOKEN", ""))


# ---------------------------------------------------------------------------
# Infra Config  (URLs only - NO credentials stored here)
# ---------------------------------------------------------------------------
@dataclass
class InfraConfig:
    # Kubernetes
    k8s_in_cluster: bool = field(default_factory=lambda: _env_bool("K8S_IN_CLUSTER", True))
    k8s_namespace: str   = field(default_factory=lambda: _env("K8S_NAMESPACE", "default"))
    k8s_kubeconfig_path: str = field(default_factory=lambda: _env("KUBECONFIG", ""))

    # Service URLs (IPs or hostnames - set via env or GUI)
    # Credentials are fetched from AWS Secrets Manager at call time via secrets.py
    nginx_url: str        = field(default_factory=lambda: _env("NGINX_URL", ""))
    kibana_url: str       = field(default_factory=lambda: _env("KIBANA_URL", ""))
    elasticsearch_url: str = field(default_factory=lambda: _env("ELASTICSEARCH_URL", ""))
    jenkins_url: str      = field(default_factory=lambda: _env("JENKINS_URL", ""))
    artifactory_url: str  = field(default_factory=lambda: _env("ARTIFACTORY_URL", ""))
    prometheus_url: str   = field(default_factory=lambda: _env("PROMETHEUS_URL", "http://prometheus.monitoring.svc:9090"))
    grafana_url: str      = field(default_factory=lambda: _env("GRAFANA_URL", ""))
    grafana_api_key: str  = field(default_factory=lambda: _env("GRAFANA_API_KEY", ""))

    # Log paths (for Nginx file-based log reading when direct access is available)
    nginx_access_log: str = field(default_factory=lambda: _env("NGINX_ACCESS_LOG", "/var/log/nginx/access.log"))
    nginx_error_log: str  = field(default_factory=lambda: _env("NGINX_ERROR_LOG",  "/var/log/nginx/error.log"))


# ---------------------------------------------------------------------------
# Permission Config (operation mode)
# ---------------------------------------------------------------------------
@dataclass
class PermissionConfig:
    # Default operation mode: read_only | read_write | safe_mode
    default_mode: str = field(default_factory=lambda: _env("DEFAULT_OPERATION_MODE", "read_write"))
    # Enable audit logging
    audit_enabled: bool = field(default_factory=lambda: _env_bool("AUDIT_ENABLED", True))
    # Path for audit logs
    audit_log_path: str = field(default_factory=lambda: _env("AUDIT_LOG_PATH", "/var/log/devops-ai/audit.log"))


# ---------------------------------------------------------------------------
# App Config
# ---------------------------------------------------------------------------
@dataclass
class AppConfig:
    host: str      = field(default_factory=lambda: _env("APP_HOST", "0.0.0.0"))
    port: int      = field(default_factory=lambda: _env_int("APP_PORT", 8000))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "info"))
    reload: bool   = field(default_factory=lambda: _env_bool("APP_RELOAD", False))


# ---------------------------------------------------------------------------
# Root config singleton
# ---------------------------------------------------------------------------
@dataclass
class Config:
    llm: LLMConfig    = field(default_factory=LLMConfig)
    infra: InfraConfig = field(default_factory=InfraConfig)
    app: AppConfig    = field(default_factory=AppConfig)
    permissions: PermissionConfig = field(default_factory=PermissionConfig)

    def reload(self):
        """Hot-reload: re-read env vars + flush Secrets Manager cache."""
        self.llm   = LLMConfig()
        self.infra = InfraConfig()
        self.app   = AppConfig()
        self.permissions = PermissionConfig()
        _sm.invalidate()  # flush all cached secrets so next call re-fetches

    def to_dict(self) -> dict:
        """Serialize to dict for /config API - never exposes credential values."""
        return {
            # LLM
            "llm_provider": self.llm.provider,
            "ollama_base_url": self.llm.ollama_base_url,
            "ollama_model": self.llm.ollama_model,
            "ollama_temperature": self.llm.ollama_temperature,
            "ollama_max_tokens": self.llm.ollama_max_tokens,
            "ollama_timeout": self.llm.ollama_timeout,
            "vertexai_project": self.llm.vertexai_project,
            "vertexai_location": self.llm.vertexai_location,
            "vertexai_model": self.llm.vertexai_model,
            "vertexai_temperature": self.llm.vertexai_temperature,
            "vertexai_max_tokens": self.llm.vertexai_max_tokens,
            "bedrock_region": self.llm.bedrock_region,
            "bedrock_model_id": self.llm.bedrock_model_id,
            "bedrock_temperature": self.llm.bedrock_temperature,
            "bedrock_max_tokens": self.llm.bedrock_max_tokens,
            # Infra URLs (safe to show)
            "nginx_url": self.infra.nginx_url,
            "kibana_url": self.infra.kibana_url,
            "elasticsearch_url": self.infra.elasticsearch_url,
            "jenkins_url": self.infra.jenkins_url,
            "artifactory_url": self.infra.artifactory_url,
            "prometheus_url": self.infra.prometheus_url,
            "grafana_url": self.infra.grafana_url,
            "grafana_api_key": self.infra.grafana_api_key,
            "k8s_in_cluster": self.infra.k8s_in_cluster,
            "k8s_namespace": self.infra.k8s_namespace,
            "k8s_kubeconfig_path": self.infra.k8s_kubeconfig_path,
            # Permissions
            "default_operation_mode": self.permissions.default_mode,
            "audit_enabled": self.permissions.audit_enabled,
            # Secret IDs (ARN/name only - not the credential values!)
            "secret_id_jenkins": _sm.jenkins.is_configured(),
            "secret_id_kibana": _sm.kibana.is_configured(),
            "secret_id_artifactory": _sm.artifactory.is_configured(),
            "secret_id_nginx": _sm.nginx.is_configured(),
            "secret_id_vertexai": _sm.vertexai.is_configured(),
            "secret_id_bedrock": _sm.bedrock.is_configured(),
        }


# Global singleton
config = Config()
