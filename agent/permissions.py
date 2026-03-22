# agent/permissions.py - Operation Mode & Permission Control
# Implements read/write toggles and safe mode for all tools
# Designed for restricted environments (banks, intranets)

import logging
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Callable, List, Set

logger = logging.getLogger(__name__)


class OperationMode(Enum):
    """Operation mode for the agent."""
    READ_ONLY = "read_only"      # Only read operations allowed
    READ_WRITE = "read_write"    # Both read and write operations allowed
    SAFE_MODE = "safe_mode"      # Only safe, non-destructive operations


class OperationType(Enum):
    """Type of operation a tool performs."""
    READ = "read"       # Read-only, non-destructive
    WRITE = "write"    # Creates/modifies resources
    DELETE = "delete"  # Destructive operations
    EXECUTE = "execute"  # Executes code/commands


# ---------------------------------------------------------------------------
# Tool Classification Registry
# Maps tool names to their operation types
# ---------------------------------------------------------------------------
TOOL_CLASSIFICATIONS: dict[str, OperationType] = {
    # Kubernetes - Read operations
    "list_pods": OperationType.READ,
    "get_pod_logs": OperationType.READ,
    "describe_pod": OperationType.READ,
    "list_services": OperationType.READ,
    "list_namespaces": OperationType.READ,
    "list_nodes": OperationType.READ,
    "get_pod_events": OperationType.READ,
    "check_pod_health": OperationType.READ,

    # Kubernetes - Write operations (destructive)
    "delete_pod": OperationType.DELETE,
    "scale_deployment": OperationType.WRITE,
    "restart_deployment": OperationType.WRITE,
    "rollout_restart": OperationType.WRITE,
    "rollout_undo": OperationType.DELETE,
    "patch_deployment": OperationType.WRITE,

    # Database - Read operations
    "postgres_list_databases": OperationType.READ,
    "postgres_get_activity": OperationType.READ,
    "postgres_get_tables": OperationType.READ,
    "postgres_get_slow_queries": OperationType.READ,
    "mysql_list_databases": OperationType.READ,
    "mysql_get_status": OperationType.READ,
    "redis_get_info": OperationType.READ,
    "mongodb_list_collections": OperationType.READ,

    # Database - Write operations (destructive)
    "postgres_execute_query": OperationType.WRITE,
    "mysql_execute_query": OperationType.WRITE,
    "redis_flush_db": OperationType.DELETE,
    "mongodb_drop_collection": OperationType.DELETE,

    # Docker - Read operations
    "list_containers": OperationType.READ,
    "get_container_logs": OperationType.READ,
    "get_container_stats": OperationType.READ,
    "list_images": OperationType.READ,

    # Docker - Write operations (destructive)
    "stop_container": OperationType.WRITE,
    "remove_container": OperationType.DELETE,
    "pull_image": OperationType.WRITE,
    "remove_image": OperationType.DELETE,

    # Nginx - Read operations
    "nginx_status": OperationType.READ,
    "nginx_access_logs": OperationType.READ,
    "nginx_error_logs": OperationType.READ,
    "nginx_config_test": OperationType.READ,

    # Nginx - Write operations
    "nginx_reload": OperationType.WRITE,
    "nginx_config_backup": OperationType.WRITE,

    # Kibana - Read operations
    "kibana_search_logs": OperationType.READ,
    "kibana_get_indices": OperationType.READ,
    "kibana_get_dashboards": OperationType.READ,

    # Kibana - Write operations
    "kibana_create_index_pattern": OperationType.WRITE,
    "kibana_delete_index": OperationType.DELETE,

    # Jenkins - Read operations
    "jenkins_list_jobs": OperationType.READ,
    "jenkins_get_build_status": OperationType.READ,
    "jenkins_get_console_output": OperationType.READ,
    "jenkins_list_agents": OperationType.READ,

    # Jenkins - Write operations (triggers builds, modifies jobs)
    "jenkins_trigger_build": OperationType.WRITE,
    "jenkins_create_job": OperationType.WRITE,
    "jenkins_delete_job": OperationType.DELETE,
    "jenkins_update_job_config": OperationType.WRITE,

    # Artifactory - Read operations
    "artifactory_list_repos": OperationType.READ,
    "artifactory_search_artifacts": OperationType.READ,
    "artifactory_get_artifact_info": OperationType.READ,

    # Artifactory - Write operations
    "artifactory_deploy_artifact": OperationType.WRITE,
    "artifactory_delete_artifact": OperationType.DELETE,

    # Prometheus - Read operations
    "prometheus_query": OperationType.READ,
    "prometheus_query_range": OperationType.READ,
    "prometheus_get_targets": OperationType.READ,
    "prometheus_get_alerts": OperationType.READ,

    # Grafana - Read operations
    "grafana_search_dashboards": OperationType.READ,
    "grafana_get_dashboard": OperationType.READ,
    "grafana_get_alerts": OperationType.READ,

    # Grafana - Write operations
    "grafana_create_dashboard": OperationType.WRITE,
    "grafana_update_dashboard": OperationType.WRITE,
    "grafana_delete_dashboard": OperationType.DELETE,

    # AWS - Read operations
    "aws_list_ec2_instances": OperationType.READ,
    "aws_list_s3_buckets": OperationType.READ,
    "aws_get_cloudwatch_metrics": OperationType.READ,
    "aws_list_lambda_functions": OperationType.READ,

    # AWS - Write operations (destructive)
    "aws_stop_ec2_instance": OperationType.WRITE,
    "aws_terminate_ec2_instance": OperationType.DELETE,
    "aws_delete_s3_bucket": OperationType.DELETE,
    "aws_invoke_lambda": OperationType.EXECUTE,

    # CloudWatch - Read operations
    "cloudwatch_get_metrics": OperationType.READ,
    "cloudwatch_get_logs": OperationType.READ,

    # GitHub - Read operations
    "github_list_workflow_runs": OperationType.READ,
    "github_get_workflow_run": OperationType.READ,
    "github_list_repos": OperationType.READ,

    # GitHub - Write operations
    "github_trigger_workflow": OperationType.WRITE,
    "github_create_issue": OperationType.WRITE,
    "github_close_issue": OperationType.WRITE,

    # GitLab - Read operations
    "gitlab_list_projects": OperationType.READ,
    "gitlab_list_pipelines": OperationType.READ,
    "gitlab_get_job_logs": OperationType.READ,

    # GitLab - Write operations
    "gitlab_trigger_pipeline": OperationType.WRITE,
    "gitlab_create_merge_request": OperationType.WRITE,
    "gitlab_cancel_pipeline": OperationType.WRITE,

    # PagerDuty - Read operations
    "pagerduty_list_incidents": OperationType.READ,
    "pagerduty_get_incident": OperationType.READ,
    "pagerduty_list_services": OperationType.READ,

    # PagerDuty - Write operations
    "pagerduty_trigger_incident": OperationType.WRITE,
    "pagerduty_acknowledge_incident": OperationType.WRITE,
    "pagerduty_resolve_incident": OperationType.WRITE,

    # SSL - Read operations
    "ssl_check_certificate": OperationType.READ,
    "ssl_get_expiry_days": OperationType.READ,

    # SSL - Write operations
    "ssl_renew_certificate": OperationType.WRITE,

    # Terraform - Read operations
    "terraform_show": OperationType.READ,
    "terraform_list_workspaces": OperationType.READ,

    # Terraform - Write operations (destructive)
    "terraform_apply": OperationType.WRITE,
    "terraform_destroy": OperationType.DELETE,
    "terraform_import": OperationType.WRITE,

    # Terraform - Execute operations
    "terraform_plan": OperationType.EXECUTE,
    "terraform_validate": OperationType.EXECUTE,

    # LLM - Read operations
    "llm_compare_configs": OperationType.READ,
    "llm_generate_runbook": OperationType.READ,

    # Bitbucket - Read operations
    "bitbucket_list_repos": OperationType.READ,
    "bitbucket_list_pipelines": OperationType.READ,
    "bitbucket_get_pipeline_status": OperationType.READ,

    # Bitbucket - Write operations
    "bitbucket_trigger_pipeline": OperationType.WRITE,
    "bitbucket_create_pr": OperationType.WRITE,

    # Jira - Read operations
    "jira_list_issues": OperationType.READ,
    "jira_get_issue": OperationType.READ,
    "jira_list_projects": OperationType.READ,

    # Jira - Write operations
    "jira_create_issue": OperationType.WRITE,
    "jira_update_issue": OperationType.WRITE,
    "jira_transition_issue": OperationType.WRITE,
    "jira_add_comment": OperationType.WRITE,
    "jira_close_issue": OperationType.WRITE,

    # Logs - Read operations
    "get_all_logs": OperationType.READ,
    "search_logs": OperationType.READ,

    # Logs - Write operations
    "ingest_logs": OperationType.WRITE,
    "delete_logs": OperationType.DELETE,
}


@dataclass
class PermissionConfig:
    """Permission configuration for the agent."""
    # Current operation mode
    mode: OperationMode = OperationMode.READ_WRITE

    # Custom tool classifications (overrides defaults)
    custom_classifications: dict[str, OperationType] = field(default_factory=dict)

    # Allowed tools in each mode (if set, only these tools are allowed)
    read_only_allowed_tools: Set[str] = field(default_factory=set)
    safe_mode_allowed_tools: Set[str] = field(default_factory=set)

    # Deny list (always blocked regardless of mode)
    denied_tools: Set[str] = field(default_factory=set)

    # Audit logging
    audit_enabled: bool = True
    audit_log_path: str = "/var/log/devops-ai/audit.log"

    def get_operation_type(self, tool_name: str) -> OperationType:
        """Get the operation type for a tool."""
        if tool_name in self.custom_classifications:
            return self.custom_classifications[tool_name]
        return TOOL_CLASSIFICATIONS.get(tool_name, OperationType.READ)

    def is_allowed(self, tool_name: str) -> tuple[bool, str]:
        """
        Check if a tool is allowed to run in the current mode.
        Returns (allowed, reason).
        """
        # Check deny list first
        if tool_name in self.denied_tools:
            return False, f"Tool '{tool_name}' is explicitly denied"

        op_type = self.get_operation_type(tool_name)

        if self.mode == OperationMode.READ_ONLY:
            if op_type == OperationType.READ:
                return True, "Read operation allowed in READ_ONLY mode"
            return False, f"Tool '{tool_name}' performs {op_type.value} operation which is not allowed in READ_ONLY mode"

        elif self.mode == OperationMode.SAFE_MODE:
            if op_type == OperationType.DELETE:
                return False, f"Tool '{tool_name}' performs DELETE operation which is blocked in SAFE_MODE"
            if op_type == OperationType.EXECUTE:
                return False, f"Tool '{tool_name}' performs EXECUTE operation which is blocked in SAFE_MODE"
            if self.safe_mode_allowed_tools and tool_name not in self.safe_mode_allowed_tools:
                return False, f"Tool '{tool_name}' is not in the SAFE_MODE allowed list"
            return True, f"{op_type.value.capitalize()} operation allowed in SAFE_MODE"

        # READ_WRITE mode - allow all except explicitly denied
        return True, f"{op_type.value.capitalize()} operation allowed in READ_WRITE mode"


# Global permission config
_permissions = PermissionConfig()


def get_permissions() -> PermissionConfig:
    """Get the global permission config."""
    return _permissions


def set_operation_mode(mode: OperationMode) -> None:
    """Set the operation mode."""
    _permissions.mode = mode
    logger.info("Operation mode changed to: %s", mode.value)


def set_mode_from_string(mode_str: str) -> bool:
    """Set operation mode from string. Returns True if successful."""
    mode_str = mode_str.lower().strip()
    mode_map = {
        "readonly": OperationMode.READ_ONLY,
        "read_only": OperationMode.READ_ONLY,
        "readwrite": OperationMode.READ_WRITE,
        "read_write": OperationMode.READ_WRITE,
        "read-write": OperationMode.READ_WRITE,
        "safemode": OperationMode.SAFE_MODE,
        "safe_mode": OperationMode.SAFE_MODE,
    }
    mode = mode_map.get(mode_str)
    if mode is None:
        return False
    set_operation_mode(mode)
    return True


def add_deny_tool(tool_name: str) -> None:
    """Add a tool to the deny list."""
    _permissions.denied_tools.add(tool_name)
    logger.info("Tool '%s' added to deny list", tool_name)


def remove_deny_tool(tool_name: str) -> None:
    """Remove a tool from the deny list."""
    _permissions.denied_tools.discard(tool_name)
    logger.info("Tool '%s' removed from deny list", tool_name)


def set_allowed_tools(mode: str, tools: List[str]) -> None:
    """Set allowed tools for a specific mode."""
    if mode.lower() in ("readonly", "read_only"):
        _permissions.read_only_allowed_tools = set(tools)
    elif mode.lower() in ("safemode", "safe_mode"):
        _permissions.safe_mode_allowed_tools = set(tools)


def check_tool_permission(tool_name: str) -> tuple[bool, str]:
    """Check if a tool is allowed to run."""
    return _permissions.is_allowed(tool_name)


def require_permission(*allowed_modes: OperationMode):
    """Decorator to enforce permission checks on tool functions."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            tool_name = getattr(func, '_tool_name', None) or func.__name__
            allowed, reason = _permissions.is_allowed(tool_name)
            if not allowed:
                logger.warning("Permission denied for tool '%s': %s", tool_name, reason)
                return f"Permission denied: {reason}"
            return func(*args, **kwargs)
        # Store tool name for permission check
        wrapper._tool_name = func.__name__
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Audit Logging
# ---------------------------------------------------------------------------
def audit_log(tool_name: str, operation: str, mode: str, allowed: bool, details: str = "") -> None:
    """Log an operation to the audit log."""
    if not _permissions.audit_enabled:
        return

    import json
    from datetime import datetime, timezone

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tool": tool_name,
        "operation": operation,
        "mode": mode,
        "allowed": allowed,
        "details": details,
    }

    try:
        import os
        log_dir = os.path.dirname(_permissions.audit_log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(_permissions.audit_log_path, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except OSError:
        # Intentionally catches file I/O errors (disk full, permission denied, etc.)
        pass


# ---------------------------------------------------------------------------
# Permission Middleware for Orchestrator
# ---------------------------------------------------------------------------
class PermissionMiddleware:
    """
    Middleware that wraps orchestrator tool execution with permission checks.
    """

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def run_with_permission_check(self, tool_name: str, func: Callable, *args, **kwargs):
        """Run a tool function with permission checking."""
        allowed, reason = _permissions.is_allowed(tool_name)
        operation_type = _permissions.get_operation_type(tool_name)

        # Audit log the attempt
        audit_log(
            tool_name=tool_name,
            operation=operation_type.value,
            mode=_permissions.mode.value,
            allowed=allowed,
            details=reason,
        )

        if not allowed:
            return {
                "error": "permission_denied",
                "message": reason,
                "tool": tool_name,
                "mode": _permissions.mode.value,
            }

        return func(*args, **kwargs)

    def get_status(self) -> dict:
        """Get current permission status."""
        return {
            "mode": _permissions.mode.value,
            "denied_tools": list(_permissions.denied_tools),
            "audit_enabled": _permissions.audit_enabled,
        }
