# agent/tools/jenkins_tool.py
# All connection details (URL, username, API token) come from config.infra
# Set via environment variables or GUI -> hot-reload

import json
import logging
import requests
from requests.auth import HTTPBasicAuth
from langchain.tools import tool

from config import config

logger = logging.getLogger(__name__)


def _auth() -> tuple:
    """Return (base_url, HTTPBasicAuth) from config. Raises if URL not set."""
    url = config.infra.jenkins_url.rstrip("/")
    if not url:
        raise ValueError(
            "Jenkins URL is not configured. "
            "Set JENKINS_URL env var or update via the GUI Configuration page."
        )
    user = config.infra.jenkins_username
    token = config.infra.jenkins_api_token
    if not user or not token:
        raise ValueError(
            "Jenkins credentials missing. "
            "Set JENKINS_USERNAME and JENKINS_API_TOKEN via env or GUI."
        )
    return url, HTTPBasicAuth(user, token)


def _get(path: str, params: dict = None) -> dict:
    """Authenticated GET to Jenkins REST API."""
    url, auth = _auth()
    resp = requests.get(
        f"{url}{path}",
        auth=auth,
        params=params,
        timeout=15,
        verify=False,  # set to True or pass CA cert in production
    )
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict = None) -> requests.Response:
    """Authenticated POST to Jenkins REST API."""
    url, auth = _auth()
    # Jenkins CSRF crumb
    try:
        crumb_data = requests.get(
            f"{url}/crumbIssuer/api/json",
            auth=auth, timeout=10, verify=False
        ).json()
        headers = {crumb_data["crumbRequestField"]: crumb_data["crumb"]}
    except Exception:
        headers = {}
    resp = requests.post(
        f"{url}{path}",
        auth=auth,
        headers=headers,
        data=data or {},
        timeout=30,
        verify=False,
    )
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# LangChain Tools
# ---------------------------------------------------------------------------

@tool
def list_jenkins_jobs(folder: str = "") -> str:
    """List all Jenkins jobs or jobs inside a specific folder.
    Args: folder - Jenkins folder name (empty string for root level)"""
    try:
        path = f"/job/{folder}/api/json" if folder else "/api/json"
        data = _get(path, params={"tree": "jobs[name,url,color,lastBuild[number,result,timestamp]]"})
        jobs = data.get("jobs", [])
        if not jobs:
            return "No jobs found."
        lines = []
        for j in jobs:
            last = j.get("lastBuild") or {}
            result = last.get("result", "N/A")
            num = last.get("number", "N/A")
            color = j.get("color", "unknown")
            lines.append(f"  - {j['name']} | status={color} | last_build=#{num} result={result}")
        return "Jenkins Jobs:\n" + "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("list_jenkins_jobs failed")
        return f"Error fetching Jenkins jobs: {e}"


@tool
def get_jenkins_build_status(job_name: str, build_number: str = "lastBuild") -> str:
    """Get the status and details of a Jenkins build.
    Args:
      job_name     - full job name (use folder/job for nested, e.g. 'deploy/api-service')
      build_number - build number or 'lastBuild' / 'lastSuccessfulBuild' / 'lastFailedBuild'"""
    try:
        # Support nested jobs: deploy/api-service -> /job/deploy/job/api-service
        job_path = "/job/" + "/job/".join(job_name.strip("/").split("/"))
        data = _get(f"{job_path}/{build_number}/api/json")
        result = data.get("result", "IN_PROGRESS")
        duration_s = data.get("duration", 0) // 1000
        url = data.get("url", "")

        causes = [c.get("shortDescription", "") for c in data.get("actions", [{}])[0].get("causes", [])]
        return (
            f"Job: {job_name}\n"
            f"Build: #{data.get('number')}\n"
            f"Result: {result}\n"
            f"Duration: {duration_s}s\n"
            f"Triggered by: {', '.join(causes) or 'N/A'}\n"
            f"URL: {url}"
        )
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("get_jenkins_build_status failed")
        return f"Error fetching build status: {e}"


@tool
def get_jenkins_build_log(job_name: str, build_number: str = "lastBuild") -> str:
    """Fetch the console log of a Jenkins build (last 100 lines).
    Args:
      job_name     - full job name (supports nested: 'folder/job-name')
      build_number - build number or 'lastBuild'"""
    try:
        url, auth = _auth()
        job_path = "/job/" + "/job/".join(job_name.strip("/").split("/"))
        resp = requests.get(
            f"{url}{job_path}/{build_number}/consoleText",
            auth=auth, timeout=20, verify=False
        )
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        tail = lines[-100:] if len(lines) > 100 else lines
        return f"Console log (last {len(tail)} lines):\n" + "\n".join(tail)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("get_jenkins_build_log failed")
        return f"Error fetching build log: {e}"


@tool
def trigger_jenkins_build(job_name: str, parameters: str = "") -> str:
    """Trigger a Jenkins build (with optional parameters).
    Args:
      job_name   - full job name (supports nested: 'folder/job-name')
      parameters - JSON string of build parameters, e.g. '{"ENV": "prod", "BRANCH": "main"}'"""
    try:
        job_path = "/job/" + "/job/".join(job_name.strip("/").split("/"))
        if parameters:
            params = json.loads(parameters)
            form_data = {k: v for k, v in params.items()}
            resp = _post(f"{job_path}/buildWithParameters", data=form_data)
        else:
            resp = _post(f"{job_path}/build")
        queue_url = resp.headers.get("Location", "N/A")
        return f"Build triggered for '{job_name}'. Queue URL: {queue_url}"
    except ValueError as e:
        return f"Configuration error: {e}"
    except json.JSONDecodeError:
        return f"Invalid parameters JSON: {parameters}"
    except Exception as e:
        logger.exception("trigger_jenkins_build failed")
        return f"Error triggering build: {e}"


@tool
def get_jenkins_pipeline_stages(job_name: str, build_number: str = "lastBuild") -> str:
    """Get pipeline stage breakdown for a Jenkins Pipeline build.
    Args:
      job_name     - pipeline job name (supports nested)
      build_number - build number or 'lastBuild'"""
    try:
        url, auth = _auth()
        job_path = "/job/" + "/job/".join(job_name.strip("/").split("/"))
        resp = requests.get(
            f"{url}{job_path}/{build_number}/wfapi/describe",
            auth=auth, timeout=15, verify=False
        )
        resp.raise_for_status()
        data = resp.json()
        stages = data.get("stages", [])
        if not stages:
            return "No pipeline stages found (may not be a Pipeline job)."
        lines = [f"Pipeline: {job_name} #{data.get('id', '')} | Status: {data.get('status')}"]
        for s in stages:
            dur = s.get("durationMillis", 0) // 1000
            lines.append(f"  [{s.get('status','?'):12}] {s.get('name','?'):30} {dur}s")
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("get_jenkins_pipeline_stages failed")
        return f"Error fetching pipeline stages: {e}"


# Exported list for orchestrator
jenkins_tools = [
    list_jenkins_jobs,
    get_jenkins_build_status,
    get_jenkins_build_log,
    trigger_jenkins_build,
    get_jenkins_pipeline_stages,
]
