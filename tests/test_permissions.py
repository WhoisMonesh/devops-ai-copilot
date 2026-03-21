# tests/test_permissions.py - Comprehensive permission system tests
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

# Stub boto3/kube/secrets before any imports
def _stub_module(name: str, **attrs):
    import types
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod

_stub_module("boto3")
_stub_module("requests")

# Stub agent.secrets
secrets_stub = _stub_module("agent.secrets")
secrets_stub.jenkins = MagicMock()
secrets_stub.jenkins.all.return_value = {"url": "http://jenkins.test", "username": "admin", "api_token": "tok"}
secrets_stub.kibana = MagicMock()
secrets_stub.kibana.all.return_value = {"url": "http://kibana.test", "username": "e", "password": "p"}
secrets_stub.artifactory = MagicMock()
secrets_stub.artifactory.all.return_value = {"url": "http://artifactory.test", "username": "a", "api_key": "k"}
secrets_stub.nginx = MagicMock()
secrets_stub.nginx.all.return_value = {"url": "http://nginx.test", "username": "u", "password": "p"}
secrets_stub.vertexai = MagicMock()
secrets_stub.vertexai.is_configured.return_value = True
secrets_stub.bedrock = MagicMock()
secrets_stub.bedrock.is_configured.return_value = True
secrets_stub.invalidate = MagicMock()


class TestPermissions(unittest.TestCase):
    """Tests for the permissions system."""

    def setUp(self):
        # Re-import to get clean module state
        import importlib
        import agent.permissions as perms_mod
        importlib.reload(perms_mod)
        self.perms = perms_mod
        # Reset global state
        perms_mod._permissions.denied_tools.clear()
        perms_mod._permissions.mode = perms_mod.OperationMode.READ_WRITE
        perms_mod._permissions.safe_mode_allowed_tools.clear()
        perms_mod._permissions.read_only_allowed_tools.clear()

    # ---- OperationMode ----
    def test_operation_mode_enum_values(self):
        self.assertEqual(self.perms.OperationMode.READ_ONLY.value, "read_only")
        self.assertEqual(self.perms.OperationMode.READ_WRITE.value, "read_write")
        self.assertEqual(self.perms.OperationMode.SAFE_MODE.value, "safe_mode")

    # ---- set_mode_from_string ----
    def test_set_mode_from_string_valid(self):
        for mode_str, expected in [
            ("read_only",   self.perms.OperationMode.READ_ONLY),
            ("readonly",    self.perms.OperationMode.READ_ONLY),
            ("read_write",  self.perms.OperationMode.READ_WRITE),
            ("readwrite",   self.perms.OperationMode.READ_WRITE),
            ("read-write",  self.perms.OperationMode.READ_WRITE),
            ("safe_mode",   self.perms.OperationMode.SAFE_MODE),
            ("safemode",    self.perms.OperationMode.SAFE_MODE),
        ]:
            result = self.perms.set_mode_from_string(mode_str)
            self.assertTrue(result, f"Failed for '{mode_str}'")
            self.assertEqual(self.perms._permissions.mode, expected, f"Failed for '{mode_str}'")

    def test_set_mode_from_string_invalid(self):
        result = self.perms.set_mode_from_string("invalid_mode")
        self.assertFalse(result)

    # ---- Tool classification ----
    def test_default_classifications_exist(self):
        self.assertEqual(self.perms.TOOL_CLASSIFICATIONS["list_pods"], self.perms.OperationType.READ)
        self.assertEqual(self.perms.TOOL_CLASSIFICATIONS["delete_pod"], self.perms.OperationType.DELETE)
        self.assertEqual(self.perms.TOOL_CLASSIFICATIONS["scale_deployment"], self.perms.OperationType.WRITE)
        self.assertEqual(self.perms.TOOL_CLASSIFICATIONS["jenkins_trigger_build"], self.perms.OperationType.WRITE)
        self.assertEqual(self.perms.TOOL_CLASSIFICATIONS["terraform_apply"], self.perms.OperationType.WRITE)
        self.assertEqual(self.perms.TOOL_CLASSIFICATIONS["terraform_destroy"], self.perms.OperationType.DELETE)
        self.assertEqual(self.perms.TOOL_CLASSIFICATIONS["redis_flush_db"], self.perms.OperationType.DELETE)

    def test_unknown_tool_defaults_to_read(self):
        op_type = self.perms._permissions.get_operation_type("nonexistent_tool")
        self.assertEqual(op_type, self.perms.OperationType.READ)

    # ---- Deny list ----
    def test_add_deny_tool(self):
        self.perms.add_deny_tool("delete_pod")
        self.assertIn("delete_pod", self.perms._permissions.denied_tools)
        # Idempotent
        self.perms.add_deny_tool("delete_pod")
        self.assertEqual(len(self.perms._permissions.denied_tools), 1)

    def test_remove_deny_tool(self):
        self.perms.add_deny_tool("delete_pod")
        self.perms.remove_deny_tool("delete_pod")
        self.assertNotIn("delete_pod", self.perms._permissions.denied_tools)

    # ---- READ_ONLY mode ----
    def test_read_only_allows_read(self):
        self.perms.set_mode_from_string("read_only")
        allowed, reason = self.perms.check_tool_permission("list_pods")
        self.assertTrue(allowed)
        self.assertIn("READ", reason)

    def test_read_only_blocks_write(self):
        self.perms.set_mode_from_string("read_only")
        allowed, reason = self.perms.check_tool_permission("jenkins_trigger_build")
        self.assertFalse(allowed)
        self.assertIn("write", reason)

    def test_read_only_blocks_delete(self):
        self.perms.set_mode_from_string("read_only")
        allowed, reason = self.perms.check_tool_permission("delete_pod")
        self.assertFalse(allowed)
        self.assertIn("delete", reason)

    # ---- READ_WRITE mode ----
    def test_read_write_allows_everything_except_denied(self):
        self.perms.set_mode_from_string("read_write")
        for tool, op_type in self.perms.TOOL_CLASSIFICATIONS.items():
            allowed, _ = self.perms.check_tool_permission(tool)
            self.assertTrue(allowed, f"READ_WRITE should allow {tool} ({op_type})")

    def test_read_write_denied_tool_still_blocked(self):
        self.perms.set_mode_from_string("read_write")
        self.perms.add_deny_tool("jenkins_trigger_build")
        allowed, reason = self.perms.check_tool_permission("jenkins_trigger_build")
        self.assertFalse(allowed)
        self.assertIn("explicitly denied", reason)

    # ---- SAFE_MODE ----
    def test_safe_mode_allows_read(self):
        self.perms.set_mode_from_string("safe_mode")
        allowed, _ = self.perms.check_tool_permission("list_pods")
        self.assertTrue(allowed)

    def test_safe_mode_blocks_delete(self):
        self.perms.set_mode_from_string("safe_mode")
        allowed, reason = self.perms.check_tool_permission("delete_pod")
        self.assertFalse(allowed)
        self.assertIn("DELETE", reason)
        self.assertIn("SAFE_MODE", reason)

    def test_safe_mode_blocks_execute(self):
        self.perms.set_mode_from_string("safe_mode")
        allowed, reason = self.perms.check_tool_permission("terraform_plan")
        self.assertFalse(allowed)
        self.assertIn("EXECUTE", reason)

    def test_safe_mode_allows_write_by_default(self):
        self.perms.set_mode_from_string("safe_mode")
        allowed, reason = self.perms.check_tool_permission("scale_deployment")
        self.assertTrue(allowed)

    def test_safe_mode_restricts_to_allowed_list(self):
        self.perms.set_mode_from_string("safe_mode")
        self.perms._permissions.safe_mode_allowed_tools = {"list_pods", "get_pod_logs"}
        allowed, _ = self.perms.check_tool_permission("list_pods")
        self.assertTrue(allowed)
        allowed2, reason2 = self.perms.check_tool_permission("describe_pod")
        self.assertFalse(allowed2)
        self.assertIn("not in the SAFE_MODE allowed list", reason2)

    # ---- Audit logging ----
    @patch("builtins.open", MagicMock())
    @patch("os.makedirs", MagicMock())
    def test_audit_log_writes_entry(self):
        self.perms.audit_log(
            tool_name="delete_pod",
            operation="delete",
            mode="read_only",
            allowed=False,
            details="blocked",
        )
        # Verify no exception raised

    # ---- PermissionMiddleware ----
    def test_permission_middleware_run_with_permission_check_blocks(self):
        mock_orchestrator = MagicMock()
        mw = self.perms.PermissionMiddleware(mock_orchestrator)
        self.perms.set_mode_from_string("read_only")

        result = mw.run_with_permission_check("jenkins_trigger_build", MagicMock())
        self.assertEqual(result["error"], "permission_denied")
        self.assertEqual(result["tool"], "jenkins_trigger_build")

    def test_permission_middleware_run_with_permission_check_allows(self):
        mock_orchestrator = MagicMock()
        mock_fn = MagicMock(return_value="success")
        mw = self.perms.PermissionMiddleware(mock_orchestrator)
        self.perms.set_mode_from_string("read_write")

        result = mw.run_with_permission_check("jenkins_trigger_build", mock_fn)
        mock_fn.assert_called_once()
        self.assertNotIn("error", result)

    # ---- require_permission decorator ----
    def test_require_permission_decorator_blocks_denied(self):
        """Decorator should block when tool is denied by global permission config."""
        # Add my_tool to deny list
        self.perms.add_deny_tool("my_tool")

        @self.perms.require_permission(self.perms.OperationMode.READ_WRITE)
        def my_tool():
            return "executed"

        result = my_tool()
        self.assertIn("Permission denied", result)


if __name__ == "__main__":
    unittest.main()
