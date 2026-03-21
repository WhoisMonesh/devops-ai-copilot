# agent/tools/prometheus_tools.py
# LangChain tools for Prometheus monitoring queries

from __future__ import annotations

import json
import logging

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _get_prometheus_url() -> str:
    """Get Prometheus URL from environment or secrets."""
    import os
    url = os.getenv("PROMETHEUS_URL", "http://prometheus.monitoring.svc:9090")
    if not url:
        raise ValueError("Prometheus URL not configured (PROMETHEUS_URL).")
    return url.rstrip("/")


@tool
def prometheus_query_range(query: str, duration: str = "1h", step: str = "15s") -> str:
    """Execute a Prometheus range query over a time duration.
    Args: query - PromQL query string, duration - time range (e.g., '1h', '30m'), step - query resolution (e.g., '15s', '1m')"""
    try:
        url = _get_prometheus_url()
        import time
        end = int(time.time())
        if duration.endswith('h'):
            start = end - (int(duration[:-1]) * 3600)
        elif duration.endswith('m'):
            start = end - (int(duration[:-1]) * 60)
        elif duration.endswith('s'):
            start = end - int(duration[:-1])
        else:
            start = end - 3600  # default 1h
        
        params = {
            'query': query,
            'start': start,
            'end': end,
            'step': step
        }
        
        resp = requests.get(f"{url}/api/v1/query_range", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        if data["status"] != "success":
            return f"Prometheus query failed: {data.get('error', 'Unknown error')}"
        
        result = data["data"]["result"]
        if not result:
            return "No data returned for query"
            
        # Format result for readability
        formatted_results = []
        for series in result[:10]:  # Limit to first 10 series
            metric = series.get("metric", {})
            values = series.get("values", [])
            
            # Get latest value
            if values:
                latest_timestamp, latest_value = values[-1]
                formatted_results.append({
                    "metric": metric,
                    "latest_value": latest_value,
                    "latest_timestamp": latest_timestamp,
                    "data_points": len(values)
                })
        
        return json.dumps({
            "query": query,
            "duration": duration,
            "step": step,
            "results": formatted_results,
            "total_series": len(result)
        }, indent=2)
        
    except Exception as exc:
        logger.error("prometheus_query_range failed: %s", exc)
        return f"Error: {exc}"


@tool
def prometheus_query_instant(query: str) -> str:
    """Execute a Prometheus instant query (current value).
    Args: query - PromQL query string"""
    try:
        url = _get_prometheus_url()
        params = {'query': query}
        
        resp = requests.get(f"{url}/api/v1/query", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if data["status"] != "success":
            return f"Prometheus query failed: {data.get('error', 'Unknown error')}"
        
        result = data["data"]["result"]
        if not result:
            return "No data returned for query"
            
        # Format result for readability
        formatted_results = []
        for series in result[:10]:  # Limit to first 10 series
            metric = series.get("metric", {})
            value = series.get("value", [None, None])
            formatted_results.append({
                "metric": metric,
                "value": value[1] if len(value) > 1 else value[0],
                "timestamp": value[0] if len(value) > 1 else None
            })
        
        return json.dumps({
            "query": query,
            "results": formatted_results,
            "total_series": len(result)
        }, indent=2)
        
    except Exception as exc:
        logger.error("prometheus_query_instant failed: %s", exc)
        return f"Error: {exc}"


@tool
def prometheus_get_series(match: str = "", limit: int = 10) -> str:
    """Get list of time series that match a label matcher.
    Args: match - label matcher (e.g., 'up', 'http_requests_total{job=\"apiserver\"}'), limit - max results"""
    try:
        url = _get_prometheus_url()
        params = {'match[]': match}
        if limit:
            params['limit'] = limit
        
        resp = requests.get(f"{url}/api/v1/series", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if data["status"] != "success":
            return f"Prometheus series query failed: {data.get('error', 'Unknown error')}"
        
        result = data["data"]
        return json.dumps({
            "match": match,
            "series": result,
            "count": len(result)
        }, indent=2)
        
    except Exception as exc:
        logger.error("prometheus_get_series failed: %s", exc)
        return f"Error: {exc}"


@tool
def prometheus_get_label_values(label: str) -> str:
    """Get all possible values for a label name.
    Args: label - label name (e.g., 'job', 'instance', 'namespace')"""
    try:
        url = _get_prometheus_url()
        params = {'match[]': '{__name__=~".+"}'}  # Match all metrics
        
        resp = requests.get(f"{url}/api/v1/label/{label}/values", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if data["status"] != "success":
            return f"Prometheus label values query failed: {data.get('error', 'Unknown error')}"
        
        result = data["data"]
        return json.dumps({
            "label": label,
            "values": result,
            "count": len(result)
        }, indent=2)
        
    except Exception as exc:
        logger.error("prometheus_get_label_values failed: %s", exc)
        return f"Error: {exc}"


@tool
def prometheus_alerts(state: str = "active") -> str:
    """Get current alerts from Prometheus Alertmanager.
    Args: filter by alert state - 'active', 'pending', 'suppressed', 'inactive'"""
    try:
        url = _get_prometheus_url()
        params = {}
        if state:
            params['active'] = 'true' if state == 'active' else 'false'
        
        resp = requests.get(f"{url}/api/v1/alerts", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if data["status"] != "success":
            return f"Prometheus alerts query failed: {data.get('error', 'Unknown error')}"
        
        result = data["data"]
        return json.dumps({
            "state": state,
            "alerts": result,
            "count": len(result)
        }, indent=2)
        
    except Exception as exc:
        logger.error("prometheus_alerts failed: %s", exc)
        return f"Error: {exc}"


PROMETHEUS_TOOLS = [
    prometheus_query_range,
    prometheus_query_instant,
    prometheus_get_series,
    prometheus_get_label_values,
    prometheus_alerts,
]
