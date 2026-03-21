# agent/ollama_client.py - Dedicated Ollama client
# Handles: health check, model listing, model pull, and LLM init
# Used by orchestrator.py as the default (3rd container) AI provider.

import requests
import logging
from typing import List, Optional
from langchain_community.llms import Ollama
from langchain_community.chat_models import ChatOllama
from agent.config import config

logger = logging.getLogger(__name__)


class OllamaClient:
    """Wrapper around Ollama REST API + LangChain integration."""

    def __init__(self):
        self.base_url = config.llm.ollama_base_url
        self.timeout  = config.llm.ollama_timeout

    # ------------------------------------------------------------------
    # Health & discovery
    # ------------------------------------------------------------------
    def is_healthy(self) -> bool:
        """Return True if the Ollama container is up."""
        try:
            r = requests.get(f"{self.base_url}/api/version", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def get_version(self) -> str:
        """Return Ollama server version string."""
        try:
            r = requests.get(f"{self.base_url}/api/version", timeout=5)
            r.raise_for_status()
            return r.json().get("version", "unknown")
        except Exception as e:
            return f"error: {e}"

    def list_models(self) -> List[dict]:
        """Return list of locally available models on the Ollama container."""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=10)
            r.raise_for_status()
            models = r.json().get("models", [])
            return [
                {
                    "name":     m["name"],
                    "size_gb":  round(m.get("size", 0) / 1e9, 2),
                    "modified": m.get("modified_at", ""),
                }
                for m in models
            ]
        except Exception as e:
            logger.warning(f"Could not list Ollama models: {e}")
            return []

    def model_names(self) -> List[str]:
        """Return plain list of model name strings."""
        return [m["name"] for m in self.list_models()]

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------
    def pull_model(self, model: Optional[str] = None) -> bool:
        """Pull a model into the Ollama container (blocking).
        Returns True on success."""
        model = model or config.llm.ollama_model
        logger.info(f"Pulling Ollama model: {model} ...")
        try:
            r = requests.post(
                f"{self.base_url}/api/pull",
                json={"name": model, "stream": False},
                timeout=600,          # large models take time
            )
            r.raise_for_status()
            status = r.json().get("status", "")
            logger.info(f"Pull result for {model}: {status}")
            return True
        except Exception as e:
            logger.error(f"Failed to pull model {model}: {e}")
            return False

    def ensure_model(self, model: Optional[str] = None) -> bool:
        """Pull the model only if it is not already present."""
        model = model or config.llm.ollama_model
        if model in self.model_names():
            logger.info(f"Model '{model}' already present, skipping pull.")
            return True
        return self.pull_model(model)

    def delete_model(self, model: str) -> bool:
        """Delete a model from the Ollama container."""
        try:
            r = requests.delete(
                f"{self.base_url}/api/delete",
                json={"name": model},
                timeout=30,
            )
            return r.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Failed to delete model {model}: {e}")
            return False

    # ------------------------------------------------------------------
    # LangChain LLM constructors
    # ------------------------------------------------------------------
    def get_llm(self, model: Optional[str] = None) -> Ollama:
        """Return a LangChain Ollama LLM instance (for plain text generation)."""
        model = model or config.llm.ollama_model
        return Ollama(
            base_url    = self.base_url,
            model       = model,
            temperature = config.llm.ollama_temperature,
            num_ctx     = config.llm.ollama_num_ctx,
            timeout     = self.timeout,
        )

    def get_chat_model(self, model: Optional[str] = None) -> ChatOllama:
        """Return a LangChain ChatOllama instance (for agent/chat use)."""
        model = model or config.llm.ollama_model
        return ChatOllama(
            base_url    = self.base_url,
            model       = model,
            temperature = config.llm.ollama_temperature,
            num_ctx     = config.llm.ollama_num_ctx,
            timeout     = self.timeout,
        )

    # ------------------------------------------------------------------
    # Raw generate (no LangChain)
    # ------------------------------------------------------------------
    def generate(self, prompt: str, model: Optional[str] = None) -> str:
        """Send a raw prompt to Ollama and return the response string."""
        model = model or config.llm.ollama_model
        try:
            r = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json().get("response", "")
        except Exception as e:
            return f"Ollama generate error: {e}"


# Singleton
ollama = OllamaClient()
