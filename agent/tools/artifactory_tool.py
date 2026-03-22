# agent/tools/artifactory_tool.py
# All connection details (URL, username, API key) come from config.infra
# Set via environment variables or GUI -> hot-reload

import logging
import os
import requests
from requests.auth import HTTPBasicAuth
from langchain.tools import tool

from agent.config import config
from agent.secrets import artifactory

logger = logging.getLogger(__name__)


def _session() -> tuple:
    """
    Return (base_url, requests.Session) with proper auth headers.
    Supports:
      - API Key auth (X-JFrog-Art-Api header)  -- preferred
      - Basic auth (username + password/apikey) -- fallback
    Raises ValueError if URL or credentials are not configured.
    """
    url = config.infra.artifactory_url.rstrip("/")
    if not url:
        msg = (
            "Artifactory URL is not configured. "
            "Set ARTIFACTORY_URL env var or update via the GUI Configuration page."
        )
        raise ValueError(msg)
    secret_data = artifactory.all()
    api_key = secret_data.get("api_key", "")
    username = secret_data.get("username", "")
    if not api_key and not username:
        msg = (
            "Artifactory credentials missing. "
            "Set SECRET_ID_ARTIFACTORY env var pointing to AWS Secrets Manager secret."
        )
        raise ValueError(msg)
    session = requests.Session()
    session.verify = os.getenv("ARTIFACTORY_VERIFY_SSL", "false").lower() == "true"
    if api_key:
        session.headers.update({
            "X-JFrog-Art-Api": api_key,
            "Content-Type": "application/json",
        })
    elif username:
        session.auth = HTTPBasicAuth(username, api_key or "")
        session.headers.update({"Content-Type": "application/json"})
    return url, session


def _api_get(path: str, params: dict = None) -> dict:
    """Authenticated GET to Artifactory REST API."""
    url, session = _session()
    resp = session.get(f"{url}/artifactory/api{path}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# LangChain Tools
# ---------------------------------------------------------------------------

@tool
def search_artifact(artifact_name: str, repo: str = "") -> str:
    """Search for an artifact in JFrog Artifactory by name.
    Args:
      artifact_name - artifact filename or pattern (e.g. 'myapp-1.2.3.jar', '*.war')
      repo          - repository key to limit search (empty = search all repos)"""
    try:
        params = {"name": artifact_name}
        if repo:
            params["repos"] = repo
        data = _api_get("/search/artifact", params=params)
        results = data.get("results", [])
        if not results:
            return f"No artifact found matching '{artifact_name}'" + (f" in repo '{repo}'" if repo else ".")
        lines = [f"Found {len(results)} artifact(s) matching '{artifact_name}':"]
        for r in results[:20]:
            uri = r.get("uri", "?")
            # Extract repo and path from URI: /api/storage/REPO/path/to/file
            parts = uri.replace("/api/storage/", "").split("/", 1)
            r_repo = parts[0] if parts else "?"
            r_path = parts[1] if len(parts) > 1 else uri
            lines.append(f"  [{r_repo}] {r_path}")
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("search_artifact failed")
        return f"Error searching Artifactory: {e}"


@tool
def get_artifact_info(repo: str, artifact_path: str) -> str:
    """Get metadata and properties of a specific artifact.
    Args:
      repo          - repository key (e.g. 'libs-release-local')
      artifact_path - path within repo (e.g. 'com/myorg/myapp/1.0/myapp-1.0.jar')"""
    try:
        url, session = _session()
        # Storage API for file info
        resp = session.get(
            f"{url}/artifactory/api/storage/{repo}/{artifact_path.lstrip('/')}",
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        lines = [
            f"Artifact: {data.get('path', artifact_path)}",
            f"Repo:     {data.get('repo', repo)}",
            f"Size:     {data.get('size', 'N/A')} bytes",
            f"Created:  {data.get('created', 'N/A')}",
            f"Modified: {data.get('lastModified', 'N/A')}",
            f"Updated:  {data.get('lastUpdated', 'N/A')}",
            f"SHA256:   {data.get('checksums', {}).get('sha256', 'N/A')}",
            f"MD5:      {data.get('checksums', {}).get('md5', 'N/A')}",
            f"Download: {data.get('downloadUri', 'N/A')}",
        ]
        props = data.get("properties", {})
        if props:
            lines.append("Properties:")
            for k, v in props.items():
                lines.append(f"  {k} = {v}")
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("get_artifact_info failed")
        return f"Error fetching artifact info: {e}"


@tool
def list_repositories(repo_type: str = "") -> str:
    """List all repositories in Artifactory.
    Args: repo_type - filter by type: 'local', 'remote', 'virtual', 'federated' (empty = all)"""
    try:
        params = {}
        if repo_type:
            params["type"] = repo_type
        data = _api_get("/repos", params=params)
        if not data:
            return "No repositories found."
        lines = [f"Found {len(data)} repositor{'ies' if len(data) != 1 else 'y'}:"]
        for r in data:
            rtype = r.get("type", "?")
            key = r.get("key", "?")
            pkg = r.get("packageType", "generic")
            desc = r.get("description", "")
            lines.append(f"  [{rtype:8}] [{pkg:12}] {key}" + (f" - {desc}" if desc else ""))
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("list_repositories failed")
        return f"Error listing repositories: {e}"


@tool
def get_latest_artifact_version(repo: str, group_path: str, artifact_id: str) -> str:
    """Find the latest version of an artifact (useful for Maven/Gradle repos).
    Args:
      repo        - repository key (e.g. 'libs-release-local')
      group_path  - group path with slashes (e.g. 'com/myorg')
      artifact_id - artifact ID (e.g. 'myapp')"""
    try:
        url, session = _session()
        base_path = f"{group_path.strip('/')}/{artifact_id}"
        resp = session.get(
            f"{url}/artifactory/api/storage/{repo}/{base_path}",
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        children = data.get("children", [])
        versions = sorted(
            [c["uri"].strip("/") for c in children if c.get("folder")],
            reverse=True
        )
        if not versions:
            return f"No versions found for {group_path}/{artifact_id} in '{repo}'."
        latest = versions[0]
        lines = [
            f"Artifact: {group_path}/{artifact_id}",
            f"Repo: {repo}",
            f"Latest version: {latest}",
            f"All versions ({len(versions)}): " + ", ".join(versions[:10]),
        ]
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("get_latest_artifact_version failed")
        return f"Error: {e}"


@tool
def get_build_info(build_name: str, build_number: str = "latest") -> str:
    """Get Artifactory build info (linked CI builds).
    Args:
      build_name   - build name as registered in Artifactory
      build_number - build number or 'latest' for the most recent"""
    try:
        url, session = _session()
        if build_number == "latest":
            # List all builds first
            resp = session.get(f"{url}/artifactory/api/build/{build_name}", timeout=15)
            resp.raise_for_status()
            builds = resp.json().get("buildsNumbers", [])
            if not builds:
                return f"No builds found for '{build_name}'."
            build_number = sorted(
                [b["uri"].strip("/") for b in builds],
                key=lambda x: x, reverse=True
            )[0]
        resp = session.get(
            f"{url}/artifactory/api/build/{build_name}/{build_number}",
            timeout=15
        )
        resp.raise_for_status()
        info = resp.json().get("buildInfo", {})
        lines = [
            f"Build Name:    {info.get('name', build_name)}",
            f"Build Number:  {info.get('number', build_number)}",
            f"Build Started: {info.get('started', 'N/A')}",
            f"Duration:      {info.get('durationMillis', 0) // 1000}s",
            f"VCS Revision:  {info.get('vcsRevision', 'N/A')}",
            f"Agent:         {info.get('agent', {}).get('name', 'N/A')}",
            f"Modules:       {len(info.get('modules', []))}",
        ]
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("get_build_info failed")
        return f"Error fetching build info: {e}"


# Exported list for orchestrator
artifactory_tools = [
    search_artifact,
    get_artifact_info,
    list_repositories,
    get_latest_artifact_version,
    get_build_info,
]
