# agent/tools/pagerduty_tool.py
# PagerDuty alerting tools for DevOps AI Copilot

import logging
import os

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

PAGERDUTY_TOKEN = os.getenv("PAGERDUTY_TOKEN", "")
PAGERDUTY_API_URL = os.getenv("PAGERDUTY_API_URL", "https://api.pagerduty.com")


def _pd_headers():
    return {
        "Authorization": f"Token token={PAGERDUTY_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.pagerduty+json;version=2",
    }


@tool
def pd_list_incidents(status: str = "triggered", urgency: str = "all") -> str:
    """List PagerDuty incidents.
    Args:
      status - Filter by status: triggered, acknowledged, resolved (default: triggered)
      urgency - Filter by urgency: high, low, all (default: all)"""
    try:
        if not PAGERDUTY_TOKEN:
            return "PAGERDUTY_TOKEN env var not set"

        params = {
            "sort_by": "created_at:desc",
            "limit": 25,
            "statuses[]": [status] if status != "all" else ["triggered", "acknowledged"],
        }
        if urgency != "all":
            params["urgencies[]"] = [urgency]

        resp = requests.get(
            f"{PAGERDUTY_API_URL}/incidents",
            headers=_pd_headers(),
            params=params,
            timeout=15,
        )
        if resp.status_code == 400:
            # Try alternate param format
            params = {
                "sort_by": "created_at:desc",
                "limit": 25,
                "status": status,
            }
            resp = requests.get(
                f"{PAGERDUTY_API_URL}/incidents",
                headers=_pd_headers(),
                params=params,
                timeout=15,
            )
        resp.raise_for_status()
        data = resp.json()
        incidents = data.get("incidents", [])

        if not incidents:
            return f"No {status} incidents found."

        lines = [f"PagerDuty Incidents ({status}) - {len(incidents)}:"]
        for inc in incidents:
            created = inc["created_at"][:16]
            title = inc["title"]
            service = inc["service"]["name"]
            assignee = inc.get("assignments", [{}])[0].get("assignee", {}).get("summary", "Unassigned")
            lines.append(f"  [{inc['urgency']}] {inc['id']} | {title}")
            lines.append(f"    Service: {service} | Assignee: {assignee} | {created}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("pd_list_incidents failed")
        return f"Error listing incidents: {e}"


@tool
def pd_get_incident_details(incident_id: str) -> str:
    """Get detailed information about a specific incident.
    Args:
      incident_id - PagerDuty incident ID"""
    try:
        if not PAGERDUTY_TOKEN:
            return "PAGERDUTY_TOKEN env var not set"

        resp = requests.get(
            f"{PAGERDUTY_API_URL}/incidents/{incident_id}",
            headers=_pd_headers(),
            params={"include[]": ["assignments", "previous_assignments", "business_hour"]},
            timeout=15,
        )
        resp.raise_for_status()
        inc = resp.json()

        lines = [
            f"PagerDuty Incident: {incident_id}",
            f"  Title: {inc['title']}",
            f"  Status: {inc['status']} | Urgency: {inc['urgency']}",
            f"  Service: {inc['service']['summary']}",
            f"  Created: {inc['created_at'][:16]}",
            f"  Description: {inc.get('description', 'N/A')}",
        ]

        # Get timeline
        timeline_resp = requests.get(
            f"{PAGERDUTY_API_URL}/incidents/{incident_id}/log_entries",
            headers=_pd_headers(),
            params={"limit": 10},
            timeout=15,
        )
        if timeline_resp.ok:
            entries = timeline_resp.json().get("log_entries", [])
            if entries:
                lines.append("  Recent Timeline:")
                for entry in entries[:5]:
                    lines.append(f"    [{entry['created_at'][:16]}] {entry['type']} - {entry.get('summary', '')}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("pd_get_incident_details failed")
        return f"Error getting incident details: {e}"


@tool
def pd_manage_incident(incident_id: str, action: str, note: str = "") -> str:
    """Manage a PagerDuty incident (acknowledge, resolve, reassign).
    Args:
      incident_id - PagerDuty incident ID
      action - Action to take: acknowledge, resolve, or reassign
      note - Optional note to add to the incident"""
    try:
        if not PAGERDUTY_TOKEN:
            return "PAGERDUTY_TOKEN env var not set"

        payload = {"incident": {"type": "incident_reference"}}
        if action == "acknowledge":
            payload["incident"]["status"] = "acknowledged"
        elif action == "resolve":
            payload["incident"]["status"] = "resolved"
        else:
            return f"Unknown action: {action}. Use 'acknowledge' or 'resolve'."

        resp = requests.put(
            f"{PAGERDUTY_API_URL}/incidents/{incident_id}",
            headers=_pd_headers(),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()

        result_msg = f"Incident {incident_id} has been {action}d."
        if note:
            # Add note
            note_resp = requests.post(
                f"{PAGERDUTY_API_URL}/incidents/{incident_id}/notes",
                headers=_pd_headers(),
                json={"note": {"content": note}},
                timeout=15,
            )
            if note_resp.ok:
                result_msg += f" Note added: {note}"

        return result_msg
    except Exception as e:
        logger.exception("pd_manage_incident failed")
        return f"Error managing incident: {e}"


@tool
def pd_list_alert_groups(status: str = "firing") -> str:
    """List PagerDuty alert groups (for Event Intelligence).
    Args:
      status - Filter: firing, resolved (default: firing)"""
    try:
        if not PAGERDUTY_TOKEN:
            return "PAGERDUTY_TOKEN env var not set"

        # Try the alert groups API
        resp = requests.get(
            f"{PAGERDUTY_API_URL}/alert_groups",
            headers=_pd_headers(),
            params={"status[]": [status], "limit": 25},
            timeout=15,
        )
        if resp.status_code == 404:
            return "Alert Groups API not available on this plan."

        resp.raise_for_status()
        data = resp.json()
        groups = data.get("alert_groups", [])

        if not groups:
            return f"No {status} alert groups found."

        lines = [f"PagerDuty Alert Groups ({status}) - {len(groups)}:"]
        for g in groups:
            lines.append(f"  [{g['status']}] {g['id']} | {g.get('service_name', 'N/A')}")
            lines.append(f"    Suppressed: {g.get('suppressed_count', 0)} | Triggered: {g.get('triggered_count', 0)}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("pd_list_alert_groups failed")
        return f"Error listing alert groups: {e}"


@tool
def pd_get_oncall() -> str:
    """Get current on-call users for all escalation policies."""
    try:
        if not PAGERDUTY_TOKEN:
            return "PAGERDUTY_TOKEN env var not set"

        resp = requests.get(
            f"{PAGERDUTY_API_URL}/oncalls",
            headers=_pd_headers(),
            params={"limit": 50},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        oncalls = data.get("oncalls", [])

        if not oncalls:
            return "No on-call users found."

        # Group by escalation policy
        by_policy = {}
        for oc in oncalls:
            policy = oc.get("escalation_policy", {}).get("summary", "Unknown")
            if policy not in by_policy:
                by_policy[policy] = []
            user = oc.get("user", {}).get("summary", "Unknown")
            by_policy[policy].append(user)

        lines = ["PagerDuty On-Call:"]
        for policy, users in by_policy.items():
            lines.append(f"  Policy: {policy}")
            for u in users:
                lines.append(f"    -> {u}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("pd_get_oncall failed")
        return f"Error getting on-call: {e}"


PAGERDUTY_TOOLS = [
    pd_list_incidents,
    pd_get_incident_details,
    pd_manage_incident,
    pd_list_alert_groups,
    pd_get_oncall,
]
