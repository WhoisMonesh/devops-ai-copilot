# agent/cache.py - Query and tool result caching layer

import hashlib
import json
import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------
class CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl_seconds: int) -> None:
        self.value = value
        self.expires_at = time.time() + ttl_seconds

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


# ---------------------------------------------------------------------------
# TTLCache - thread-safe TTL cache
# ---------------------------------------------------------------------------
class TTLCache:
    """Thread-safe in-memory cache with TTL and LRU-like behaviour."""

    def __init__(self, default_ttl: int = 300, max_size: int = 500) -> None:
        self._store: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    # ---- basic operations ----------------------------------------------------
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired():
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            if len(self._store) >= self._max_size and key not in self._store:
                self._evict_oldest()
            self._store[key] = CacheEntry(value, ttl or self._default_ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    # ---- stats ----------------------------------------------------------------
    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def hit_ratio(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def _evict_oldest(self) -> None:
        """Evict the oldest expired entry, or a random entry if none expired."""
        if not self._store:
            return
        # Try to find expired entries first
        now = time.time()
        expired = [k for k, e in self._store.items() if now > e.expires_at]
        if expired:
            for k in expired[:5]:  # evict up to 5 expired
                del self._store[k]
        else:
            # Fallback: remove a random entry (cache is full)
            oldest_key = next(iter(self._store))
            del self._store[oldest_key]

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of evicted entries."""
        with self._lock:
            before = len(self._store)
            self._store = {
                k: e for k, e in self._store.items() if not e.is_expired()
            }
            return before - len(self._store)


# ---------------------------------------------------------------------------
# Cache key builders
# ---------------------------------------------------------------------------
def _normalize_question(q: str) -> str:
    return q.strip().lower()

def _question_cache_key(question: str, session_id: str = "default") -> str:
    norm = _normalize_question(question)
    return f"q:{session_id}:{hashlib.sha256(norm.encode()).hexdigest()[:16]}"

def _tool_cache_key(tool_name: str, **kwargs) -> str:
    params = json.dumps(kwargs, sort_keys=True)
    return f"t:{tool_name}:{hashlib.sha256(params.encode()).hexdigest()[:16]}"


# ---------------------------------------------------------------------------
# Global caches
# ---------------------------------------------------------------------------
QUERY_CACHE = TTLCache(default_ttl=300, max_size=500)   # 5-minute TTL for LLM responses
TOOL_CACHE = TTLCache(default_ttl=60, max_size=200)    # 1-minute TTL for tool results


# ---------------------------------------------------------------------------
# Cache control API (hot-reload aware)
# ---------------------------------------------------------------------------
def configure_cache(ttl: Optional[int] = None, max_size: Optional[int] = None) -> dict:
    if ttl is not None:
        QUERY_CACHE._default_ttl = ttl
        TOOL_CACHE._default_ttl = max(15, ttl // 5)  # tool cache shorter
    if max_size is not None:
        QUERY_CACHE._max_size = max_size
        TOOL_CACHE._max_size = max(max_size // 2, 50)
    return {
        "query_cache_ttl": QUERY_CACHE._default_ttl,
        "query_cache_max_size": QUERY_CACHE._max_size,
        "tool_cache_ttl": TOOL_CACHE._default_ttl,
        "tool_cache_max_size": TOOL_CACHE._max_size,
    }


def invalidate_caches() -> None:
    QUERY_CACHE.clear()
    TOOL_CACHE.clear()
    logger.info("All caches invalidated")
