# agent/tools/terraform_tool.py
# Terraform and Infrastructure as Code tools for DevOps AI Copilot

import logging
import os
import subprocess

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

TERRAFORM_PATH = os.getenv("TERRAFORM_PATH", ".")  # Directory containing terraform files


def _run_terraform(args: list, cwd: str = TERRAFORM_PATH) -> tuple[str, str, int]:
    """Run terraform command and return stdout, stderr, returncode."""
    try:
        result = subprocess.run(
            ["terraform"] + args,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=cwd,
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return "", "Terraform not found. Is it installed and in PATH?", 1
    except Exception as e:
        return "", str(e), 1


@tool
def terraform_validate() -> str:
    """Validate Terraform configuration files without executing."""
    try:
        stdout, stderr, code = _run_terraform(["validate"])
        if code != 0:
            return f"Terraform validation failed:\n{stderr or stdout}"
        return f"Terraform validation passed:\n{stdout}"
    except Exception as e:
        logger.exception("terraform_validate failed")
        return f"Error validating Terraform: {e}"


@tool
def terraform_plan(destroy: bool = False) -> str:
    """Generate Terraform execution plan.
    Args:
      destroy - Generate a plan to destroy all resources (default: False)"""
    try:
        args = ["plan", "-out=tfplan"]
        if destroy:
            args.append("-destroy")

        stdout, stderr, code = _run_terraform(args)
        if code != 0:
            return f"Terraform plan failed:\n{stderr or stdout}"

        # Extract summary
        lines = stdout.split("\n")
        summary_lines = [line for line in lines if "Plan:" in line or "will be" in line or "destroyed" in line or "changed" in line]
        summary = "\n".join(summary_lines[-10:]) if summary_lines else stdout[-500:]

        return f"Terraform Plan:\n{summary}"
    except Exception as e:
        logger.exception("terraform_plan failed")
        return f"Error generating Terraform plan: {e}"


@tool
def terraform_apply(auto_approve: bool = False) -> str:
    """Apply Terraform changes.
    Args:
      auto_approve - Skip interactive approval (default: False - manual confirm)"""
    try:
        args = ["apply", "-input=false"]
        if auto_approve:
            args.append("-auto-approve")
        args.append("tfplan")

        stdout, stderr, code = _run_terraform(args)
        if code != 0:
            return f"Terraform apply failed:\n{stderr or stdout}"

        return f"Terraform apply succeeded:\n{stdout[-1000:]}"
    except Exception as e:
        logger.exception("terraform_apply failed")
        return f"Error applying Terraform: {e}"


@tool
def terraform_destroy(auto_approve: bool = False) -> str:
    """Destroy all Terraform-managed resources.
    Args:
      auto_approve - Skip interactive approval (default: False)"""
    try:
        args = ["destroy", "-input=false"]
        if auto_approve:
            args.append("-auto-approve")

        stdout, stderr, code = _run_terraform(args)
        if code != 0:
            return f"Terraform destroy failed:\n{stderr or stdout}"

        return f"Terraform destroy succeeded:\n{stdout[-1000:]}"
    except Exception as e:
        logger.exception("terraform_destroy failed")
        return f"Error destroying Terraform resources: {e}"


@tool
def terraform_state_list(resource: str = "") -> str:
    """List resources in Terraform state.
    Args:
      resource - Optional filter for specific resource type/name"""
    try:
        args = ["state", "list"]
        if resource:
            args.append("-state=" + resource)

        stdout, stderr, code = _run_terraform(args)
        if code != 0:
            return f"Terraform state list failed:\n{stderr or stdout}"

        if not stdout.strip():
            return "No resources found in Terraform state."

        lines = stdout.strip().split("\n")
        return f"Terraform State Resources ({len(lines)}):\n" + "\n".join(f"  {r}" for r in lines)
    except Exception as e:
        logger.exception("terraform_state_list failed")
        return f"Error listing Terraform state: {e}"


@tool
def terraform_output() -> str:
    """Get values of Terraform output variables."""
    try:
        stdout, stderr, code = _run_terraform(["output"])
        if code != 0:
            return f"Terraform output failed:\n{stderr or stdout}"

        if not stdout.strip():
            return "No Terraform outputs defined."

        return f"Terraform Outputs:\n{stdout}"
    except Exception as e:
        logger.exception("terraform_output failed")
        return f"Error getting Terraform output: {e}"


@tool
def terraform_show() -> str:
    """Show the current Terraform state as JSON."""
    try:
        stdout, stderr, code = _run_terraform(["show", "-json"])
        if code != 0:
            return f"Terraform show failed:\n{stderr or stdout}"

        return f"Terraform State (JSON):\n{stdout[-2000:]}"
    except Exception as e:
        logger.exception("terraform_show failed")
        return f"Error showing Terraform state: {e}"


TERRAFORM_TOOLS = [
    terraform_validate,
    terraform_plan,
    terraform_apply,
    terraform_destroy,
    terraform_state_list,
    terraform_output,
    terraform_show,
]
