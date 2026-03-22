# agent/tools/nginx_tool.py - Nginx Access/Error Log Tool
import os
import re
import json
from collections import Counter
from datetime import datetime, timedelta
from langchain.tools import tool
import logging

logger = logging.getLogger(__name__)

NGINX_ACCESS_LOG = os.getenv("NGINX_ACCESS_LOG", "/var/log/nginx/access.log")
NGINX_ERROR_LOG  = os.getenv("NGINX_ERROR_LOG",  "/var/log/nginx/error.log")

# Combined log format pattern
LOG_PATTERN = re.compile(
    r'(?P<ip>[\d\.]+) - - \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) \S+" '
    r'(?P<status>\d{3}) (?P<size>\d+) '
    r'"(?P<referer>[^"]*)" "(?P<ua>[^"]*)"'
)

def _read_last_lines(filepath: str, n: int = 2000) -> list:
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
        return lines[-n:]
    except FileNotFoundError:
        return []
    except OSError:
        # Intentionally catches file read errors (permission denied, I/O errors, etc.)
        return []

@tool
def get_nginx_5xx_errors(last_minutes: int = 30) -> str:
    """Get all 5xx HTTP errors from Nginx access logs within last N minutes.
    Args: last_minutes - time window in minutes to look back"""
    try:
        lines = _read_last_lines(NGINX_ACCESS_LOG)
        errors = []
        cutoff = datetime.utcnow() - timedelta(minutes=last_minutes)
        for line in lines:
            m = LOG_PATTERN.match(line)
            if m and m.group("status").startswith("5"):
                try:
                    ts = datetime.strptime(m.group("time").split()[0], "%d/%b/%Y:%H:%M:%S")
                    if ts >= cutoff:
                        errors.append({
                            "ip": m.group("ip"),
                            "time": m.group("time"),
                            "method": m.group("method"),
                            "path": m.group("path"),
                            "status": m.group("status"),
                            "size": m.group("size")
                        })
                except ValueError:
                    # Skip lines with unparseable timestamps
                    pass
        status_counts = Counter(e["status"] for e in errors)
        return json.dumps({
            "total_5xx": len(errors),
            "by_status": dict(status_counts),
            "errors": errors[:50]
        }, indent=2)
    except OSError:
        # Intentionally catches file read errors
        return "Nginx error: unable to read access log"

@tool
def get_nginx_top_endpoints(last_minutes: int = 60, top_n: int = 10) -> str:
    """Get top N most requested endpoints from Nginx access logs.
    Args: last_minutes - time window, top_n - number of top endpoints to return"""
    try:
        lines = _read_last_lines(NGINX_ACCESS_LOG)
        paths = []
        cutoff = datetime.utcnow() - timedelta(minutes=last_minutes)
        for line in lines:
            m = LOG_PATTERN.match(line)
            if m:
                try:
                    ts = datetime.strptime(m.group("time").split()[0], "%d/%b/%Y:%H:%M:%S")
                    if ts >= cutoff:
                        paths.append(m.group("path").split("?")[0])
                except ValueError:
                    # Skip lines with unparseable timestamps
                    pass
        counts = Counter(paths).most_common(top_n)
        return json.dumps({
            "window_minutes": last_minutes,
            "total_requests": len(paths),
            "top_endpoints": [{"path": p, "count": c} for p, c in counts]
        }, indent=2)
    except OSError:
        # Intentionally catches file read errors
        return "Nginx error: unable to read access log"

@tool
def get_nginx_status_summary(last_minutes: int = 60) -> str:
    """Get HTTP status code distribution from Nginx access logs.
    Args: last_minutes - time window in minutes"""
    try:
        lines = _read_last_lines(NGINX_ACCESS_LOG)
        statuses = []
        ips = []
        cutoff = datetime.utcnow() - timedelta(minutes=last_minutes)
        for line in lines:
            m = LOG_PATTERN.match(line)
            if m:
                try:
                    ts = datetime.strptime(m.group("time").split()[0], "%d/%b/%Y:%H:%M:%S")
                    if ts >= cutoff:
                        statuses.append(m.group("status"))
                        ips.append(m.group("ip"))
                except ValueError:
                    # Skip lines with unparseable timestamps
                    pass
        status_dist = Counter(statuses)
        top_ips = Counter(ips).most_common(5)
        total = len(statuses)
        error_rate = round(
            sum(v for k, v in status_dist.items() if k.startswith(("4","5"))) / total * 100, 2
        ) if total > 0 else 0
        return json.dumps({
            "window_minutes": last_minutes,
            "total_requests": total,
            "error_rate_pct": error_rate,
            "status_distribution": dict(status_dist),
            "top_client_ips": [{"ip": ip, "requests": c} for ip, c in top_ips]
        }, indent=2)
    except OSError:
        # Intentionally catches file read errors
        return "Nginx error: unable to read access log"

@tool
def get_nginx_error_log(last_lines: int = 50) -> str:
    """Read the last N lines from Nginx error log.
    Args: last_lines - number of lines to read from the error log"""
    try:
        lines = _read_last_lines(NGINX_ERROR_LOG, n=last_lines)
        if not lines:
            return "No nginx error log found or log is empty"
        return "".join(lines)
    except OSError:
        # Intentionally catches file read errors
        return "Nginx error: unable to read error log"

def get_nginx_tools():
    return [get_nginx_5xx_errors, get_nginx_top_endpoints, get_nginx_status_summary, get_nginx_error_log]
