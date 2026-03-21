# tests/test_tools.py
# Unit tests for DevOps AI Copilot tools (offline / mocked)

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stubs so imports don't require real AWS / K8s credentials
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Stub boto3
boto3_stub = _stub_module("boto3")
boto3_stub.session = _stub_module("boto3.session")

# Stub kubernetes
kube_stub = _stub_module("kubernetes")
kube_stub.config = MagicMock()
kube_stub.client = MagicMock()
_stub_module("kubernetes.config")
_stub_module("kubernetes.client")

# Stub requests
requests_stub = _stub_module("requests")

# Stub agent.secrets
secrets_stub = _stub_module("agent.secrets")
secrets_stub.jenkins = MagicMock()
secrets_stub.jenkins.all.return_value = {
    "url": "http://jenkins.test",
    "username": "admin",
    "api_token": "token123",
}
secrets_stub.kibana = MagicMock()
secrets_stub.kibana.all.return_value = {
    "url": "http://kibana.test",
    "username": "elastic",
    "password": "pass",
    "elasticsearch_url": "http://es.test",
}
secrets_stub.artifactory = MagicMock()
secrets_stub.artifactory.all.return_value = {
    "url": "http://artifactory.test",
    "username": "admin",
    "api_key": "key123",
}


class TestJenkinsTools(unittest.TestCase):
    """Tests for Jenkins tool helpers."""

    def setUp(self):
        # Import after stubs are in place
        from agent.tools.jenkins_tools import _client
        self._client = _client

    def test_client_returns_url_and_auth(self):
        url, auth = self._client()
        self.assertEqual(url, "http://jenkins.test")
        self.assertEqual(auth, ("admin", "token123"))

    @patch("agent.tools.jenkins_tools.requests.get")
    def test_list_jobs_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"jobs": [{"name": "build-app", "color": "blue"}]}
        mock_get.return_value = mock_resp

        from agent.tools.jenkins_tools import jenkins_list_jobs
        result = jenkins_list_jobs.invoke({})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "build-app")

    @patch("agent.tools.jenkins_tools.requests.get")
    def test_list_jobs_error(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        from agent.tools.jenkins_tools import jenkins_list_jobs
        result = jenkins_list_jobs.invoke({})
        self.assertIn("error", result[0])


class TestKibanaTools(unittest.TestCase):
    """Tests for Kibana/Elasticsearch tool helpers."""

    @patch("agent.tools.kibana_tool.requests.get")
    def test_health_check(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "green", "cluster_name": "devops"}
        mock_get.return_value = mock_resp

        from agent.tools.kibana_tool import kibana_cluster_health
        result = kibana_cluster_health.invoke({})
        self.assertEqual(result.get("status"), "green")


class TestSecretsModule(unittest.TestCase):
    """Tests for the secrets TTL cache."""

    def test_service_secrets_is_configured_false_when_no_env(self):
        from agent.secrets import _ServiceSecrets
        svc = _ServiceSecrets("__NONEXISTENT_ENV_VAR__", "Test")
        self.assertFalse(svc.is_configured())

    def test_service_secrets_get_returns_default(self):
        from agent.secrets import _ServiceSecrets
        svc = _ServiceSecrets("__NONEXISTENT_ENV_VAR__", "Test")
        self.assertIsNone(svc.get("url"))
        self.assertEqual(svc.get("url", "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
