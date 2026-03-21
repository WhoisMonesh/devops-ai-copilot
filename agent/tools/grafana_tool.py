# agent/tools/grafana_tool.py - Grafana dashboard and alerting integration
from __future__ import annotations

import json
import logging
import os

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

GRAFANA_URL = os.getenv("GRAFANA_URL", "")
GRAFANA_API_KEY = os.getenv("GRAFANA_API_KEY", "")

def _grafana_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if GRAFANA_API_KEY:
        headers["Authorization"] = f"Bearer {GRAFANA_API_KEY}"
    return headers


@tool
def grafana_list_dashboards(limit: int = 20) -> str:
    """List all available Grafana dashboards.
    Args: limit - maximum number of dashboards to return (default: 20)"""
    try:
        url = GRAFANA_URL.rstrip("/") + "/api/search"
        params = {"limit": limit} if GRAFANA_URL else {}
        resp = requests.get(url, headers=_grafana_headers(), params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        dashboards = []
        for d in data[:limit]:
            dashboards.append({
                "uid": d.get("uid"),
                "title": d.get("title"),
                "type": d.get("type"),
                "url": d.get("url"),
                "folder_title": d.get("folderTitle"),
            })
        return json.dumps({"dashboards": dashboards, "count": len(dashboards)}, indent=2)
    except Exception as exc:
        logger.error("grafana_list_dashboards failed: %s", exc)
        return f"Error: {exc}"


@tool
def grafana_get_dashboard(uid: str) -> str:
    """Get a Grafana dashboard by its UID and return panel data.
    Args: uid - Grafana dashboard UID"""
    try:
        url = f"{GRAFANA_URL.rstrip('/')}/api/dashboards/uid/{uid}"
        resp = requests.get(url, headers=_grafana_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        dashboard = data.get("dashboard", {})
        panels = []
        for panel in dashboard.get("panels", []):
            panels.append({
                "id": panel.get("id"),
                "title": panel.get("title"),
                "type": panel.get("type"),
                "grid_pos": panel.get("gridPos"),
            })
        result = {
            "uid": uid,
            "title": dashboard.get("title"),
            "panels": panels,
            "panels_count": len(panels),
        }
        # Include annotations if available
        if "annotations" in dashboard:
            result["annotations"] = list(dashboard["annotations"].keys())
        return json.dumps(result, indent=2)
    except Exception as exc:
        logger.error("grafana_get_dashboard failed: %s", exc)
        return f"Error: {exc}"


@tool
def grafana_query_panel(uid: str, panel_id: int, from_: str = "now-1h", to: str = "now") -> str:
    """Query data from a specific dashboard panel using Grafana query API.
    Args: uid - dashboard UID, panel_id - panel ID, from_ - start time (Prometheus-style, e.g. 'now-1h'), to - end time (e.g. 'now')"""
    try:
        # Get panel info first
        dash_resp = requests.get(
            f"{GRAFANA_URL.rstrip('/')}/api/dashboards/uid/{uid}",
            headers=_grafana_headers(),
            timeout=15,
        )
        dash_resp.raise_for_status()
        dashboard = dash_resp.json().get("dashboard", {})
        panel = next((p for p in dashboard.get("panels", []) if p.get("id") == panel_id), None)
        if not panel:
            return f"Panel {panel_id} not found in dashboard {uid}"
        # Build query from panel targets
        targets = panel.get("targets", [])
        if not targets:
            return f"Panel {panel_id} has no query targets"
        # Use the panel's datasource query
        queries = []
        for t in targets:
            expr = t.get("expr", t.get("target", ""))
            if expr:
                queries.append({"expr": expr, "refId": t.get("refId", "A")})
        if not queries:
            return f"Could not extract PromQL/InfluxQL from panel {panel_id} targets"
        payload = {
            "queries": queries,
            "from": from_,
            "to": to,
        }
        query_resp = requests.post(
            f"{GRAFANA_URL.rstrip('/')}/api/ds/query",
            headers=_grafana_headers(),
            json=payload,
            timeout=30,
        )
        if query_resp.status_code == 400:
            # Try alternative Prometheus query API
            return json.dumps({
                "panel_id": panel_id,
                "panel_title": panel.get("title"),
                "panel_type": panel.get("type"),
                "message": "Panel uses non-Prometheus datasource - raw panel config returned",
                "targets": [
                    {"expr": t.get("expr", ""), "refId": t.get("refId", "")}
                    for t in targets
                ],
            }, indent=2)
        query_resp.raise_for_status()
        qdata = query_resp.json()
        results = []
        for frame in qdata.get("results", {}).values():
            for row in frame.get("frames", []):
                results.append({
                    "ref_id": frame.get("refId"),
                    "frame": row,
                })
        return json.dumps({
            "panel_id": panel_id,
            "panel_title": panel.get("title"),
            "from": from_,
            "to": to,
            "frames": results,
        }, indent=2)
    except Exception as exc:
        logger.error("grafana_query_panel failed: %s", exc)
        return f"Error: {exc}"


@tool
def grafana_list_alerts(limit: int = 50) -> str:
    """List all Grafana alerts across all dashboards.
    Args: limit - maximum number of alerts to return (default: 50)"""
    try:
        url = f"{GRAFANA_URL.rstrip('/')}/api/alerts"
        resp = requests.get(url, headers=_grafana_headers(), params={"limit": limit}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        alerts = []
        for alert in data.get("alerts", [])[:limit]:
            alerts.append({
                "uid": alert.get("uid"),
                "title": alert.get("name"),
                "state": alert.get("state"),
                "dashboard_uid": alert.get("dashboardUID"),
                "panel_id": alert.get("panelId"),
                "rule_url": alert.get("ruleUrl"),
            })
        return json.dumps({
            "alerts": alerts,
            "count": len(alerts),
            "total": data.get("total", len(alerts)),
        }, indent=2)
    except Exception as exc:
        logger.error("grafana_list_alerts failed: %s", exc)
        return f"Error: {exc}"


@tool
def grafana_alert_groups() -> str:
    """Get Grafana alert groups with detailed status per folder/rule.
    Returns current firing, pending, and no-data alert states."""
    try:
        url = f"{GRAFANA_URL.rstrip('/')}/api/alerts/groups"
        resp = requests.get(url, headers=_grafana_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        groups = []
        for group in data:
            folder = group.get("folder", {})
            rules = []
            for rule in group.get("rules", []):
                rules.append({
                    "name": rule.get("name"),
                    "uid": rule.get("uid"),
                    "state": rule.get("state"),
                    "condition": rule.get("condition"),
                })
            groups.append({
                "folder": folder.get("title"),
                "group": group.get("group"),
                "rules": rules,
            })
        return json.dumps({"groups": groups, "count": len(groups)}, indent=2)
    except Exception as exc:
        logger.error("grafana_alert_groups failed: %s", exc)
        return f"Error: {exc}"


@tool
def grafana_get_annotation(range_start: str = "now-1h", range_end: str = "now", limit: int = 100) -> str:
    """Fetch Grafana annotations for a time range (e.g. deployments, alerts).
    Args: range_start - ISO8601 or 'now-Xh' style, range_end - end time, limit - max annotations"""
    try:
        url = f"{GRAFANA_URL.rstrip('/')}/api/annotations"
        params = {"from": range_start, "to": range_end, "limit": limit}
        resp = requests.get(url, headers=_grafana_headers(), params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        annotations = []
        for ann in data:
            annotations.append({
                "id": ann.get("id"),
                "type": ann.get("type"),
                "text": ann.get("text"),
                "tags": ann.get("tags"),
                "time": ann.get("time"),
                "time_end": ann.get("timeEnd"),
            })
        return json.dumps({"annotations": annotations, "count": len(annotations)}, indent=2)
    except Exception as exc:
        logger.error("grafana_get_annotation failed: %s", exc)
        return f"Error: {exc}"


GRAFANA_TOOLS = [
    grafana_list_dashboards,
    grafana_get_dashboard,
    grafana_query_panel,
    grafana_list_alerts,
    grafana_alert_groups,
    grafana_get_annotation,
]
