# tests/test_tools.py - Comprehensive tool tests
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

def _stub_module(name: str, **attrs):
    import types
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod

_stub_module("boto3", __version__="1.34.0")
_stub_module("requests", __version__="2.32.5", HTTPError=Exception, Response=MagicMock(), Session=MagicMock())
_stub_module("httpx", __version__="0.27.2")


class TestJenkinsTools(unittest.TestCase):
    """Tests for Jenkins tool helpers."""

    def setUp(self):
        from agent.tools.jenkins_tools import _client
        self._client_fn = _client

    def test_client_returns_url_and_auth(self):
        with patch("agent.tools.jenkins_tools.secrets") as mock_secrets:
            mock_secrets.jenkins.all.return_value = {
                "url": "http://jenkins.test",
                "username": "admin",
                "api_token": "token123",
            }
            url, auth = self._client_fn()
            self.assertEqual(url, "http://jenkins.test")
            self.assertEqual(auth, ("admin", "token123"))

    @patch("agent.tools.jenkins_tools.requests.get")
    @patch("agent.tools.jenkins_tools.secrets")
    def test_list_jobs_success(self, mock_secrets, mock_get):
        mock_secrets.jenkins.all.return_value = {
            "url": "http://jenkins.test", "username": "u", "api_token": "t",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"jobs": [{"name": "build-app", "color": "blue"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from agent.tools.jenkins_tools import jenkins_list_jobs
        result = jenkins_list_jobs.invoke({})
        self.assertEqual(result[0]["name"], "build-app")

    @patch("agent.tools.jenkins_tools.requests.get")
    @patch("agent.tools.jenkins_tools.secrets")
    def test_list_jobs_error(self, mock_secrets, mock_get):
        mock_secrets.jenkins.all.return_value = {
            "url": "http://jenkins.test", "username": "u", "api_token": "t",
        }
        mock_get.side_effect = Exception("connection refused")

        from agent.tools.jenkins_tools import jenkins_list_jobs
        result = jenkins_list_jobs.invoke({})
        self.assertIn("error", str(result))


class TestKibanaTools(unittest.TestCase):
    """Tests for Kibana/Elasticsearch tool helpers."""

    @patch("agent.tools.kibana_tool.requests.get")
    @patch("agent.tools.kibana_tool.secrets")
    def test_cluster_health(self, mock_secrets, mock_get):
        mock_secrets.kibana.all.return_value = {
            "url": "http://kibana.test",
            "username": "elastic",
            "password": "pass",
            "elasticsearch_url": "http://es.test",
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "green", "cluster_name": "devops"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from agent.tools.kibana_tool import kibana_cluster_health
        result = kibana_cluster_health.invoke({})
        self.assertEqual(result.get("status"), "green")


class TestCloudWatchTools(unittest.TestCase):
    """Tests for CloudWatch tools."""

    @patch("agent.tools.cloudwatch_tool.boto3.client")
    def test_cloudwatch_logs_no_results(self, mock_boto):
        mock_client = MagicMock()
        mock_client.filter_log_events.return_value = {"events": []}
        mock_boto.return_value = mock_client

        from agent.tools.cloudwatch_tool import cloudwatch_logs
        result = cloudwatch_logs.invoke({
            "log_group": "/aws/lambda/test",
            "filter_pattern": "ERROR",
            "hours": 1,
            "limit": 50,
        })
        self.assertIn("No CloudWatch logs found", result)

    @patch("agent.tools.cloudwatch_tool.boto3.client")
    def test_cloudwatch_logs_with_events(self, mock_boto):
        import time
        mock_client = MagicMock()
        now_ms = int(time.time() * 1000)
        mock_client.filter_log_events.return_value = {
            "events": [
                {"timestamp": now_ms - 60000, "message": "ERROR: test error"},
            ]
        }
        mock_boto.return_value = mock_client

        from agent.tools.cloudwatch_tool import cloudwatch_logs
        result = cloudwatch_logs.invoke({
            "log_group": "/aws/lambda/test",
            "hours": 1,
            "limit": 50,
        })
        self.assertIn("CloudWatch Logs:", result)
        self.assertIn("ERROR: test error", result)

    @patch("agent.tools.cloudwatch_tool.boto3.client")
    def test_cloudtrail_events(self, mock_boto):
        mock_client = MagicMock()
        mock_client.lookup_events.return_value = {
            "Events": [
                {
                    "EventTime": "2024-01-01T12:00:00Z",
                    "EventName": "DescribeInstances",
                    "Username": "admin",
                }
            ]
        }
        mock_boto.return_value = mock_client

        from agent.tools.cloudwatch_tool import cloudtrail_events
        result = cloudtrail_events.invoke({"hours": 1})
        self.assertIn("CloudTrail Events", result)
        self.assertIn("DescribeInstances", result)

    @patch("agent.tools.cloudwatch_tool.boto3.client")
    def test_cloudwatch_alarms(self, mock_boto):
        mock_client = MagicMock()
        mock_client.describe_alarms.return_value = {
            "MetricAlarms": [
                {
                    "AlarmName": "HighCPU",
                    "StateValue": "ALARM",
                    "Namespace": "AWS/EC2",
                    "MetricName": "CPUUtilization",
                    "StateReason": "Threshold crossed",
                }
            ]
        }
        mock_boto.return_value = mock_client

        from agent.tools.cloudwatch_tool import cloudwatch_alarms
        result = cloudwatch_alarms.invoke({})
        self.assertIn("HighCPU", result)
        self.assertIn("ALARM", result)


class TestSSLTools(unittest.TestCase):
    """Tests for SSL/TLS tools."""

    @patch("agent.tools.ssl_tool.socket.create_connection")
    @patch("agent.tools.ssl_tool.ssl.wrap_socket")
    @patch("agent.tools.ssl_tool.crypto.load_certificate")
    def test_ssl_check_host_expired(self, mock_load_cert, mock_wrap, mock_create_conn):
        mock_sock = MagicMock()
        mock_create_conn.return_value.__enter__.return_value = mock_sock

        mock_x509 = MagicMock()
        mock_x509.get_subject.return_value.get_components.return_value = [(b"CN", b"example.com")]
        mock_x509.get_issuer.return_value.get_components.return_value = [(b"CN", b"DigiCert")]
        mock_x509.get_serial_number.return_value = 12345
        mock_x509.get_notBefore.return_value = b"20200101000000Z"
        mock_x509.get_notAfter.return_value = b"20210101000000Z"   # expired
        mock_x509.get_version.return_value = 3
        mock_x509.get_signature_algorithm.return_value = b"sha256WithRSAEncryption"
        mock_load_cert.return_value = mock_x509

        from agent.tools.ssl_tool import ssl_check_host
        result = ssl_check_host.invoke({"host": "example.com"})
        self.assertIn("EXPIRED", result)

    @patch("agent.tools.ssl_tool.socket.create_connection")
    @patch("agent.tools.ssl_tool.ssl.wrap_socket")
    @patch("agent.tools.ssl_tool.crypto.load_certificate")
    def test_ssl_check_host_ok(self, mock_load_cert, mock_wrap, mock_create_conn):
        from datetime import datetime, timedelta
        mock_sock = MagicMock()
        mock_create_conn.return_value.__enter__.return_value = mock_sock

        future = (datetime.utcnow() + timedelta(days=180)).strftime("%Y%m%d%H%M%SZ").encode()

        mock_x509 = MagicMock()
        mock_x509.get_subject.return_value.get_components.return_value = [(b"CN", b"example.com")]
        mock_x509.get_issuer.return_value.get_components.return_value = [(b"CN", b"Let's Encrypt")]
        mock_x509.get_serial_number.return_value = 12345
        mock_x509.get_notBefore.return_value = b"20230101000000Z"
        mock_x509.get_notAfter.return_value = future
        mock_x509.get_version.return_value = 3
        mock_x509.get_signature_algorithm.return_value = b"sha256WithRSAEncryption"
        mock_load_cert.return_value = mock_x509

        from agent.tools.ssl_tool import ssl_check_host
        result = ssl_check_host.invoke({"host": "example.com"})
        self.assertIn("OK", result)


class TestPagerDutyTools(unittest.TestCase):
    """Tests for PagerDuty tools."""

    @patch("agent.tools.pagerduty_tool.requests.get")
    def test_pd_list_incidents(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "incidents": [
                {
                    "id": "P123",
                    "title": "High CPU",
                    "urgency": "high",
                    "created_at": "2024-01-01T12:00:00Z",
                    "service": {"name": "webapp"},
                    "assignments": [{"assignee": {"summary": "alice"}}],
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from agent.tools.pagerduty_tool import pd_list_incidents
        result = pd_list_incidents.invoke({"status": "triggered"})
        self.assertIn("High CPU", result)
        self.assertIn("P123", result)

    @patch("agent.tools.pagerduty_tool.requests.get")
    def test_pd_get_oncall(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "oncalls": [
                {
                    "escalation_policy": {"summary": "Primary"},
                    "user": {"summary": "bob"},
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from agent.tools.pagerduty_tool import pd_get_oncall
        result = pd_get_oncall.invoke({})
        self.assertIn("bob", result)
        self.assertIn("Primary", result)


class TestGitHubTools(unittest.TestCase):
    """Tests for GitHub tools."""

    @patch("agent.tools.github_tool.requests.get")
    def test_github_list_workflow_runs(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "workflow_runs": [
                {
                    "name": "CI",
                    "status": "completed",
                    "conclusion": "success",
                    "run_number": 42,
                    "head_branch": "main",
                    "created_at": "2024-01-01T12:00:00Z",
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from agent.tools.github_tool import github_list_workflow_runs
        result = github_list_workflow_runs.invoke({})
        self.assertIn("CI", result)
        self.assertIn("42", result)

    @patch("agent.tools.github_tool.requests.get")
    def test_github_get_repo_info(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "full_name": "org/repo",
            "description": "A cool repo",
            "visibility": "public",
            "default_branch": "main",
            "stargazers_count": 100,
            "forks_count": 20,
            "open_issues_count": 5,
            "language": "Python",
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "html_url": "https://github.com/org/repo",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from agent.tools.github_tool import github_get_repo_info
        result = github_get_repo_info.invoke({})
        self.assertIn("org/repo", result)
        self.assertIn("100", result)


class TestPermissionsToolClassifications(unittest.TestCase):
    """Tests that tool names are correctly classified in permissions."""

    def test_all_tools_in_tools_init_are_in_permissions(self):
        """Verify all tools in __init__.py have a permission classification."""
        from agent.permissions import TOOL_CLASSIFICATIONS

        # Import tool lists from __init__
        from importlib import import_module
        tools_mod = import_module("agent.tools")

        # Collect all tool names
        all_tool_names = set()
        for attr_name in dir(tools_mod):
            if attr_name.isupper() and attr_name.endswith("_TOOLS"):
                tool_list = getattr(tools_mod, attr_name)
                if isinstance(tool_list, list):
                    for t in tool_list:
                        all_tool_names.add(t.name)

        # Check each has a classification
        unclassified = []
        for name in all_tool_names:
            if name not in TOOL_CLASSIFICATIONS:
                unclassified.append(name)

        self.assertEqual(
            unclassified, [],
            f"Unclassified tools: {unclassified}",
        )


if __name__ == "__main__":
    unittest.main()
