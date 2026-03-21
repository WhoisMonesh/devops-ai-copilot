# tests/test_llm_client.py - Comprehensive LLM client tests
from __future__ import annotations

import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Stub prometheus_client before importing metrics
def _stub_module(name: str, **attrs):
    import types
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod

_stub_module("prometheus_client", Counter=MagicMock(), Histogram=MagicMock(), Gauge=MagicMock(), Info=MagicMock(), CONTENT_TYPE_LATEST="text/plain; charset=utf-8", generate_latest=MagicMock())
_stub_module("requests", __version__="2.32.5")
_stub_module("httpx", __version__="0.27.2", Client=MagicMock(), AsyncClient=MagicMock())
_stub_module("boto3", __version__="1.34.0")
_stub_module("google.auth")
_stub_module("google.oauth2")
_stub_module("google.oauth2.service_account")
_stub_module("vertexai")
_stub_module("google.cloud.aiplatform")


class TestCircuitBreaker(unittest.TestCase):
    """Tests for the circuit breaker."""

    def test_initial_state_is_closed(self):
        from agent.llm_client import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.can_execute())

    def test_opens_after_failure_threshold(self):
        from agent.llm_client import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        for _ in range(3):
            cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.can_execute())

    def test_half_open_after_recovery_timeout(self):
        from agent.llm_client import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        time.sleep(0.15)
        self.assertTrue(cb.can_execute())
        self.assertEqual(cb.state, CircuitState.HALF)

    def test_half_open_success_closes_circuit(self):
        from agent.llm_client import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        cb.record_failure()
        time.sleep(0.1)
        cb.can_execute()  # transition to HALF
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_half_open_failure_reopens(self):
        from agent.llm_client import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        cb.record_failure()
        time.sleep(0.1)
        cb.can_execute()  # -> HALF
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_success_resets_failure_count(self):
        from agent.llm_client import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        cb.record_success()  # reset
        # One more failure should NOT open the circuit
        cb.record_failure()
        self.assertEqual(cb._failure_count, 1)
        self.assertTrue(cb.can_execute())


class TestRetryWithBackoff(unittest.TestCase):
    """Tests for the retry mechanism."""

    @patch("agent.llm_client._cb")
    @patch("time.sleep")
    def test_retries_on_failure(self, mock_sleep, mock_cb):
        from agent.llm_client import _retry, CircuitBreaker

        mock_cb.return_value = CircuitBreaker()

        attempts = []
        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise ValueError("not yet")
            return "success"

        result = _retry(flaky, "ollama", max_attempts=3, base_delay=0.01)
        self.assertEqual(result, "success")
        self.assertEqual(len(attempts), 3)
        mock_sleep.assert_called()  # sleeps between retries

    @patch("agent.llm_client._cb")
    def test_circuit_breaker_blocks(self, mock_cb):
        from agent.llm_client import _retry, CircuitBreaker, CircuitState

        cb = CircuitBreaker()
        cb._state = CircuitState.OPEN
        mock_cb.return_value = cb

        with self.assertRaises(RuntimeError) as ctx:
            _retry(lambda: "x", "ollama")
        self.assertIn("Circuit breaker", str(ctx.exception))

    @patch("agent.llm_client._cb")
    @patch("time.sleep")
    def test_all_attempts_fail_raises(self, mock_sleep, mock_cb):
        from agent.llm_client import _retry, CircuitBreaker
        mock_cb.return_value = CircuitBreaker()
        with self.assertRaises(RuntimeError) as ctx:
            _retry(lambda: (_ for _ in ()).throw(ValueError("bad")), "ollama", max_attempts=3, base_delay=0.01)
        self.assertIn("All 3 attempts failed", str(ctx.exception))


class TestHealthCache(unittest.TestCase):
    """Tests for the health check cache."""

    @patch("time.time")
    def test_cache_hit(self, mock_time):
        import agent.llm_client as lc

        lc._health_cache.clear()
        mock_time.return_value = 100.0

        check_called = []
        def check():
            check_called.append(1)
            return "ok"

        # First call
        result = lc._health_cached("test", check)
        self.assertEqual(result, "ok")
        self.assertEqual(len(check_called), 1)

        # Second call within TTL (same time)
        result = lc._health_cached("test", check)
        self.assertEqual(result, "ok")
        self.assertEqual(len(check_called), 1)  # cached, no new call

        # After TTL expires
        mock_time.return_value = 106.0
        result = lc._health_cached("test", check)
        self.assertEqual(len(check_called), 2)


class TestTokenEstimation(unittest.TestCase):
    """Tests for token estimation."""

    def test_estimate_tokens(self):
        from agent.llm_client import _est_tokens
        text = "one two three four five six seven eight nine ten"
        tokens = _est_tokens(text)  # 10 words -> ~13 tokens
        self.assertGreater(tokens, 0)

    def test_empty_text(self):
        from agent.llm_client import _est_tokens
        self.assertEqual(_est_tokens(""), 0)


class TestOllamaFunctions(unittest.TestCase):
    """Tests for Ollama-specific functions with mocked HTTP."""

    @patch("httpx.Client")
    @patch("agent.llm_client.config")
    def test_ollama_chat_success(self, mock_config, MockClient):
        mock_config.llm.ollama_base_url = "http://ollama:11434"
        mock_config.llm.ollama_model = "mistral"
        mock_config.llm.ollama_temperature = 0.7
        mock_config.llm.ollama_max_tokens = 2048
        mock_config.llm.ollama_timeout = 120

        mock_instance = MockClient.return_value.__enter__.return_value
        mock_instance.post.return_value.raise_for_status.return_value = None
        mock_instance.post.return_value.json.return_value = {
            "message": {"content": "Test response"}
        }

        from agent.llm_client import _ollama_chat
        result = _ollama_chat("hello")
        self.assertEqual(result, "Test response")

    @patch("httpx.Client")
    @patch("agent.llm_client.config")
    def test_ollama_health_ok(self, mock_config, MockClient):
        mock_config.llm.ollama_base_url = "http://ollama:11434"

        mock_instance = MockClient.return_value.__enter__.return_value
        mock_instance.get.return_value.raise_for_status.return_value = None
        mock_instance.get.return_value.status_code = 200

        from agent.llm_client import _ollama_health
        status = _ollama_health()
        self.assertEqual(status, "ok")

    @patch("httpx.Client")
    @patch("agent.llm_client.config")
    def test_ollama_health_error(self, mock_config, MockClient):
        mock_config.llm.ollama_base_url = "http://ollama:11434"

        mock_instance = MockClient.return_value.__enter__.return_value
        mock_instance.get.side_effect = Exception("connection refused")

        import agent.llm_client as lc
        lc._health_cache.clear()  # clear cache

        from agent.llm_client import _ollama_health
        status = _ollama_health()
        self.assertIn("connection refused", status)


class TestBedrockChat(unittest.TestCase):
    """Tests for Bedrock chat function."""

    @patch("agent.llm_client._bedrock_client")
    @patch("agent.llm_client.config")
    @patch("agent.llm_client._retry")
    def test_bedrock_anthropic_model(self, mock_retry, mock_config, mock_bedrock_client):
        mock_config.llm.bedrock_model_id = "anthropic.claude-3-sonnet-v1"
        mock_config.llm.bedrock_region = "us-east-1"
        mock_config.llm.bedrock_temperature = 0.7
        mock_config.llm.bedrock_max_tokens = 2048
        mock_config.llm.aws_access_key_id = ""
        mock_config.llm.aws_secret_access_key = ""
        mock_config.llm.aws_session_token = ""

        mock_retry.side_effect = lambda fn, p, **kw: fn()

        mock_client_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.__getitem__.return_value = {
            "body": MagicMock(read=MagicMock(return_value=b'{"content":[{"text":"bedrock response"}]}'))
        }
        mock_client_instance.invoke_model.return_value = mock_response
        mock_bedrock_client.return_value = mock_client_instance

        from agent.llm_client import _bedrock_chat
        result = _bedrock_chat("test prompt")
        self.assertEqual(result, "bedrock response")

    @patch("agent.llm_client._bedrock_client")
    @patch("agent.llm_client.config")
    @patch("agent.llm_client._retry")
    def test_bedrock_unsupported_model(self, mock_retry, mock_config, mock_bedrock_client):
        mock_config.llm.bedrock_model_id = "unknown.model"
        mock_config.llm.bedrock_region = "us-east-1"
        mock_config.llm.bedrock_temperature = 0.7
        mock_config.llm.bedrock_max_tokens = 2048
        mock_config.llm.aws_access_key_id = ""
        mock_config.llm.aws_secret_access_key = ""
        mock_config.llm.aws_session_token = ""

        mock_retry.side_effect = lambda fn, p, **kw: fn()

        from agent.llm_client import _bedrock_chat
        with self.assertRaises(ValueError) as ctx:
            _bedrock_chat("test")
        self.assertIn("Unsupported Bedrock model", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
