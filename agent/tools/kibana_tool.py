# agent/tools/kibana_tool.py
# All connection details (Elasticsearch URL, Kibana URL, username, password)
# come from config.infra - set via env vars or GUI -> hot-reload

import json
import logging
from datetime import datetime, timedelta

import requests
from requests.auth import HTTPBasicAuth
from elasticsearch import Elasticsearch
from langchain.tools import tool

from config import config
from agent.secrets import kibana

logger = logging.getLogger(__name__)


def _es_client() -> Elasticsearch:
    """Build Elasticsearch client from config. Raises if URL not set."""
    es_url = config.infra.elasticsearch_url.strip()
    if not es_url:
        raise ValueError(
            "Elasticsearch URL is not configured. "
            "Set ELASTICSEARCH_URL env var or update via the GUI Configuration page."
        )
    # Try secrets first (from AWS Secrets Manager)
    secret_data = kibana.all()
    user = secret_data.get("username", "") or secret_data.get("elasticsearch_username", "")
    password = secret_data.get("password", "") or secret_data.get("elasticsearch_password", "")
    if user and password:
        return Elasticsearch(es_url, basic_auth=(user, password), verify_certs=False)
    return Elasticsearch(es_url, verify_certs=False)


def _kibana_get(path: str, params: dict = None) -> dict:
    """Authenticated GET to Kibana REST API."""
    base = config.infra.kibana_url.rstrip("/")
    if not base:
        raise ValueError(
            "Kibana URL is not configured. "
            "Set KIBANA_URL env var or update via the GUI Configuration page."
        )
    secret_data = kibana.all()
    user = secret_data.get("username", "")
    password = secret_data.get("password", "")
    headers = {"kbn-xsrf": "true", "Content-Type": "application/json"}
    auth = HTTPBasicAuth(user, password) if user and password else None
    resp = requests.get(
        f"{base}{path}",
        auth=auth,
        headers=headers,
        params=params,
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    return resp.json()


def _kibana_post(path: str, body: dict = None) -> dict:
    """Authenticated POST to Kibana REST API."""
    base = config.infra.kibana_url.rstrip("/")
    if not base:
        raise ValueError("Kibana URL is not configured.")
    secret_data = kibana.all()
    user = secret_data.get("username", "")
    password = secret_data.get("password", "")
    headers = {"kbn-xsrf": "true", "Content-Type": "application/json"}
    auth = HTTPBasicAuth(user, password) if user and password else None
    resp = requests.post(
        f"{base}{path}",
        auth=auth,
        headers=headers,
        json=body or {},
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# LangChain Tools
# ---------------------------------------------------------------------------

@tool
def search_error_logs(service: str, minutes: int = 30, size: int = 20) -> str:
    """Search for ERROR/WARN logs in Elasticsearch for a specific service.
    Args:
      service - service or app name to filter logs (e.g. 'nginx', 'api-gateway')
      minutes - time window in minutes to look back (default 30)
      size    - max number of log entries to return (default 20)"""
    try:
        es = _es_client()
        since = datetime.utcnow() - timedelta(minutes=minutes)
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"service.name": service}},
                        {"terms": {"log.level": ["ERROR", "WARN", "error", "warn"]}},
                        {"range": {"@timestamp": {"gte": since.isoformat()}}},
                    ]
                }
            },
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": size,
        }
        result = es.search(index="logs-*,filebeat-*", body=query)
        hits = result["hits"]["hits"]
        if not hits:
            return f"No ERROR/WARN logs found for '{service}' in last {minutes} minutes."
        lines = [f"Found {len(hits)} error/warn log(s) for '{service}' (last {minutes} min):"]
        for h in hits:
            src = h["_source"]
            ts = src.get("@timestamp", "N/A")
            level = src.get("log", {}).get("level") or src.get("level", "?")
            msg = src.get("message", src.get("log", {}).get("original", "N/A"))
            lines.append(f"  [{ts}] [{level}] {msg[:200]}")
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("search_error_logs failed")
        return f"Error searching logs: {e}"


@tool
def search_logs_by_query(index: str, query_string: str, minutes: int = 60, size: int = 20) -> str:
    """Run a free-text Elasticsearch query against any index.
    Args:
      index        - Elasticsearch index pattern (e.g. 'logs-*', 'filebeat-*', 'nginx-*')
      query_string - Lucene query string (e.g. 'status:500 AND path:/api/login')
      minutes      - time window in minutes to look back (default 60)
      size         - max log entries to return (default 20)"""
    try:
        es = _es_client()
        since = datetime.utcnow() - timedelta(minutes=minutes)
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"query_string": {"query": query_string}},
                        {"range": {"@timestamp": {"gte": since.isoformat()}}},
                    ]
                }
            },
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": size,
        }
        result = es.search(index=index, body=query)
        hits = result["hits"]["hits"]
        total = result["hits"]["total"]["value"]
        if not hits:
            return f"No results for query '{query_string}' on index '{index}'."
        lines = [f"Total matches: {total} | Showing: {len(hits)} | Index: {index}"]
        for h in hits:
            src = h["_source"]
            ts = src.get("@timestamp", "N/A")
            msg = src.get("message", json.dumps(src)[:300])
            lines.append(f"  [{ts}] {msg[:250]}")
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("search_logs_by_query failed")
        return f"Error querying Elasticsearch: {e}"


@tool
def get_kibana_dashboards(search: str = "") -> str:
    """List Kibana dashboards, optionally filtered by name.
    Args: search - optional name filter (empty returns all dashboards)"""
    try:
        params = {"type": "dashboard", "per_page": 50}
        if search:
            params["search"] = search
        data = _kibana_get("/api/saved_objects/_find", params=params)
        items = data.get("saved_objects", [])
        if not items:
            return "No dashboards found."
        lines = [f"Found {len(items)} Kibana dashboard(s):"]
        for d in items:
            title = d.get("attributes", {}).get("title", "Untitled")
            did = d.get("id", "?")
            lines.append(f"  - [{did}] {title}")
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("get_kibana_dashboards failed")
        return f"Error fetching Kibana dashboards: {e}"


@tool
def get_log_count_by_level(service: str, minutes: int = 60) -> str:
    """Get log count breakdown by level (ERROR, WARN, INFO) for a service.
    Args:
      service - service or app name
      minutes - time window in minutes (default 60)"""
    try:
        es = _es_client()
        since = datetime.utcnow() - timedelta(minutes=minutes)
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"service.name": service}},
                        {"range": {"@timestamp": {"gte": since.isoformat()}}},
                    ]
                }
            },
            "aggs": {
                "by_level": {
                    "terms": {"field": "log.level", "size": 10}
                }
            },
            "size": 0,
        }
        result = es.search(index="logs-*,filebeat-*", body=query)
        buckets = result.get("aggregations", {}).get("by_level", {}).get("buckets", [])
        total = result["hits"]["total"]["value"]
        if not buckets:
            return f"No logs found for '{service}' in last {minutes} minutes."
        lines = [f"Log levels for '{service}' (last {minutes} min, total={total}):'"]
        for b in buckets:
            lines.append(f"  {b['key']:10} : {b['doc_count']}")
        return "\n".join(lines)
    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        logger.exception("get_log_count_by_level failed")
        return f"Error: {e}"


# Exported list for orchestrator
kibana_tools = [
    search_error_logs,
    search_logs_by_query,
    get_kibana_dashboards,
    get_log_count_by_level,
]
