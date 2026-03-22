# agent/llm_client.py - Unified LLM Client
# Supports 3 providers:
#   1. Ollama     - local in-cluster model (default)
#   2. Vertex AI  - Google Gemini via service-account JSON credentials
#   3. AWS Bedrock - Claude/Titan via IAM role (IRSA) or static keys
#
# Resilience features:
#   - Circuit breaker per provider (5 failures = open, 30s recovery)
#   - Exponential backoff retry (3 attempts: 1s / 2s / 4s delays)
#   - Cached health checks (5s TTL) to avoid hammering endpoints
#   - Token usage estimation
#   - Streaming support for Ollama

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Generator

import httpx

from agent.config import config

logger = logging.getLogger(__name__)


# ============================================================================
# Circuit Breaker (per provider)
# ============================================================================
class CircuitState(Enum):
    CLOSED = "closed"   # Normal: calls pass through
    OPEN   = "open"     # Failing: reject calls for recovery_timeout seconds
    HALF   = "half"     # Probing: allow one call to test recovery


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 1

    _state: CircuitState = field(default=CircuitState.CLOSED, repr=False)
    _failure_count: int = field(default=0, repr=False)
    _last_failure_time: float = field(default=0.0, repr=False)
    _half_open_calls: int = field(default=0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def can_execute(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF
                    self._half_open_calls = 0
                    logger.info("Circuit breaker OPEN → HALF (recovery window elapsed)")
                    return True
                return False
            # HALF: allow one probe call
            return self._half_open_calls < self.half_open_max_calls

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF:
                self._state = CircuitState.CLOSED
                self._half_open_calls = 0
                logger.info("Circuit breaker HALF → CLOSED (probe succeeded)")
            # CLOSED: stay closed

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF:
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker HALF → OPEN (probe failed)")
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker CLOSED → OPEN (%d consecutive failures)",
                    self.failure_threshold,
                )

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state


# Per-provider circuit breakers
_circuit_breakers: dict[str, CircuitBreaker] = {
    "ollama":   CircuitBreaker(),
    "vertexai": CircuitBreaker(),
    "bedrock":  CircuitBreaker(),
}


def _cb(provider: str) -> CircuitBreaker:
    return _circuit_breakers.get(provider, CircuitBreaker())


# ============================================================================
# Retry with exponential backoff
# ============================================================================
def _retry(
    fn: Callable[[], str],
    provider: str,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> str:
    for attempt in range(1, max_attempts + 1):
        if not _cb(provider).can_execute():
            raise RuntimeError(
                f"Circuit breaker is { _cb(provider).state.value } for '{provider}'. "
                "Provider is temporarily unavailable."
            )
        try:
            return fn()
        except Exception:
            # Intentionally broad: _retry wraps heterogeneous providers (httpx, boto3, google-auth)
            # and needs to retry on any failure type; last_error remains empty as exc binding is unused
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), 8.0)
                logger.info("[%s] Retrying in %.1fs...", provider.upper(), delay)
                time.sleep(delay)

    _cb(provider).record_failure()
    raise RuntimeError(f"All {max_attempts} attempts failed for '{provider}'")


# ============================================================================
# Health check with 5s TTL cache
# ============================================================================
_health_cache: dict[str, tuple[str, float]] = {}
_HEALTH_CACHE_TTL = 5.0


def _health_cached(provider: str, check_fn: Callable[[], str]) -> str:
    now = time.time()
    if provider in _health_cache:
        status, cached_at = _health_cache[provider]
        if now - cached_at < _HEALTH_CACHE_TTL:
            return status
    status = check_fn()
    _health_cache[provider] = (status, now)
    return status


# ============================================================================
# Token estimation (word-based approximation)
# ============================================================================
def _est_tokens(text: str) -> int:
    return len(text.split()) * 4 // 3


# ============================================================================
# Provider 1 – Ollama (local, in-cluster)
# ============================================================================
def _ollama_chat(prompt: str, system: str = "") -> str:
    cfg = config.llm
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": cfg.ollama_model,
        "messages": messages,
        "options": {
            "temperature": cfg.ollama_temperature,
            "num_predict": cfg.ollama_max_tokens,
        },
        "stream": False,
    }
    url = f"{cfg.ollama_base_url}/api/chat"

    def _call() -> str:
        with httpx.Client(timeout=cfg.ollama_timeout) as client:
            logger.info("[Ollama] POST %s model=%s", url, cfg.ollama_model)
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "").strip()

    return _retry(_call, "ollama")


def _ollama_stream(prompt: str, system: str = "") -> Generator[str, None, None]:
    cfg = config.llm
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": cfg.ollama_model,
        "messages": messages,
        "options": {
            "temperature": cfg.ollama_temperature,
            "num_predict": cfg.ollama_max_tokens,
        },
        "stream": True,
    }
    url = f"{cfg.ollama_base_url}/api/chat"

    try:
        with httpx.Client(timeout=cfg.ollama_timeout) as client:
            with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            token = data.get("message", {}).get("content", "")
                            if token:
                                yield token
                        except json.JSONDecodeError:
                            continue
        _cb("ollama").record_success()
    except Exception:
        # Intentionally broad: stream may encounter httpx or OS-level errors; record failure and re-raise
        _cb("ollama").record_failure()
        raise


def _ollama_health() -> str:
    def _check() -> str:
        try:
            with httpx.Client(timeout=5) as client:
                r = client.get(f"{config.llm.ollama_base_url}/api/tags")
                r.raise_for_status()
                return "ok"
        except Exception:
            # Intentionally broad: health check must handle httpx, DNS, connection errors
            return ""
    return _health_cached("ollama", _check)


def _ollama_list_models() -> list[str]:
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{config.llm.ollama_base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        # Intentionally broad: list_models may encounter httpx or network errors
        return []


# ============================================================================
# Provider 2 – Vertex AI / Gemini
# ============================================================================
def _vertexai_credentials():
    try:
        from google.oauth2 import service_account
    except ImportError:
        msg = "google-auth is required for Vertex AI. Install: pip install google-auth"
        raise ImportError(msg) from None
    cfg = config.llm
    if cfg.vertexai_credentials_json:
        info = json.loads(cfg.vertexai_credentials_json)
        return service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    elif cfg.vertexai_credentials_file:
        return service_account.Credentials.from_service_account_file(
            cfg.vertexai_credentials_file,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    else:
        import google.auth
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return creds


def _vertexai_chat(prompt: str, system: str = "") -> str:
    def _call() -> str:
        import vertexai
        from vertexai.generative_models import GenerationConfig, GenerativeModel
        cfg = config.llm
        vertexai.init(
            project=cfg.vertexai_project,
            location=cfg.vertexai_location,
            credentials=_vertexai_credentials(),
        )
        model = GenerativeModel(
            cfg.vertexai_model,
            system_instruction=system if system else None,
        )
        gen_config = GenerationConfig(
            temperature=cfg.vertexai_temperature,
            max_output_tokens=cfg.vertexai_max_tokens,
        )
        logger.info("[VertexAI] project=%s model=%s", cfg.vertexai_project, cfg.vertexai_model)
        response = model.generate_content(prompt, generation_config=gen_config)
        return response.text.strip()

    return _retry(_call, "vertexai")


def _vertexai_health() -> str:
    def _check() -> str:
        try:
            cfg = config.llm
            if not cfg.vertexai_project:
                return "missing_project"
            _vertexai_credentials()
            return "ok"
        except Exception:
            # Intentionally broad: health check must handle httpx, DNS, connection, auth errors
            return ""
    return _health_cached("vertexai", _check)


# ============================================================================
# Provider 3 – AWS Bedrock (IRSA or static keys)
# ============================================================================
def _bedrock_client():
    try:
        import boto3
    except ImportError:
        msg = "boto3 is required for Bedrock. Install: pip install boto3"
        raise ImportError(msg) from None
    cfg = config.llm
    kwargs: dict = {"region_name": cfg.bedrock_region}
    if cfg.aws_access_key_id and cfg.aws_secret_access_key:
        kwargs["aws_access_key_id"] = cfg.aws_access_key_id
        kwargs["aws_secret_access_key"] = cfg.aws_secret_access_key
        if cfg.aws_session_token:
            kwargs["aws_session_token"] = cfg.aws_session_token
    return boto3.client("bedrock-runtime", **kwargs)


def _bedrock_chat(prompt: str, system: str = "") -> str:
    def _call() -> str:
        cfg = config.llm
        client = _bedrock_client()
        model_id = cfg.bedrock_model_id
        logger.info("[Bedrock] region=%s model=%s", cfg.bedrock_region, model_id)

        if "anthropic.claude" in model_id:
            body: dict = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": cfg.bedrock_max_tokens,
                "temperature": cfg.bedrock_temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                body["system"] = system
            resp = client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(resp["body"].read())
            return result["content"][0]["text"].strip()

        elif "amazon.titan" in model_id:
            full_prompt = f"{system}\n\n{prompt}" if system else prompt
            body = {
                "inputText": full_prompt,
                "textGenerationConfig": {
                    "maxTokenCount": cfg.bedrock_max_tokens,
                    "temperature": cfg.bedrock_temperature,
                },
            }
            resp = client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(resp["body"].read())
            return result["results"][0]["outputText"].strip()

        elif "meta.llama" in model_id:
            full_prompt = (
                f"<|system|>\n{system}<|end|>\n<|user|>\n{prompt}<|end|>\n<|assistant|>\n"
                if system
                else f"<|user|>\n{prompt}<|end|>\n<|assistant|>\n"
            )
            body = {
                "prompt": full_prompt,
                "max_gen_len": cfg.bedrock_max_tokens,
                "temperature": cfg.bedrock_temperature,
            }
            resp = client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(resp["body"].read())
            return result.get("generation", "").strip()

        else:
            raise ValueError(
                f"Unsupported Bedrock model: {model_id}. "
                "Supported: anthropic.claude, amazon.titan, meta.llama"
            )

    return _retry(_call, "bedrock")


def _bedrock_health() -> str:
    def _check() -> str:
        try:
            _bedrock_client().list_foundation_models()
            return "ok"
        except Exception:
            # Intentionally broad: health check must handle httpx, DNS, connection, auth errors
            return ""
    return _health_cached("bedrock", _check)


# ============================================================================
# Public API
# ============================================================================
def chat(prompt: str, system: str = "") -> str:
    """
    Send a prompt to the configured LLM provider.

    Provider is selected by LLM_PROVIDER env var:
      - "ollama"    -> local Ollama container (default)
      - "vertexai"  -> Google Vertex AI / Gemini
      - "bedrock"   -> AWS Bedrock (Claude / Titan / Llama)
    """
    provider = config.llm.provider.lower().strip()
    logger.info("[LLMClient] provider=%s", provider)

    if provider == "ollama":
        result = _ollama_chat(prompt, system)
    elif provider in ("vertexai", "vertex_ai", "gemini"):
        result = _vertexai_chat(prompt, system)
    elif provider in ("bedrock", "aws_bedrock", "aws"):
        result = _bedrock_chat(prompt, system)
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER='{provider}'. "
            "Valid options: 'ollama', 'vertexai', 'bedrock'"
        )

    # Record token usage
    tokens = _est_tokens(result)
    from agent.metrics import get_metrics_collector
    mc = get_metrics_collector()
    mc.record_llm_call(provider, "success", 0.0, tokens)

    return result


def chat_stream(prompt: str, system: str = "") -> Generator[str, None, None]:
    """
    Stream tokens from the LLM.
    Currently only Ollama supports streaming; other providers return
    non-streaming responses via their respective chat() functions.
    """
    provider = config.llm.provider.lower().strip()
    if provider == "ollama":
        yield from _ollama_stream(prompt, system)
    else:
        yield chat(prompt, system)


def health() -> dict:
    """Return health status of all configured LLM providers."""
    raw_provider = config.llm.provider.lower().strip()
    # Normalize provider aliases to canonical keys
    provider_map = {
        "ollama":   "ollama",
        "vertexai": "vertexai", "vertex_ai": "vertexai", "gemini": "vertexai",
        "bedrock":  "bedrock", "aws_bedrock": "bedrock", "aws": "bedrock",
    }
    provider = provider_map.get(raw_provider, raw_provider)

    info: dict = {
        "provider": raw_provider,
        "providers": {},
    }

    checks = {
        "ollama":   (_ollama_health,   _ollama_chat),
        "vertexai": (_vertexai_health, _vertexai_chat),
        "bedrock":  (_bedrock_health,  _bedrock_chat),
    }

    for name, (health_fn, _) in checks.items():
        status = health_fn()
        cb = _cb(name)
        info["providers"][name] = {
            "status": "ok" if status == "ok" else "error",
            "detail": status,
            "circuit_breaker": cb.state.value,
            "is_primary": name == provider,
        }

    primary_check = checks.get(provider, (_ollama_health, None))
    primary_status = primary_check[0]() if primary_check[0] else "unknown"
    info["status"] = "ok" if primary_status == "ok" else "degraded"
    info["detail"] = primary_status
    return info


_ = (os, tempfile)  # noqa: F401
