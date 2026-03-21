# tests/test_cache.py - Comprehensive cache tests
from __future__ import annotations

import sys
import threading
import time
import unittest

# Stub modules
def _stub_module(name: str, **attrs):
    import types
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod

_stub_module("prometheus_client")


class TestCacheEntry(unittest.TestCase):
    """Tests for CacheEntry."""

    def test_expires_after_ttl(self):
        from agent.cache import CacheEntry
        entry = CacheEntry("value", ttl_seconds=1)
        self.assertFalse(entry.is_expired())
        time.sleep(1.1)
        self.assertTrue(entry.is_expired())

    def test_not_expired_before_ttl(self):
        from agent.cache import CacheEntry
        entry = CacheEntry("value", ttl_seconds=5)
        self.assertFalse(entry.is_expired())


class TestTTLCache(unittest.TestCase):
    """Tests for TTLCache."""

    def setUp(self):
        from agent.cache import TTLCache
        self.cache = TTLCache(default_ttl=2, max_size=10)

    def test_set_and_get(self):
        self.cache.set("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")

    def test_get_nonexistent(self):
        self.assertIsNone(self.cache.get("nonexistent"))

    def test_get_expired(self):
        self.cache.set("key1", "value1", ttl=1)
        time.sleep(1.1)
        self.assertIsNone(self.cache.get("key1"))

    def test_delete(self):
        self.cache.set("key1", "value1")
        self.cache.delete("key1")
        self.assertIsNone(self.cache.get("key1"))

    def test_delete_nonexistent(self):
        # Should not raise
        self.cache.delete("nonexistent")

    def test_clear(self):
        self.cache.set("k1", "v1")
        self.cache.set("k2", "v2")
        self.cache.clear()
        self.assertIsNone(self.cache.get("k1"))
        self.assertIsNone(self.cache.get("k2"))
        self.assertEqual(self.cache.size, 0)

    def test_size(self):
        for i in range(5):
            self.cache.set(f"key{i}", f"val{i}")
        self.assertEqual(self.cache.size, 5)

    def test_hit_ratio(self):
        self.cache.set("k1", "v1")
        self.cache.get("k1")   # hit
        self.cache.get("k2")   # miss
        self.cache.get("k3")   # miss
        self.assertAlmostEqual(self.cache.hit_ratio, 1/3, places=2)

    def test_hit_ratio_empty(self):
        self.assertEqual(self.cache.hit_ratio, 0.0)

    def test_max_size_eviction(self):
        cache = self.cache
        cache._max_size = 3
        for i in range(5):
            cache.set(f"key{i}", f"val{i}")
        # At least one old key should be evicted
        stored = [cache.get(f"key{i}") for i in range(5)]
        self.assertLess(sum(1 for v in stored if v is not None), 5)

    def test_cleanup_expired(self):
        self.cache.set("k1", "v1", ttl=1)
        self.cache.set("k2", "v2", ttl=10)
        time.sleep(1.1)
        evicted = self.cache.cleanup_expired()
        self.assertEqual(evicted, 1)
        self.assertIsNone(self.cache.get("k1"))
        self.assertEqual(self.cache.get("k2"), "v2")

    def test_thread_safety(self):
        """Verify no race conditions under concurrent access."""
        from agent.cache import TTLCache
        cache = TTLCache(default_ttl=60, max_size=500)
        errors = []

        def writer(n):
            try:
                for i in range(50):
                    cache.set(f"k{n}_{i}", f"v{n}_{i}")
            except Exception as e:
                errors.append(e)

        def reader(n):
            try:
                for i in range(50):
                    cache.get(f"k{n}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        threads += [threading.Thread(target=reader, args=(i,)) for i in range(5, 10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread safety errors: {errors}")

    def test_cache_key_normalization(self):
        from agent.cache import _question_cache_key
        key1 = _question_cache_key("Show me pods", "session1")
        key2 = _question_cache_key("show me pods", "session1")
        self.assertEqual(key1, key2)  # case-insensitive


class TestConfigureCache(unittest.TestCase):
    """Tests for cache configuration."""

    def test_configure_ttl(self):
        from agent.cache import configure_cache, QUERY_CACHE, TOOL_CACHE
        orig_q_ttl = QUERY_CACHE._default_ttl
        configure_cache(ttl=600)
        self.assertEqual(QUERY_CACHE._default_ttl, 600)
        self.assertEqual(TOOL_CACHE._default_ttl, 120)  # 1/5 of 600
        configure_cache(ttl=orig_q_ttl)  # restore

    def test_configure_max_size(self):
        from agent.cache import configure_cache, QUERY_CACHE, TOOL_CACHE
        orig_max = QUERY_CACHE._max_size
        configure_cache(max_size=1000)
        self.assertEqual(QUERY_CACHE._max_size, 1000)
        self.assertEqual(TOOL_CACHE._max_size, 500)  # half
        configure_cache(max_size=orig_max)  # restore


if __name__ == "__main__":
    unittest.main()
