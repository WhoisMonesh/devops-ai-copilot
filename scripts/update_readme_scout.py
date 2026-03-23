#!/usr/bin/env python3
"""Update README.md with latest Docker Scout CVE scan results."""

import json
import os
import sys
from datetime import datetime, timezone
import re


def parse_sarif(sarif_path):
    """Parse SARIF file and extract vulnerability counts."""
    if not os.path.exists(sarif_path):
        return {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0, "total": 0}

    with open(sarif_path) as f:
        data = json.load(f)

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}

    # SARIF format from Docker Scout
    for run in data.get("runs", []):
        for rule in run.get("tool", {}).get("driver", {}).get("rules", []):
            severity = rule.get("properties", {}).get("security-severity", "UNKNOWN")
            if severity in counts:
                counts[severity] += 1

        # Also check results
        for result in run.get("results", []):
            level = result.get("level", "note")
            sev = result.get("ruleId", "UNKNOWN")
            # Try to extract severity from ruleId or properties
            props = result.get("rule", {}).get("properties", {})
            severity = props.get("security-severity", "UNKNOWN")
            if severity in counts:
                if level == "error":
                    counts[severity] += 1

    counts["total"] = sum(counts.values())
    return counts


def main():
    scout_dir = "docker-scout-results"
    readme_path = "README.md"

    images = ["agent", "gui", "ollama-qwen", "ollama-mistral"]
    per_image = {}

    for img in images:
        sarif_file = os.path.join(scout_dir, f"docker-scout-cve-{img}.sarif")
        per_image[img] = parse_sarif(sarif_file)

    total_vulns = sum(per_image[img]["total"] for img in images)
    total_crit = sum(per_image[img]["CRITICAL"] for img in images)
    total_high = sum(per_image[img]["HIGH"] for img in images)
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Read current README
    with open(readme_path) as f:
        content = f.read()

    # Check if Docker Scout section exists
    scout_section_marker = "<!--DOCKER_SCOUT_RESULTS-->"
    if scout_section_marker not in content:
        # Add Docker Scout section after Trivy section
        trivy_section_end = content.find("**Latest scan:**")
        if trivy_section_end != -1:
            # Find the end of that line
            line_end = content.find("\n", trivy_section_end)
            if line_end != -1:
                scout_section = f"""

### Docker Scout Scan

> Scanned with [Docker Scout](https://docker.com/blog/announcing-docker-scout/) on every push to `main`.

| Image | Critical | High | Medium | Low | Total |
|-------|----------|------|--------|-----|-------|
| `agent` | {per_image["agent"]["CRITICAL"]} | {per_image["agent"]["HIGH"]} | {per_image["agent"]["MEDIUM"]} | {per_image["agent"]["LOW"]} | {per_image["agent"]["total"]} |
| `gui` | {per_image["gui"]["CRITICAL"]} | {per_image["gui"]["HIGH"]} | {per_image["gui"]["MEDIUM"]} | {per_image["gui"]["LOW"]} | {per_image["gui"]["total"]} |
| `ollama-qwen` | {per_image["ollama-qwen"]["CRITICAL"]} | {per_image["ollama-qwen"]["HIGH"]} | {per_image["ollama-qwen"]["MEDIUM"]} | {per_image["ollama-qwen"]["LOW"]} | {per_image["ollama-qwen"]["total"]} |
| `ollama-mistral` | {per_image["ollama-mistral"]["CRITICAL"]} | {per_image["ollama-mistral"]["HIGH"]} | {per_image["ollama-mistral"]["MEDIUM"]} | {per_image["ollama-mistral"]["LOW"]} | {per_image["ollama-mistral"]["total"]} |

**Latest Docker Scout scan:** {scan_date}

{scout_section_marker}
"""
                content = content[:line_end + 1] + scout_section + content[line_end + 1:]
    else:
        # Update existing section
        for img in images:
            img_upper = img.upper().replace("-", "_")
            content = re.sub(
                rf"\|\s*`{img}`\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*\d+\s*\|",
                f"| `{img}` | {per_image[img]['CRITICAL']} | {per_image[img]['HIGH']} | {per_image[img]['MEDIUM']} | {per_image[img]['LOW']} | {per_image[img]['total']} |",
                content
            )
        # Update date
        content = re.sub(
            r"\*\*Latest Docker Scout scan:\*\*.*",
            f"**Latest Docker Scout scan:** {scan_date}",
            content
        )

    with open(readme_path, "w") as f:
        f.write(content)

    print(f"Updated {readme_path} with Docker Scout results")
    print(f"Total vulns: {total_vulns} (CRITICAL: {total_crit}, HIGH: {total_high})")
    for img in images:
        s = per_image[img]
        print(f"  {img}: CRITICAL={s['CRITICAL']} HIGH={s['HIGH']} MEDIUM={s['MEDIUM']} LOW={s['LOW']} TOTAL={s['total']}")


if __name__ == "__main__":
    main()
