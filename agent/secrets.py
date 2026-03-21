# agent/secrets.py
# AWS Secrets Manager client - single source of truth for ALL credentials
#
# Design:
#   - All secrets are stored in AWS Secrets Manager as JSON blobs
#   - This module fetches + caches them (TTL-based, default 5 min)
#   - Works with IRSA (no static keys inside EKS) or explicit keys for local dev
#   - Only ONE env var needed per secret: the Secret ARN or Name
#
# Secret naming convention (store in Secrets Manager):
#   devops-copilot/jenkins      -> {"url":"...","username":"...","api_token":"..."}
#   devops-copilot/kibana       -> {"url":"...","username":"...","password":"...","elasticsearch_url":"..."}
#   devops-copilot/artifactory  -> {"url":"...","username":"...","api_key":"..."}
#   devops-copilot/nginx        -> {"url":"...","access_log":"...","error_log":"..."}
#   devops-copilot/llm/vertexai -> {"project":"...","location":"...","credentials_json":"{...}"}
#   devops-copilot/llm/bedrock  -> {"region":"...","model_id":"..."}
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache: {secret_id -> (fetched_at_epoch, data_dict)}
# ---------------------------------------------------------------------------
_cache: Dict[str, tuple] = {}
CACHE_TTL_SECONDS: int = int(os.getenv("SECRETS_CACHE_TTL", "300"))  # 5 min default

# AWS region - use the same as Bedrock region, or set independently
AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")


def _boto_client():
    """Create a boto3 secretsmanager client.
    Uses IRSA inside EKS (no creds needed) or explicit keys for local dev."""
    try:
        import boto3
    except ImportError:
        raise ImportError("boto3 is required. Add it to requirements.txt.")
    kwargs: dict = {"region_name": AWS_REGION}
    # Only pass explicit creds if set (local dev / non-IRSA)
    key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if key_id and secret:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
        session_token = os.getenv("AWS_SESSION_TOKEN", "")
        if session_token:
            kwargs["aws_session_token"] = session_token
    return boto3.client("secretsmanager", **kwargs)


def get_secret(secret_id: str, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Fetch a secret from AWS Secrets Manager and return it as a dict.

    Args:
        secret_id     - Secret ARN or friendly name (e.g. 'devops-copilot/jenkins')
        force_refresh - bypass cache and re-fetch immediately

    Returns:
        dict with the secret key-value pairs

    Raises:
        ValueError  - if secret_id is empty
        RuntimeError - if AWS call fails
    """
    if not secret_id:
        raise ValueError("secret_id must not be empty.")
    now = time.monotonic()
    # Return from cache if still fresh
    if not force_refresh and secret_id in _cache:
        fetched_at, data = _cache[secret_id]
        if now - fetched_at < CACHE_TTL_SECONDS:
            logger.debug("[Secrets] cache hit for '%s'", secret_id)
            return data
    logger.info(
        "[Secrets] fetching '%s' from AWS Secrets Manager (region=%s)",
        secret_id,
        AWS_REGION,
    )
    try:
        client = _boto_client()
        response = client.get_secret_value(SecretId=secret_id)
        raw = response.get("SecretString") or ""
        if not raw:
            # Binary secret - decode
            import base64
            raw = base64.b64decode(response["SecretBinary"]).decode("utf-8")
        data = json.loads(raw)
        _cache[secret_id] = (now, data)
        logger.info("[Secrets] successfully fetched '%s'", secret_id)
        return data
    except Exception as e:
        logger.error("[Secrets] failed to fetch '%s': %s", secret_id, e)
        raise RuntimeError(f"Failed to fetch secret '{secret_id}': {e}") from e


def get_secret_value(secret_id: str, key: str, default: str = "") -> str:
    """
    Convenience: fetch a single key from a Secrets Manager secret.

    Args:
        secret_id - Secret ARN or name
        key       - key inside the JSON secret blob
        default   - returned if key is missing or secret fetch fails
    """
    try:
        return str(get_secret(secret_id).get(key, default))
    except Exception:
        return default


def invalidate(secret_id: Optional[str] = None) -> None:
    """
    Invalidate cache entries.
    - Pass a secret_id to invalidate only that entry.
    - Pass None to flush the entire cache (e.g. on config hot-reload).
    """
    if secret_id:
        _cache.pop(secret_id, None)
        logger.info("[Secrets] cache invalidated for '%s'", secret_id)
    else:
        _cache.clear()
        logger.info("[Secrets] entire secrets cache flushed")


# ---------------------------------------------------------------------------
# Named secret helpers - each maps to a specific Secrets Manager secret
# Env var controls which secret ARN/name to use per service.
# ---------------------------------------------------------------------------
class _ServiceSecrets:
    """
    Helper: resolves a service's secret_id from env, then fetches on demand.
    Falls back gracefully if secret not configured.
    """

    def __init__(self, env_var: str, description: str) -> None:
        self._env_var = env_var
        self._description = description

    @property
    def _secret_id(self) -> str:
        return os.getenv(self._env_var, "")

    def get(self, key: str, default: str = "") -> str:
        """Fetch key from this service's secret. Returns default on any error."""
        sid = self._secret_id
        if not sid:
            logger.debug(
                "[Secrets] %s: env var '%s' not set, returning default for key '%s'",
                self._description,
                self._env_var,
                key,
            )
            return default
        return get_secret_value(sid, key, default)

    def all(self) -> dict:
        """Return full secret dict. Returns {} on any error."""
        sid = self._secret_id
        if not sid:
            return {}
        try:
            return get_secret(sid)
        except Exception:
            return {}

    def is_configured(self) -> bool:
        """True if the env var is set (secret_id exists)."""
        return bool(self._secret_id)


# ---------------------------------------------------------------------------
# Pre-built service secret accessors - import these in tools / config
# ---------------------------------------------------------------------------
# Each env var holds the AWS Secrets Manager ARN or name for that service
jenkins = _ServiceSecrets("SECRET_ID_JENKINS", "Jenkins")
kibana = _ServiceSecrets("SECRET_ID_KIBANA", "Kibana/Elasticsearch")
artifactory = _ServiceSecrets("SECRET_ID_ARTIFACTORY", "JFrog Artifactory")
nginx = _ServiceSecrets("SECRET_ID_NGINX", "Nginx")
vertexai = _ServiceSecrets("SECRET_ID_VERTEXAI", "Vertex AI / Gemini")
bedrock = _ServiceSecrets("SECRET_ID_BEDROCK", "AWS Bedrock")
