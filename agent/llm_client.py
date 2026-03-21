# agent/llm_client.py - Unified LLM Client
# Supports 3 providers:
#   1. Ollama     - local in-cluster model (default)
#   2. Vertex AI  - Google Gemini via service-account JSON credentials
#   3. AWS Bedrock - Claude/Titan via IAM role (IRSA) or static keys
from __future__ import annotations

import json
import logging
import os
import tempfile

import httpx

from config import config

logger = logging.getLogger(__name__)


# ===========================================================================
# Provider 1 - Ollama (local)
# ===========================================================================
def _call_ollama(prompt: str, system: str = "") -> str:
    """Call local Ollama container via REST API."""
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
    logger.info("[Ollama] POST %s model=%s", url, cfg.ollama_model)
    with httpx.Client(timeout=120) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()


def _check_ollama() -> str:
    """Return 'ok' if Ollama is reachable, else error string."""
    try:
        with httpx.Client(timeout=5) as client:
            r = client.get(f"{config.llm.ollama_base_url}/api/tags")
            r.raise_for_status()
            return "ok"
    except Exception as e:
        return str(e)


def _list_ollama_models() -> list[str]:
    """Return list of locally available Ollama model names."""
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{config.llm.ollama_base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


# ===========================================================================
# Provider 2 - Vertex AI / Gemini
# ===========================================================================
def _get_vertexai_credentials():
    """
    Build Google credentials object from either:
    - GOOGLE_APPLICATION_CREDENTIALS env (path to JSON file)
    - VERTEXAI_CREDENTIALS_JSON env (raw JSON string)
    """
    try:
        from google.oauth2 import service_account
    except ImportError:
        raise ImportError("google-auth not installed. Add 'google-auth' to requirements.txt.")
    cfg = config.llm
    if cfg.vertexai_credentials_json:
        # JSON content passed directly as env var (K8s Secret -> env)
        info = json.loads(cfg.vertexai_credentials_json)
        return service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    elif cfg.vertexai_credentials_file:
        # Path to mounted JSON file (K8s Secret -> volume mount)
        return service_account.Credentials.from_service_account_file(
            cfg.vertexai_credentials_file,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    else:
        # Fall back to Application Default Credentials (Workload Identity)
        import google.auth
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return creds


def _call_vertexai(prompt: str, system: str = "") -> str:
    """Call Vertex AI Gemini model."""
    try:
        import vertexai
        from vertexai.generative_models import GenerationConfig, GenerativeModel
    except ImportError:
        raise ImportError("google-cloud-aiplatform not installed. Add it to requirements.txt.")
    cfg = config.llm
    creds = _get_vertexai_credentials()
    vertexai.init(
        project=cfg.vertexai_project,
        location=cfg.vertexai_location,
        credentials=creds,
    )
    model = GenerativeModel(
        model_name=cfg.vertexai_model,
        system_instruction=system if system else None,
    )
    gen_config = GenerationConfig(
        temperature=cfg.vertexai_temperature,
        max_output_tokens=cfg.vertexai_max_tokens,
    )
    logger.info("[VertexAI] project=%s model=%s", cfg.vertexai_project, cfg.vertexai_model)
    response = model.generate_content(prompt, generation_config=gen_config)
    return response.text.strip()


# ===========================================================================
# Provider 3 - AWS Bedrock (IAM role / IRSA)
# ===========================================================================
def _get_bedrock_client():
    """
    Build boto3 Bedrock runtime client.
    - Inside EKS with IRSA: no creds needed, boto3 picks up the role automatically.
    - Outside EKS: set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN.
    """
    try:
        import boto3
    except ImportError:
        raise ImportError("boto3 not installed. Add it to requirements.txt.")
    cfg = config.llm
    kwargs: dict = {"region_name": cfg.bedrock_region}
    # Only pass explicit creds if provided (non-IRSA setup)
    if cfg.aws_access_key_id and cfg.aws_secret_access_key:
        kwargs["aws_access_key_id"] = cfg.aws_access_key_id
        kwargs["aws_secret_access_key"] = cfg.aws_secret_access_key
        if cfg.aws_session_token:
            kwargs["aws_session_token"] = cfg.aws_session_token
    return boto3.client("bedrock-runtime", **kwargs)


def _call_bedrock(prompt: str, system: str = "") -> str:
    """Call AWS Bedrock - supports Anthropic Claude and Amazon Titan models."""
    cfg = config.llm
    client = _get_bedrock_client()
    model_id = cfg.bedrock_model_id
    logger.info("[Bedrock] region=%s model=%s", cfg.bedrock_region, model_id)
    # Anthropic Claude models (claude-2, claude-3-*)
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
    # Amazon Titan models
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
    # Meta Llama 3 on Bedrock
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
            "Supported prefixes: anthropic.claude, amazon.titan, meta.llama"
        )


# ===========================================================================
# Public unified interface
# ===========================================================================
def chat(prompt: str, system: str = "") -> str:
    """
    Send a prompt to the configured LLM provider.
    Provider is selected by LLM_PROVIDER env var (or GUI config):
      - "ollama"    -> local Ollama container (default)
      - "vertexai"  -> Google Vertex AI / Gemini
      - "bedrock"   -> AWS Bedrock (Claude / Titan / Llama)
    """
    provider = config.llm.provider.lower().strip()
    logger.info("[LLMClient] provider=%s", provider)
    if provider == "ollama":
        return _call_ollama(prompt, system)
    elif provider in ("vertexai", "vertex_ai", "gemini"):
        return _call_vertexai(prompt, system)
    elif provider in ("bedrock", "aws_bedrock", "aws"):
        return _call_bedrock(prompt, system)
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER='{provider}'. "
            "Valid options: 'ollama', 'vertexai', 'bedrock'"
        )


def health() -> dict:
    """Return health/status of the currently configured LLM provider."""
    provider = config.llm.provider.lower().strip()
    info: dict = {"provider": provider}
    if provider == "ollama":
        status = _check_ollama()
        info["status"] = "ok" if status == "ok" else "error"
        info["detail"] = status
        info["models"] = _list_ollama_models()
    elif provider in ("vertexai", "vertex_ai", "gemini"):
        info["status"] = "configured" if config.llm.vertexai_project else "missing_project"
        info["project"] = config.llm.vertexai_project
        info["model"] = config.llm.vertexai_model
    elif provider in ("bedrock", "aws_bedrock", "aws"):
        info["status"] = "configured"
        info["region"] = config.llm.bedrock_region
        info["model_id"] = config.llm.bedrock_model_id
        info["irsa"] = not bool(config.llm.aws_access_key_id)  # True = using IRSA
    else:
        info["status"] = "unknown_provider"
    return info


# Suppress unused import warnings for tempfile/os used in credential helpers
_ = (os, tempfile)  # noqa: F401
