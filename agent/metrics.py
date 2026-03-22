# agent/metrics.py - Agent self-monitoring via Prometheus metrics

import logging
from threading import Lock
from typing import Optional

from prometheus_client import Counter, Histogram, Gauge, Info

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics definitions
# ---------------------------------------------------------------------------
INFO = Info("devops_copilot_agent", "DevOps AI Copilot agent info")
INFO.info({"version": "1.1.0", "framework": "fastapi+langchain"})

# Request metrics
REQUEST_COUNT = Counter(
    "devops_copilot_requests_total",
    "Total number of queries received",
    ["status", "tool_used"]
)
REQUEST_LATENCY = Histogram(
    "devops_copilot_request_latency_seconds",
    "Latency of query processing",
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
)

# Tool usage metrics
TOOL_CALL_COUNT = Counter(
    "devops_copilot_tool_calls_total",
    "Total number of tool invocations",
    ["tool_name", "status"]
)
TOOL_LATENCY = Histogram(
    "devops_copilot_tool_latency_seconds",
    "Tool invocation latency",
    ["tool_name"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# Cache metrics
CACHE_HITS = Counter("devops_copilot_cache_hits_total", "Total cache hits")
CACHE_MISSES = Counter("devops_copilot_cache_misses_total", "Total cache misses")
CACHE_HIT_RATIO = Gauge("devops_copilot_cache_hit_ratio", "Cache hit ratio (last 100 queries)")

# LLM metrics
LLM_CALL_COUNT = Counter(
    "devops_copilot_llm_calls_total",
    "Total LLM provider calls",
    ["provider", "status"]
)
LLM_LATENCY = Histogram(
    "devops_copilot_llm_latency_seconds",
    "LLM call latency",
    ["provider"],
    buckets=[1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
)
LLM_TOKEN_USAGE = Counter(
    "devops_copilot_llm_tokens_total",
    "Estimated token usage",
    ["provider"]
)

# Error metrics
ERROR_COUNT = Counter(
    "devops_copilot_errors_total",
    "Total errors encountered",
    ["error_type", "tool"]
)

# In-memory gauge state
_ACTIVE_QUERIES = Gauge("devops_copilot_active_queries", "Number of queries currently being processed")
_CACHE_SIZE = Gauge("devops_copilot_cache_size", "Number of entries in query cache")


# ---------------------------------------------------------------------------
# Metrics collector (singleton)
# ---------------------------------------------------------------------------
class MetricsCollector:
    _instance: Optional["MetricsCollector"] = None
    _lock = Lock()

    def __init__(self) -> None:
        self._cache_hit_buffer: list[bool] = []  # rolling window of last 100
        self._cache_lock = Lock()

    @classmethod
    def get_instance(cls) -> "MetricsCollector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # --- Request tracking ---
    def record_request(self, status: str, tool_used: Optional[str] = None) -> None:
        REQUEST_COUNT.labels(status=status, tool_used=tool_used or "none").inc()

    def record_latency(self, latency: float) -> None:
        REQUEST_LATENCY.observe(latency)

    def set_active_queries(self, count: int) -> None:
        _ACTIVE_QUERIES.set(count)

    # --- Tool tracking ---
    def record_tool_call(self, tool_name: str, status: str, latency: float) -> None:
        TOOL_CALL_COUNT.labels(tool_name=tool_name, status=status).inc()
        TOOL_LATENCY.labels(tool_name=tool_name).observe(latency)

    # --- Cache tracking ---
    def record_cache_hit(self) -> None:
        CACHE_HITS.inc()
        with self._cache_lock:
            self._cache_hit_buffer.append(True)
            if len(self._cache_hit_buffer) > 100:
                self._cache_hit_buffer.pop(0)
        self._update_cache_ratio()

    def record_cache_miss(self) -> None:
        CACHE_MISSES.inc()
        with self._cache_lock:
            self._cache_hit_buffer.append(False)
            if len(self._cache_hit_buffer) > 100:
                self._cache_hit_buffer.pop(0)
        self._update_cache_ratio()

    def set_cache_size(self, size: int) -> None:
        _CACHE_SIZE.set(size)

    def _update_cache_ratio(self) -> None:
        with self._cache_lock:
            if self._cache_hit_buffer:
                ratio = sum(self._cache_hit_buffer) / len(self._cache_hit_buffer)
                CACHE_HIT_RATIO.set(ratio)

    # --- LLM tracking ---
    def record_llm_call(self, provider: str, status: str, latency: float, tokens: int = 0) -> None:
        LLM_CALL_COUNT.labels(provider=provider, status=status).inc()
        LLM_LATENCY.labels(provider=provider).observe(latency)
        if tokens > 0:
            LLM_TOKEN_USAGE.labels(provider=provider).inc(tokens)

    # --- Error tracking ---
    def record_error(self, error_type: str, tool: str = "agent") -> None:
        ERROR_COUNT.labels(error_type=error_type, tool=tool).inc()


def get_metrics_collector() -> MetricsCollector:
    return MetricsCollector.get_instance()
