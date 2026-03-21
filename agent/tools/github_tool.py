# agent/tools/github_tool.py
# GitHub and GitLab CI/CD tools for DevOps AI Copilot

import logging
import os

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # format: owner/repo
GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.com")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
GITLAB_PROJECT_ID = os.getenv("GITLAB_PROJECT_ID", "")


def _github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }


def _gitlab_headers():
    return {
        "PRIVATE-TOKEN": f"{GITLAB_TOKEN}",
        "Content-Type": "application/json"
    }


@tool
def github_list_workflow_runs(workflow_name: str = "", max_runs: int = 10) -> str:
    """List recent GitHub Actions workflow runs.
    Args:
      workflow_name - Name of the workflow file (e.g., 'ci.yml') or empty for all
      max_runs - Number of recent runs to show (default: 10)"""
    try:
        if not GITHUB_REPO:
            return "GITHUB_REPO env var not set (format: owner/repo)"

        if workflow_name:
            # Get workflow ID
            wf_resp = requests.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows",
                headers=_github_headers(),
                timeout=15,
            )
            workflows = wf_resp.json().get("workflows", [])
            wf_id = next((w["id"] for w in workflows if w["name"] == workflow_name or w["path"] == workflow_name), None)
            if not wf_id:
                return f"Workflow '{workflow_name}' not found."
            url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{wf_id}/runs"
        else:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs"

        resp = requests.get(url, headers=_github_headers(), timeout=15, params={"per_page": max_runs})
        resp.raise_for_status()
        data = resp.json()
        runs = data.get("workflow_runs", [])

        if not runs:
            return "No workflow runs found."

        lines = [f"GitHub Actions Runs - {workflow_name or 'all'} ({len(runs)}):"]
        for r in runs:
            status = r["status"]
            conclusion = r.get("conclusion", "")
            triggered = r["created_at"][:16]
            name = r["name"]
            branch = r["head_branch"]
            lines.append(f"  [{status}/{conclusion}] {name} | #{r['run_number']} | {branch} | {triggered}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("github_list_workflow_runs failed")
        return f"Error listing workflow runs: {e}"


@tool
def github_get_workflow_run_status(run_id: int) -> str:
    """Get detailed status of a specific GitHub Actions run.
    Args:
      run_id - The workflow run ID"""
    try:
        if not GITHUB_REPO:
            return "GITHUB_REPO env var not set"

        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}",
            headers=_github_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        run = resp.json()

        jobs_url = run["jobs_url"]
        jobs_resp = requests.get(jobs_url, headers=_github_headers(), timeout=15)
        jobs = jobs_resp.json().get("jobs", [])

        lines = [
            f"GitHub Actions Run #{run['run_number']}",
            f"  Status: {run['status']} | Conclusion: {run.get('conclusion', 'N/A')}",
            f"  Branch: {run['head_branch']} | SHA: {run['head_sha'][:7]}",
            f"  Triggered: {run['created_at'][:16]} | Updated: {run['updated_at'][:16]}",
            f"  Workflow: {run['name']}",
            f"  Jobs ({len(jobs)}):",
        ]
        for j in jobs:
            lines.append(f"    [{j['status']}/{j.get('conclusion', '')}] {j['name']}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("github_get_workflow_run_status failed")
        return f"Error getting workflow run status: {e}"


@tool
def github_list_pr_checks(pr_number: int) -> str:
    """List all CI checks status for a Pull Request.
    Args:
      pr_number - Pull Request number"""
    try:
        if not GITHUB_REPO:
            return "GITHUB_REPO env var not set"

        # Get PR details
        pr_resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/pulls/{pr_number}",
            headers=_github_headers(),
            timeout=15,
        )
        pr_resp.raise_for_status()
        pr = pr_resp.json()

        # Get commit SHA
        sha = pr["head"]["sha"]

        # Get status checks for that commit
        status_resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/commits/{sha}/status",
            headers=_github_headers(),
            timeout=15,
        )
        status = status_resp.json()

        # Get check runs
        checks_resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/commits/{sha}/check-runs",
            headers=_github_headers(),
            timeout=15,
        )
        checks = checks_resp.json().get("check_runs", [])

        lines = [
            f"PR #{pr_number} CI Checks - {pr['head']['ref']}:",
            f"  Commit: {sha[:7]} | Total: {status.get('total_count', len(checks))}",
            f"  State: {status.get('state', 'unknown')}",
        ]

        if checks:
            lines.append("  Check Runs:")
            for c in checks:
                lines.append(f"    [{c['status']}/{c.get('conclusion', '')}] {c['name']} | {c['check_suite']['app']['name']}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("github_list_pr_checks failed")
        return f"Error listing PR checks: {e}"


@tool
def github_get_repo_info() -> str:
    """Get GitHub repository information."""
    try:
        if not GITHUB_REPO:
            return "GITHUB_REPO env var not set"

        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}",
            headers=_github_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        repo = resp.json()

        lines = [
            f"GitHub Repository: {repo['full_name']}",
            f"  Description: {repo.get('description', 'N/A')}",
            f"  Visibility: {repo['visibility']}",
            f"  Default Branch: {repo['default_branch']}",
            f"  Stars: {repo['stargazers_count']} | Forks: {repo['forks_count']}",
            f"  Open Issues: {repo['open_issues_count']}",
            f"  Language: {repo.get('language', 'N/A')}",
            f"  Created: {repo['created_at'][:10]} | Updated: {repo['updated_at'][:10]}",
            f"  URL: {repo['html_url']}",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.exception("github_get_repo_info failed")
        return f"Error getting repo info: {e}"


@tool
def gitlab_list_pipelines(status: str = "") -> str:
    """List GitLab CI/CD pipelines.
    Args:
      status - Filter by status: running, pending, success, failed, skipped (default: all)"""
    try:
        if not GITLAB_PROJECT_ID:
            return "GITLAB_PROJECT_ID env var not set"

        params = {"per_page": 20}
        if status:
            params["status"] = status

        resp = requests.get(
            f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/pipelines",
            headers=_gitlab_headers(),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        pipelines = resp.json()

        if not pipelines:
            return f"No GitLab pipelines found with status: {status or 'all'}."

        lines = [f"GitLab Pipelines - {len(pipelines)} ({status or 'all statuses'}):"]
        for p in pipelines:
            lines.append(f"  #{p['id']} | {p['ref']} | {p['status']} | {p['created_at'][:16]}")
            lines.append(f"    SHA: {p['sha'][:8]} | User: {p['user']['name']}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("gitlab_list_pipelines failed")
        return f"Error listing GitLab pipelines: {e}"


@tool
def gitlab_get_pipeline_status(pipeline_id: int) -> str:
    """Get detailed status of a GitLab pipeline.
    Args:
      pipeline_id - GitLab pipeline ID"""
    try:
        if not GITLAB_PROJECT_ID:
            return "GITLAB_PROJECT_ID env var not set"

        # Get pipeline details
        resp = requests.get(
            f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/pipelines/{pipeline_id}",
            headers=_gitlab_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        pipeline = resp.json()

        # Get jobs
        jobs_resp = requests.get(
            f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/pipelines/{pipeline_id}/jobs",
            headers=_gitlab_headers(),
            timeout=15,
        )
        jobs = jobs_resp.json()

        lines = [
            f"GitLab Pipeline #{pipeline['id']}",
            f"  Ref: {pipeline['ref']} | SHA: {pipeline['sha'][:8]}",
            f"  Status: {pipeline['status']}",
            f"  Created: {pipeline['created_at'][:16]} | Updated: {pipeline['updated_at'][:16]}",
            f"  User: {pipeline['user']['name']}",
            f"  Jobs ({len(jobs)}):",
        ]
        for j in jobs:
            lines.append(f"    [{j['status']}] {j['name']} | Stage: {j['stage']}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("gitlab_get_pipeline_status failed")
        return f"Error getting pipeline status: {e}"


GITHUB_TOOLS = [
    github_list_workflow_runs,
    github_get_workflow_run_status,
    github_list_pr_checks,
    github_get_repo_info,
    gitlab_list_pipelines,
    gitlab_get_pipeline_status,
]
