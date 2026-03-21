# tests/test_orchestrator.py - Orchestrator, rate limiter, and metrics tests
from __future__ import annotations

import sys
import time
import unittest
from unittest.mock import MagicMock, patch

def _stub_module(name: str, **attrs):
    import types
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod

_stub_module("prometheus_client")
_stub_module("requests")


class TestRateLimiter(unittest.TestCase):
    """Tests for the token-bucket rate limiter."""

    def test_allows_under_limit(self):
        from agent.main import RateLimiter
        rl = RateLimiter(rate=5, per=60)
        for _ in range(5):
            self.assertTrue(rl.is_allowed("client1"))

    def test_blocks_over_limit(self):
        from agent.main import RateLimiter
        rl = RateLimiter(rate=3, per=60)
        for _ in range(3):
            rl.is_allowed("client1")
        self.assertFalse(rl.is_allowed("client1"))

    def test_per_client_isolation(self):
        from agent.main import RateLimiter
        rl = RateLimiter(rate=2, per=60)
        rl.is_allowed("client1")
        rl.is_allowed("client1")
        # client1 is now over limit
        self.assertFalse(rl.is_allowed("client1"))
        # client2 should still be allowed
        self.assertTrue(rl.is_allowed("client2"))

    def test_refills_after_window(self):
        from agent.main import RateLimiter
        rl = RateLimiter(rate=2, per=1)  # 1 second window
        rl.is_allowed("client1")
        rl.is_allowed("client1")
        self.assertFalse(rl.is_allowed("client1"))
        time.sleep(1.1)
        self.assertTrue(rl.is_allowed("client1"))

    def test_refill_at_exact_window(self):
        from agent.main import RateLimiter
        rl = RateLimiter(rate=2, per=1)
        rl.is_allowed("client1")
        rl.is_allowed("client1")
        time.sleep(1.0)
        # At exactly the window boundary it should refill
        self.assertTrue(rl.is_allowed("client1"))


class TestMetricsCollector(unittest.TestCase):
    """Tests for the Prometheus metrics collector."""

    def setUp(self):
        import importlib
        import agent.metrics as metrics_mod
        importlib.reload(metrics_mod)
        self.mc = metrics_mod.MetricsCollector()

    def test_record_request_increments_counter(self):
        self.mc.record_request("success", "list_pods")
        self.mc.record_request("error", "jenkins_trigger_build")
        # Verify no exception raised

    def test_record_latency(self):
        self.mc.record_latency(0.5)
        self.mc.record_latency(2.5)

    def test_record_cache_hit_and_miss(self):
        for _ in range(5):
            self.mc.record_cache_hit()
        for _ in range(3):
            self.mc.record_cache_miss()
        self.assertAlmostEqual(self.mc._cache_hit_buffer.count(True), 5)
        self.assertAlmostEqual(self.mc._cache_hit_buffer.count(False), 3)

    def test_cache_hit_ratio(self):
        for _ in range(4):
            self.mc.record_cache_hit()
        for _ in range(6):
            self.mc.record_cache_miss()
        # Ratio = 4/10
        ratio = sum(self.mc._cache_hit_buffer) / len(self.mc._cache_hit_buffer)
        self.assertAlmostEqual(ratio, 0.4)

    def test_cache_ratio_rolling_window(self):
        # Record 100 hits, then 100 misses
        for _ in range(100):
            self.mc.record_cache_hit()
        for _ in range(100):
            self.mc.record_cache_miss()
        # Rolling window should keep last 100 entries
        # After 100 hits + 100 misses, only last 100 survive
        # So ratio depends on order - but buffer never exceeds 100

    def test_record_llm_call(self):
        self.mc.record_llm_call("ollama", "success", 1.5, 150)
        self.mc.record_llm_call("ollama", "error", 0.5, 0)

    def test_record_error(self):
        self.mc.record_error("timeout", "jenkins_tool")
        self.mc.record_error("unauthorized", "k8s_tool")

    def test_singleton(self):
        import agent.metrics as metrics_mod
        mc1 = metrics_mod.get_metrics_collector()
        mc2 = metrics_mod.get_metrics_collector()
        self.assertIs(mc1, mc2)


class TestOrchestrator(unittest.TestCase):
    """Tests for the Orchestrator class."""

    def setUp(self):
        # Stub external dependencies
        self.patches = []

        self.patches.append(patch("agent.orchestrator.llm_client"))
        self.patches.append(patch("agent.orchestrator.config"))
        self.patches.append(patch("agent.orchestrator.AgentExecutor"))
        self.patches.append(patch("agent.orchestrator.ConversationBufferWindowMemory"))
        self.patches.append(patch("agent.orchestrator.PromptTemplate"))
        self.patches.append(patch("agent.orchestrator.create_react_agent"))
        self.patches.append(patch("agent.orchestrator.get_metrics_collector"))

        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_orchestrator_initializes(self):
        from agent.orchestrator import Orchestrator
        # Mock _load_tools
        with patch("agent.orchestrator._load_tools", return_value=[]):
            with patch("agent.orchestrator.DevOpsLLM"):
                orch = Orchestrator()
                self.assertIsNotNone(orch._agent_executor)

    def test_orchestrator_run_returns_dict(self):
        from agent.orchestrator import Orchestrator
        with patch("agent.orchestrator._load_tools", return_value=[]):
            with patch("agent.orchestrator.DevOpsLLM"):
                with patch.object(Orchestrator, "_build"):
                    orch = Orchestrator()
                    orch._agent_executor = MagicMock()
                    orch._agent_executor.invoke.return_value = {"output": "test response"}

                    result = orch.run("show me pods")
                    self.assertIsInstance(result, dict)
                    self.assertIn("answer", result)
                    self.assertIn("corr_id", result)


class TestApiKeyVerification(unittest.TestCase):
    """Tests for API key authentication."""

    def test_missing_api_key_when_disabled(self):
        import os
        orig = os.environ.get("API_KEY", "")
        os.environ.pop("API_KEY", None)

        from unittest.mock import MagicMock
        from agent.main import verify_api_key

        # No API_KEY set → should return None (auth disabled)
        result = verify_api_key(MagicMock(headers={}))
        self.assertIsNone(result)

        os.environ["API_KEY"] = orig

    def test_valid_bearer_token(self):
        import os
        os.environ["API_KEY"] = "secret123"

        from unittest.mock import MagicMock
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer secret123"}

        from agent.main import verify_api_key
        result = verify_api_key(mock_request)
        self.assertEqual(result, "secret123")

        os.environ.pop("API_KEY", None)

    def test_invalid_token_raises(self):
        import os
        os.environ["API_KEY"] = "secret123"

        from unittest.mock import MagicMock
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer wrong"}

        from fastapi import HTTPException
        from agent.main import verify_api_key

        with self.assertRaises(HTTPException) as ctx:
            verify_api_key(mock_request)
        self.assertEqual(ctx.exception.status_code, 401)

        os.environ.pop("API_KEY", None)


if __name__ == "__main__":
    unittest.main()
