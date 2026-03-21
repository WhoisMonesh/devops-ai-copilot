# agent/main.py - DevOps AI Copilot Backend (FastAPI)
# Features: Auth, Metrics, Hot-reload config, Rate limiting, Structured logging
from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
import uvicorn

from agent.orchestrator import Orchestrator
from config import config
from cache import configure_cache, invalidate_caches, QUERY_CACHE, TOOL_CACHE
from metrics import get_metrics_collector

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting (in-memory, per-IP sliding window)
# ---------------------------------------------------------------------------
@dataclass
class RateLimitEntry:
    tokens: int
    last_refill: float

class RateLimiter:
    """Simple token-bucket rate limiter."""

    def __init__(self, rate: int = 60, per: int = 60) -> None:
        self._buckets: dict[str, RateLimitEntry] = {}
        self._lock = Lock()
        self._rate = rate  # requests
        self._per = per     # per seconds

    def is_allowed(self, key: str) -> bool:
        with self._lock:
            now = time.time()
            entry = self._buckets.get(key)
            if entry is None or now - entry.last_refill >= self._per:
                self._buckets[key] = RateLimitEntry(tokens=self._rate, last_refill=now)
                return True
            if entry.tokens > 0:
                entry.tokens -= 1
                return True
            return False

rate_limiter = RateLimiter(rate=60, per=60)  # 60 requests/minute per IP


# ---------------------------------------------------------------------------
# API key authentication
# ---------------------------------------------------------------------------
API_KEY = os.getenv("API_KEY", "")  # Set via env; empty = disabled

def verify_api_key(request: Request) -> Optional[str]:
    """Return client key if valid, None if auth disabled, raise HTTPException if invalid."""
    if not API_KEY:
        return None  # Auth disabled
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if secrets.compare_digest(token, API_KEY):
            return token
    raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="DevOps AI Copilot",
    description="AI-powered DevOps assistant - K8s, Jenkins, Kibana, Grafana, Prometheus, Nginx",
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global orchestrator
_agent: Optional[Orchestrator] = None

@app.on_event("startup")
async def startup_event():
    global _agent
    _agent = Orchestrator()
    logger.info("DevOps AI Copilot agent started v1.1.0")


# ---------------------------------------------------------------------------
# Middleware: correlation ID + rate limiting
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_correlation_and_rate_limit(request: Request, call_next):
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4())[:8])
    request.state.corr_id = corr_id

    # Rate limiting (skip for /health and /metrics)
    if request.url.path not in ("/health", "/metrics", "/docs", "/openapi.json"):
        client_ip = request.client.host if request.client else "unknown"
        if not rate_limiter.is_allowed(client_ip):
            logger.warning("[corr_id=%s] Rate limit exceeded for %s", corr_id, client_ip)
            return Response(
                content='{"error":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"X-Correlation-ID": corr_id},
            )

    response = await call_next(request)
    response.headers["X-Correlation-ID"] = corr_id
    return response


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    context: Optional[str] = ""
    session_id: Optional[str] = "default"

class QueryResponse(BaseModel):
    answer: str
    sources: list
    tool_calls: list
    session_id: str
    cached: Optional[bool] = False
    corr_id: Optional[str] = None
    latency_seconds: Optional[float] = None

class ConfigUpdateRequest(BaseModel):
    # LLM / Ollama
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    ollama_temperature: Optional[float] = None
    ollama_max_tokens: Optional[int] = None
    # Infra URLs
    nginx_url: Optional[str] = None
    kibana_url: Optional[str] = None
    jenkins_url: Optional[str] = None
    artifactory_url: Optional[str] = None
    prometheus_url: Optional[str] = None
    grafana_url: Optional[str] = None
    k8s_in_cluster: Optional[bool] = None
    k8s_namespace: Optional[str] = None
    k8s_kubeconfig_path: Optional[str] = None
    # Cache config
    cache_ttl: Optional[int] = Field(None, ge=30, le=3600)
    cache_max_size: Optional[int] = Field(None, ge=50, le=10000)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check(request: Request):
    corr_id = getattr(request.state, "corr_id", "")
    agent_status = "ok" if _agent is not None else "not_initialized"
    llm_info = _agent.llm_health() if _agent else {}
    return {
        "status": agent_status,
        "service": "devops-ai-copilot-agent",
        "version": "1.1.0",
        "correlation_id": corr_id,
        "llm": llm_info,
    }


# ---------------------------------------------------------------------------
# Prometheus metrics endpoint
# ---------------------------------------------------------------------------
@app.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------
@app.get("/config")
async def get_config(request: Request):
    verify_api_key(request)
    return config.to_dict()


@app.post("/config")
async def update_config(req: ConfigUpdateRequest, request: Request):
    verify_api_key(request)
    logger.info("[corr_id=%s] Config update requested", getattr(request.state, "corr_id", ""))
    # Apply cache config first
    cache_info = configure_cache(ttl=req.cache_ttl, max_size=req.cache_max_size)
    # Trigger hot-reload on orchestrator
    if _agent:
        _agent.reload()
    return {
        "status": "ok",
        "message": "Configuration hot-reloaded",
        "cache": cache_info,
    }


# ---------------------------------------------------------------------------
# Cache stats endpoint
# ---------------------------------------------------------------------------
@app.get("/cache/stats")
async def cache_stats(request: Request):
    verify_api_key(request)
    return {
        "query_cache": {
            "size": QUERY_CACHE.size,
            "hits": QUERY_CACHE.hits,
            "misses": QUERY_CACHE.misses,
            "hit_ratio": round(QUERY_CACHE.hit_ratio, 4),
        },
        "tool_cache": {
            "size": TOOL_CACHE.size,
            "hits": TOOL_CACHE.hits,
            "misses": TOOL_CACHE.misses,
            "hit_ratio": round(TOOL_CACHE.hit_ratio, 4),
        },
    }


@app.post("/cache/invalidate")
async def invalidate_cache(request: Request):
    verify_api_key(request)
    invalidate_caches()
    logger.info("[corr_id=%s] Cache invalidated", getattr(request.state, "corr_id", ""))
    return {"status": "ok", "message": "Cache invalidated"}


# ---------------------------------------------------------------------------
# Query endpoint
# ---------------------------------------------------------------------------
@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, request: Request):
    verify_api_key(request)
    corr_id = getattr(request.state, "corr_id", "")
    metrics = get_metrics_collector()

    if not _agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = _agent.run(req.question, req.session_id or "default")
        return QueryResponse(
            answer=result["answer"],
            sources=result.get("sources", []),
            tool_calls=result.get("tool_calls", []),
            session_id=req.session_id or "default",
            cached=result.get("cached", False),
            corr_id=result.get("corr_id", corr_id),
            latency_seconds=result.get("latency_seconds"),
        )
    except Exception as e:
        logger.error("[corr_id=%s] Query failed: %s", corr_id, e)
        metrics.record_error(type(e).__name__, "query_endpoint")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Tools listing
# ---------------------------------------------------------------------------
@app.get("/tools")
async def list_tools(request: Request):
    verify_api_key(request)
    if not _agent or not _agent._agent_executor:
        return []
    tools = _agent._agent_executor.tools
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": (
                t.args_schema.schema()
                if hasattr(t, "args_schema") and hasattr(t.args_schema, "schema")
                else {}
            ),
        }
        for t in tools
    ]


if __name__ == "__main__":
    uvicorn.run(
        "agent.main:app",
        host=config.app.host,
        port=config.app.port,
        reload=config.app.reload,
    )
