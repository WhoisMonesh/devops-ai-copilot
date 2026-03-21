#!/usr/bin/env python3
# scripts/ingest_logs.py
# Periodic log ingestion script - collects data from all infra sources
# and writes structured JSON lines to a rolling log file for offline analysis.
#
# Usage:
#   python scripts/ingest_logs.py --output /var/log/devops-copilot/collected.jsonl
#   python scripts/ingest_logs.py --once   # single run then exit
#
# Schedule via Kubernetes CronJob or cron on EKS worker node.

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("ingest_logs")

# ---------------------------------------------------------------------------
# Source collectors
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = int(os.getenv("INGEST_TIMEOUT", "10"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_nginx_errors(nginx_error_log: str = "/var/log/nginx/error.log") -> list[dict]:
    """Read last 200 lines of the Nginx error log."""
    path = Path(nginx_error_log)
    if not path.exists():
        logger.warning("Nginx error log not found: %s", nginx_error_log)
        return []
    try:
        lines = path.read_text(errors="replace").splitlines()[-200:]
        return [
            {"source": "nginx", "type": "error_log", "line": line, "ts": _now_iso()}
            for line in lines if line.strip()
        ]
    except Exception as exc:
        logger.error("collect_nginx_errors: %s", exc)
        return []


def collect_jenkins_failed_builds() -> list[dict]:
    """Fetch failed Jenkins builds via REST API."""
    url = os.getenv("JENKINS_URL", "").rstrip("/")
    username = os.getenv("JENKINS_USERNAME", "")
    api_token = os.getenv("JENKINS_API_TOKEN", "")
    if not url:
        logger.info("JENKINS_URL not set, skipping Jenkins ingestion")
        return []
    try:
        resp = requests.get(
            f"{url}/api/json",
            params={"tree": "jobs[name,color,lastBuild[number,result,timestamp,url]]"},
            auth=(username, api_token),
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        records = []
        for job in jobs:
            lb = job.get("lastBuild") or {}
            records.append({
                "source": "jenkins",
                "type": "build",
                "job": job.get("name"),
                "color": job.get("color"),
                "build_number": lb.get("number"),
                "result": lb.get("result"),
                "timestamp": lb.get("timestamp"),
                "build_url": lb.get("url"),
                "ts": _now_iso(),
            })
        return records
    except Exception as exc:
        logger.error("collect_jenkins_failed_builds: %s", exc)
        return []


def collect_kibana_cluster_health() -> list[dict]:
    """Check Elasticsearch cluster health."""
    es_url = os.getenv("ELASTICSEARCH_URL", "").rstrip("/")
    username = os.getenv("KIBANA_USERNAME", "")
    password = os.getenv("KIBANA_PASSWORD", "")
    if not es_url:
        logger.info("ELASTICSEARCH_URL not set, skipping Kibana ingestion")
        return []
    try:
        resp = requests.get(
            f"{es_url}/_cluster/health",
            auth=(username, password) if username else None,
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return [{
            "source": "elasticsearch",
            "type": "cluster_health",
            **data,
            "ts": _now_iso(),
        }]
    except Exception as exc:
        logger.error("collect_kibana_cluster_health: %s", exc)
        return []


def collect_artifactory_storage() -> list[dict]:
    """Fetch Artifactory storage summary."""
    url = os.getenv("ARTIFACTORY_URL", "").rstrip("/")
    username = os.getenv("ARTIFACTORY_USERNAME", "")
    api_key = os.getenv("ARTIFACTORY_API_KEY", "")
    if not url:
        logger.info("ARTIFACTORY_URL not set, skipping Artifactory ingestion")
        return []
    try:
        resp = requests.get(
            f"{url}/artifactory/api/storageinfo",
            auth=(username, api_key),
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        summary = data.get("storageSummary", {})
        return [{
            "source": "artifactory",
            "type": "storage_summary",
            "total_space": summary.get("fileStoreSummary", {}).get("totalSpace"),
            "used_space": summary.get("fileStoreSummary", {}).get("usedSpace"),
            "free_space": summary.get("fileStoreSummary", {}).get("freeSpace"),
            "ts": _now_iso(),
        }]
    except Exception as exc:
        logger.error("collect_artifactory_storage: %s", exc)
        return []


COLLECTORS = [
    collect_nginx_errors,
    collect_jenkins_failed_builds,
    collect_kibana_cluster_health,
    collect_artifactory_storage,
]


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_jsonl(records: list[dict], output_path: str) -> None:
    """Append records as JSON lines to output file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, default=str) + "\n")
    logger.info("Wrote %d records to %s", len(records), output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_once(output_path: str) -> int:
    """Run all collectors once and write output. Returns number of records written."""
    all_records: list[dict] = []
    for collector in COLLECTORS:
        try:
            records = collector()
            all_records.extend(records)
            logger.info("%s returned %d records", collector.__name__, len(records))
        except Exception as exc:
            logger.error("%s raised: %s", collector.__name__, exc)
    if all_records:
        write_jsonl(all_records, output_path)
    return len(all_records)


def main() -> None:
    parser = argparse.ArgumentParser(description="DevOps AI Copilot - log ingestion script")
    parser.add_argument(
        "--output",
        default=os.getenv("INGEST_OUTPUT", "/tmp/devops-copilot-collected.jsonl"),
        help="Path to output JSONL file",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("INGEST_INTERVAL", "300")),
        help="Polling interval in seconds (default 300 = 5 min)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single collection pass and exit",
    )
    args = parser.parse_args()

    logger.info("Starting DevOps log ingestion | output=%s | interval=%ds", args.output, args.interval)

    if args.once:
        count = run_once(args.output)
        logger.info("Single run complete - %d records collected", count)
        sys.exit(0)

    while True:
        try:
            count = run_once(args.output)
            logger.info("Collection pass complete - %d records | sleeping %ds", count, args.interval)
        except KeyboardInterrupt:
            logger.info("Interrupted - exiting")
            sys.exit(0)
        except Exception as exc:
            logger.error("Unexpected error in main loop: %s", exc)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
