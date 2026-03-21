# agent/tools/cloudwatch_tool.py
# AWS CloudWatch and CloudTrail logs tools for DevOps AI Copilot

import logging
import os
from datetime import datetime, timedelta

import boto3
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def _get_logs_client():
    kwargs = {"region_name": AWS_REGION}
    key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if key_id and secret:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("logs", **kwargs)


def _get_cloudwatch_client():
    kwargs = {"region_name": AWS_REGION}
    key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if key_id and secret:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("cloudwatch", **kwargs)


@tool
def cloudwatch_logs(log_group: str, filter_pattern: str = "", hours: int = 1, limit: int = 50) -> str:
    """Query CloudWatch Logs.
    Args:
      log_group - CloudWatch log group name (e.g., /aws/lambda/my-function)
      filter_pattern - Optional filter pattern (e.g., ERROR, json)
      hours - Time window in hours (default: 1)
      limit - Max number of log events to return (default: 50)"""
    try:
        client = _get_logs_client()
        start_time = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        end_time = int(datetime.now().timestamp() * 1000)

        kwargs = {
            "logGroupName": log_group,
            "startTime": start_time,
            "endTime": end_time,
            "limit": limit,
            "interleaved": True,
        }
        if filter_pattern:
            kwargs["filterPattern"] = filter_pattern

        resp = client.filter_log_events(**kwargs)
        events = resp.get("events", [])

        if not events:
            return f"No CloudWatch logs found for '{log_group}' in last {hours}h."

        lines = [f"CloudWatch Logs: {log_group} ({len(events)} events in last {hours}h):"]
        for e in events[:limit]:
            ts = datetime.fromtimestamp(e["timestamp"] / 1000).strftime("%H:%M:%S")
            msg = e.get("message", "")[:150]
            lines.append(f"  [{ts}] {msg}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("cloudwatch_logs failed")
        return f"Error querying CloudWatch logs: {e}"


@tool
def cloudwatch_metrics(namespace: str, metric_name: str = "", stat: str = "Average", minutes: int = 60) -> str:
    """Get CloudWatch metrics.
    Args:
      namespace - AWS namespace (e.g., AWS/EC2, AWS/Lambda)
      metric_name - Metric name (e.g., CPUUtilization, Errors)
      stat - Statistic: Average, Sum, Maximum, Minimum (default: Average)
      minutes - Time window in minutes (default: 60)"""
    try:
        client = _get_cloudwatch_client()
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=minutes)

        kwargs = {
            "Namespace": namespace,
            "StartTime": start_time,
            "EndTime": end_time,
            "Period": max(60, minutes * 60 // 100),
            "Statistics": [stat],
        }
        if metric_name:
            kwargs["MetricName"] = metric_name

        resp = client.get_metric_statistics(**kwargs)
        datapoints = resp.get("Datapoints", [])

        if not datapoints:
            return f"No metrics found for {namespace}/{metric_name or '*'}"

        lines = [f"CloudWatch Metrics: {namespace}/{metric_name or '*'} ({stat}, last {minutes}m)"]
        for dp in sorted(datapoints, key=lambda x: x["Timestamp"]):
            ts = dp["Timestamp"].strftime("%H:%M:%S")
            val = dp[stat]
            lines.append(f"  [{ts}] {val:.2f}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("cloudwatch_metrics failed")
        return f"Error getting CloudWatch metrics: {e}"


@tool
def cloudwatch_dashboards() -> str:
    """List all CloudWatch Dashboards."""
    try:
        client = _get_cloudwatch_client()
        resp = client.list_dashboards()
        dashboards = resp.get("DashboardEntries", [])

        if not dashboards:
            return "No CloudWatch Dashboards found."

        lines = [f"CloudWatch Dashboards ({len(dashboards)}):"]
        for d in dashboards:
            lines.append(f"  {d['DashboardName']} | Modified: {d.get('LastModified', 'N/A')[:16]}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("cloudwatch_dashboards failed")
        return f"Error listing dashboards: {e}"


@tool
def cloudtrail_events(hours: int = 1, event_name: str = "", limit: int = 50) -> str:
    """Query CloudTrail events.
    Args:
      hours - Time window in hours (default: 1)
      event_name - Optional event name filter (e.g., DescribeInstances, CreateBucket)
      limit - Max events to return (default: 50)"""
    try:
        client = boto3.client("cloudtrail", region_name=AWS_REGION)
        start_time = datetime.now() - timedelta(hours=hours)

        kwargs = {
            "StartTime": start_time,
            "MaxResults": limit,
        }
        if event_name:
            kwargs["LookupAttributes"] = [{"AttributeKey": "EventName", "AttributeValue": event_name}]

        resp = client.lookup_events(**kwargs)
        events = resp.get("Events", [])

        if not events:
            return f"No CloudTrail events found in last {hours}h."

        lines = [f"CloudTrail Events (last {hours}h, {len(events)}):"]
        for e in events:
            ts = e["EventTime"].strftime("%H:%M:%S")
            name = e["EventName"]
            user = e.get("Username", "AWSService")
            lines.append(f"  [{ts}] {name} | User: {user}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("cloudtrail_events failed")
        return f"Error querying CloudTrail: {e}"


@tool
def cloudwatch_alarms(state: str = "ALARM") -> str:
    """List CloudWatch alarms by state.
    Args:
      state - Alarm state: ALARM, OK, INSUFFICIENT_DATA (default: ALARM)"""
    try:
        client = _get_cloudwatch_client()
        resp = client.describe_alarms(
            AlarmTypes=["MetricAlarms"],
            StateValue=state,
        )
        alarms = resp.get("MetricAlarms", [])

        if not alarms:
            return f"No {state} CloudWatch alarms found."

        lines = [f"CloudWatch Alarms ({state}) - {len(alarms)}:"]
        for a in alarms:
            lines.append(f"  {a['AlarmName']} | {a.get('StateValue', state)}")
            lines.append(f"    Metric: {a['Namespace']}/{a['MetricName']}")
            lines.append(f"    Reason: {a.get('StateReason', 'N/A')[:80]}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("cloudwatch_alarms failed")
        return f"Error listing CloudWatch alarms: {e}"


CLOUDWATCH_TOOLS = [
    cloudwatch_logs,
    cloudwatch_metrics,
    cloudwatch_dashboards,
    cloudtrail_events,
    cloudwatch_alarms,
]
