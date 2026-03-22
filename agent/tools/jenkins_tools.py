# agent/tools/jenkins_tools.py
# LangChain tools for Jenkins CI/CD operations

from __future__ import annotations

import logging
from typing import Optional

import requests
from langchain_core.tools import tool

from agent.secrets import jenkins

logger = logging.getLogger(__name__)


def _client() -> tuple[str, tuple[str, str]]:
    """Return (base_url, auth) for Jenkins API calls."""
    s = jenkins.all()
    url = s.get("url", "").rstrip("/")
    username = s.get("username", "")
    api_token = s.get("api_token", "")
    if not url:
        msg = "Jenkins secret not configured (SECRET_ID_JENKINS)."
        raise ValueError(msg)
    return url, (username, api_token)


@tool
def jenkins_list_jobs(folder: str = "") -> list:
    """List all Jenkins jobs. Optionally filter by folder name."""
    try:
        base_url, auth = _client()
        api_path = f"{base_url}/job/{folder}/api/json" if folder else f"{base_url}/api/json"
        resp = requests.get(
            api_path,
            params={"tree": "jobs[name,url,color,lastBuild[number,result,timestamp]]"},
            auth=auth,
            timeout=15,
        )
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        logger.info("jenkins_list_jobs: found %d jobs", len(jobs))
        return jobs
    except requests.exceptions.RequestException:
        # Intentionally broad: HTTP calls may fail due to network, auth, or server errors
        pass


@tool
def jenkins_get_build_status(job_name: str, build_number: Optional[int] = None) -> dict:
    """Get build status for a Jenkins job. Uses lastBuild if build_number is omitted."""
    try:
        base_url, auth = _client()
        build_ref = build_number if build_number else "lastBuild"
        url = f"{base_url}/job/{job_name}/{build_ref}/api/json"
        resp = requests.get(url, auth=auth, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {
            "job": job_name,
            "build_number": data.get("number"),
            "result": data.get("result"),
            "duration_ms": data.get("duration"),
            "timestamp": data.get("timestamp"),
            "building": data.get("building"),
            "url": data.get("url"),
        }
    except requests.exceptions.RequestException:
        # Intentionally broad: HTTP calls may fail due to network, auth, or server errors
        pass


@tool
def jenkins_trigger_build(job_name: str, parameters: Optional[dict] = None) -> dict:
    """Trigger a Jenkins build. Pass parameters dict for parameterized jobs."""
    try:
        base_url, auth = _client()
        if parameters:
            url = f"{base_url}/job/{job_name}/buildWithParameters"
            resp = requests.post(url, auth=auth, params=parameters, timeout=15)
        else:
            url = f"{base_url}/job/{job_name}/build"
            resp = requests.post(url, auth=auth, timeout=15)
        resp.raise_for_status()
        queue_url = resp.headers.get("Location", "")
        return {"queued": True, "queue_url": queue_url}
    except requests.exceptions.RequestException:
        # Intentionally broad: HTTP calls may fail due to network, auth, or server errors
        pass


@tool
def jenkins_get_console_output(job_name: str, build_number: Optional[int] = None) -> str:
    """Fetch console log for a Jenkins build (last 50 KB)."""
    try:
        base_url, auth = _client()
        build_ref = build_number if build_number else "lastBuild"
        url = f"{base_url}/job/{job_name}/{build_ref}/logText/progressiveText?start=0"
        resp = requests.get(url, auth=auth, timeout=20)
        resp.raise_for_status()
        return resp.text[-51200:]
    except requests.exceptions.RequestException:
        # Intentionally broad: HTTP calls may fail due to network, auth, or server errors
        pass


@tool
def jenkins_list_failed_builds(limit: int = 10) -> list:
    """Return a list of recently failed Jenkins builds across all jobs."""
    try:
        jobs = jenkins_list_jobs({})
        failed = []
        for job in jobs[:50]:
            last = job.get("lastBuild")
            if last and job.get("color", "").startswith("red"):
                failed.append({
                    "job": job.get("name"),
                    "build_number": last.get("number"),
                    "result": last.get("result"),
                    "timestamp": last.get("timestamp"),
                    "url": job.get("url"),
                })
                if len(failed) >= limit:
                    break
        return failed
    except requests.exceptions.RequestException:
        # Intentionally broad: HTTP calls may fail due to network, auth, or server errors
        pass


JENKINS_TOOLS = [
    jenkins_list_jobs,
    jenkins_get_build_status,
    jenkins_trigger_build,
    jenkins_get_console_output,
    jenkins_list_failed_builds,
]
