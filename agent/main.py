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
from typing import Optional, List
import json

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
import uvicorn

from agent.orchestrator import Orchestrator
from agent.config import config
from agent.cache import configure_cache, invalidate_caches, QUERY_CACHE, TOOL_CACHE
from agent.metrics import get_metrics_collector
from agent.permissions import (
    get_permissions,
    set_mode_from_string,
    add_deny_tool,
    remove_deny_tool,
    check_tool_permission,
    set_allowed_tools as _set_allowed_tools_perms,
)
from agent.observability import (
    get_audit_logger,
    set_corr_id,
    set_user,
)

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

    # Propagate to observability context
    set_corr_id(corr_id)
    if hasattr(request.state, "user") and request.state.user:
        set_user(getattr(request.state.user, "subject", "anonymous"))

    # Rate limiting (skip for /health and /metrics)
    if request.url.path not in ("/health", "/metrics", "/docs", "/openapi.json"):
        client_ip = request.client.host if request.client else "unknown"
        if not rate_limiter.is_allowed(client_ip):
            logger.warning("[corr_id=%s] Rate limit exceeded for %s", corr_id, client_ip)
            get_audit_logger().log_auth(False, client_ip, "Rate limit exceeded")
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
    ollama_timeout: Optional[int] = Field(None, ge=30, le=600)
    # Infra URLs
    nginx_url: Optional[str] = None
    kibana_url: Optional[str] = None
    jenkins_url: Optional[str] = None
    artifactory_url: Optional[str] = None
    prometheus_url: Optional[str] = None
    grafana_url: Optional[str] = None
    grafana_api_key: Optional[str] = None
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

    # Apply non-cache config to the live config object (hot-reload without restart)
    cfg = config
    if req.ollama_base_url is not None:
        cfg.llm.ollama_base_url = req.ollama_base_url
    if req.ollama_model is not None:
        cfg.llm.ollama_model = req.ollama_model
    if req.ollama_temperature is not None:
        cfg.llm.ollama_temperature = req.ollama_temperature
    if req.ollama_max_tokens is not None:
        cfg.llm.ollama_max_tokens = req.ollama_max_tokens
    if req.ollama_timeout is not None:
        cfg.llm.ollama_timeout = req.ollama_timeout
    if req.nginx_url is not None:
        cfg.infra.nginx_url = req.nginx_url
    if req.kibana_url is not None:
        cfg.infra.kibana_url = req.kibana_url
    if req.jenkins_url is not None:
        cfg.infra.jenkins_url = req.jenkins_url
    if req.artifactory_url is not None:
        cfg.infra.artifactory_url = req.artifactory_url
    if req.prometheus_url is not None:
        cfg.infra.prometheus_url = req.prometheus_url
    if req.grafana_url is not None:
        cfg.infra.grafana_url = req.grafana_url
    if req.grafana_api_key is not None:
        cfg.infra.grafana_api_key = req.grafana_api_key
    if req.k8s_namespace is not None:
        cfg.infra.k8s_namespace = req.k8s_namespace
    if req.k8s_in_cluster is not None:
        cfg.infra.k8s_in_cluster = req.k8s_in_cluster
    if req.k8s_kubeconfig_path is not None:
        cfg.infra.k8s_kubeconfig_path = req.k8s_kubeconfig_path

    # Apply cache config
    cache_info = configure_cache(ttl=req.cache_ttl, max_size=req.cache_max_size)

    # Trigger hot-reload on orchestrator (rebuilds agent with new config)
    if _agent:
        _agent.reload()

    logger.info("[corr_id=%s] Config hot-reloaded", getattr(request.state, "corr_id", ""))
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
# Permission / Operation Mode endpoints
# ---------------------------------------------------------------------------
class OperationModeRequest(BaseModel):
    mode: str = Field(..., description="Operation mode: read_only, read_write, or safe_mode")

class DenyToolRequest(BaseModel):
    tool_name: str = Field(..., description="Tool name to deny or allow")

class AllowedToolsRequest(BaseModel):
    mode: str = Field(..., description="Mode: readonly or safemode")
    tools: List[str] = Field(..., description="List of allowed tool names")


@app.get("/permissions/status")
async def get_permissions_status(request: Request):
    """Get current permission/mode status."""
    verify_api_key(request)
    perms = get_permissions()
    return {
        "mode": perms.mode.value,
        "denied_tools": list(perms.denied_tools),
        "safe_mode_allowed_tools": list(perms.safe_mode_allowed_tools),
        "read_only_allowed_tools": list(perms.read_only_allowed_tools),
        "audit_enabled": perms.audit_enabled,
    }


@app.post("/permissions/mode")
async def set_permissions_mode(req: OperationModeRequest, request: Request):
    """Set operation mode: read_only, read_write, or safe_mode."""
    verify_api_key(request)
    if set_mode_from_string(req.mode):
        logger.info("[corr_id=%s] Operation mode changed to: %s", getattr(request.state, "corr_id", ""), req.mode)
        return {"status": "ok", "mode": req.mode}
    return {"status": "error", "message": f"Invalid mode: {req.mode}. Valid modes: read_only, read_write, safe_mode"}


@app.post("/permissions/deny")
async def deny_tool(req: DenyToolRequest, request: Request):
    """Add a tool to the deny list."""
    verify_api_key(request)
    add_deny_tool(req.tool_name)
    logger.info("[corr_id=%s] Tool '%s' denied", getattr(request.state, "corr_id", ""), req.tool_name)
    return {"status": "ok", "tool_name": req.tool_name, "action": "denied"}


@app.post("/permissions/allow")
async def allow_tool(req: DenyToolRequest, request: Request):
    """Remove a tool from the deny list."""
    verify_api_key(request)
    remove_deny_tool(req.tool_name)
    logger.info("[corr_id=%s] Tool '%s' allowed", getattr(request.state, "corr_id", ""), req.tool_name)
    return {"status": "ok", "tool_name": req.tool_name, "action": "allowed"}


@app.post("/permissions/allowed-tools")
async def set_allowed_tools_endpoint(req: AllowedToolsRequest, request: Request):
    """Set explicit list of allowed tools for a mode."""
    verify_api_key(request)
    _set_allowed_tools_perms(req.mode, req.tools)
    logger.info("[corr_id=%s] Allowed tools for %s mode set to: %s", getattr(request.state, "corr_id", ""), req.mode, req.tools)
    return {"status": "ok", "mode": req.mode, "allowed_tools": req.tools}


@app.get("/permissions/check/{tool_name}")
async def check_tool(tool_name: str, request: Request):
    """Check if a specific tool is allowed in current mode."""
    verify_api_key(request)
    allowed, reason = check_tool_permission(tool_name)
    perms = get_permissions()
    return {
        "tool": tool_name,
        "allowed": allowed,
        "reason": reason,
        "current_mode": perms.mode.value,
    }


@app.get("/permissions/audit-log")
async def get_audit_log(request: Request):
    """Get recent audit log entries (reads from log file)."""
    verify_api_key(request)
    perms = get_permissions()
    log_path = perms.audit_log_path
    entries = []
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                lines = f.readlines()
                # Return last 100 entries
                entries = [json.loads(line) for line in lines[-100:] if line.strip()]
    except Exception:
        return {"error": "Failed to read audit log entries", "entries": []}
    return {"entries": entries, "log_path": log_path}


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
        start = time.time()
        result = _agent.run(req.question, req.session_id or "default")
        latency_ms = int((time.time() - start) * 1000)

        # Structured audit log for query execution
        get_audit_logger().log_query(
            question=req.question,
            session_id=req.session_id or "default",
            tool_used=result.get("tool_used"),
            cached=result.get("cached", False),
            latency_ms=latency_ms,
            error="",
        )

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
# Knowledge Base API
# ---------------------------------------------------------------------------
from agent.knowledge_base import (  # noqa: E402
    add_entry,
    build_rag_context,
    delete_entry,
    get_entry,
    get_stats,
    list_entries,
    search_entries,
    update_entry,
    KnowledgeEntry,
    ALL_COLLECTIONS,
)

class KBAddRequest(BaseModel):
    title: str
    content: str
    collection: str = Field(..., description="runbooks, incidents, configs, sops, kb")
    tags: str = Field(default="", description="Comma-separated tags")
    author: str = Field(default="")

class KBSearchRequest(BaseModel):
    query: str
    collection: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)

class KBUpdateRequest(BaseModel):
    content: str = ""
    title: str = ""
    tags: str = ""


@app.get("/kb/stats")
async def kb_stats(request: Request):
    verify_api_key(request)
    return get_stats()


@app.post("/kb/search")
async def kb_search(req: KBSearchRequest, request: Request):
    verify_api_key(request)
    if req.collection and req.collection not in ALL_COLLECTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid collection. Valid: {ALL_COLLECTIONS}")
    results = search_entries(query=req.query, collection=req.collection, n_results=req.top_k)
    return {"query": req.query, "results": results, "count": len(results)}


@app.post("/kb/context")
async def kb_context(req: KBSearchRequest, request: Request):
    verify_api_key(request)
    context = build_rag_context(query=req.query, collection=req.collection, top_k=req.top_k)
    return {"query": req.query, "context": context}


@app.get("/kb/{collection}")
async def kb_list(collection: str, request: Request, limit: int = 50):
    verify_api_key(request)
    if collection not in ALL_COLLECTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid collection. Valid: {ALL_COLLECTIONS}")
    return {"collection": collection, "entries": list_entries(collection=collection, limit=limit)}


@app.get("/kb/{collection}/{entry_id}")
async def kb_get(collection: str, entry_id: str, request: Request):
    verify_api_key(request)
    entry = get_entry(entry_id=entry_id, collection=collection)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found in {collection}")
    return entry


@app.post("/kb/add")
async def kb_add(req: KBAddRequest, request: Request):
    verify_api_key(request)
    if req.collection not in ALL_COLLECTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid collection. Valid: {ALL_COLLECTIONS}")
    import uuid
    entry = KnowledgeEntry(
        id=str(uuid.uuid4()),
        title=req.title,
        content=req.content,
        collection=req.collection,
        tags=[t.strip() for t in req.tags.split(",") if t.strip()],
        author=req.author or "devops-ai",
    )
    add_entry(entry)
    return {"status": "ok", "id": entry.id}


@app.put("/kb/{collection}/{entry_id}")
async def kb_update(collection: str, entry_id: str, req: KBUpdateRequest, request: Request):
    verify_api_key(request)
    kwargs = {}
    if req.content:
        kwargs["content"] = req.content
    if req.title:
        kwargs["title"] = req.title
    if req.tags:
        kwargs["tags"] = [t.strip() for t in req.tags.split(",") if t.strip()]
    if not kwargs:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update_entry(entry_id=entry_id, collection=collection, **kwargs)
    return {"status": "ok"}


@app.delete("/kb/{collection}/{entry_id}")
async def kb_delete(collection: str, entry_id: str, request: Request):
    verify_api_key(request)
    delete_entry(entry_id=entry_id, collection=collection)
    return {"status": "ok"}


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
