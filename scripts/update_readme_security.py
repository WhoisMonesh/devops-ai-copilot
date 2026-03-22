#!/usr/bin/env python3
"""Update README.md with latest Trivy security scan results."""

import json
import os
import sys
from datetime import datetime, timezone

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <commit-sha>", file=sys.stderr)
        sys.exit(1)

    commit = sys.argv[1]
    trivy_dir = "trivy-results"
    readme_path = "README.md"

    # Collect vuln counts from all images
    images = ["agent", "gui", "ollama-qwen", "ollama-mistral"]
    per_image = {}

    for img in images:
        json_file = f"{trivy_dir}/trivy-results-{img}.json"
        summary = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
        if os.path.exists(json_file):
            with open(json_file) as f:
                data = json.load(f)
            for r in data.get("Results", []):
                for v in (r.get("Vulnerabilities") or []):
                    sev = v.get("Severity", "UNKNOWN")
                    if sev in summary:
                        summary[sev] += 1
        per_image[img] = summary

    total_vulns = sum(sum(per_image[img].values()) for img in images)
    total_crit = sum(per_image[img]["CRITICAL"] for img in images)
    total_high = sum(per_image[img]["HIGH"] for img in images)
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def make_key(img, sev):
        key = f"{img.upper()}_{sev}"
        return f"<!--{key}-->"

    # Build placeholder replacements
    replacements = {}
    for img in images:
        key_prefix = img.upper()
        replacements[f"<!--{key_prefix}_CRITICAL-->"] = str(per_image[img]["CRITICAL"])
        replacements[f"<!--{key_prefix}_HIGH-->"] = str(per_image[img]["HIGH"])
        replacements[f"<!--{key_prefix}_MEDIUM-->"] = str(per_image[img]["MEDIUM"])
        replacements[f"<!--{key_prefix}_LOW-->"] = str(per_image[img]["LOW"])
        replacements[f"<!--{key_prefix}_TOTAL-->"] = str(sum(per_image[img].values()))
    replacements["<!--COMMIT_SHA-->"] = commit[:12]
    replacements["<!--SCAN_DATE-->"] = scan_date

    # Read current README
    with open(readme_path) as f:
        content = f.read()

    # Replace all placeholders
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    with open(readme_path, "w") as f:
        f.write(content)

    print(f"Updated {readme_path} with scan results for commit {commit[:12]}")
    print(f"Total vulns: {total_vulns} (CRITICAL: {total_crit}, HIGH: {total_high})")
    for img in images:
        s = per_image[img]
        print(f"  {img}: CRITICAL={s['CRITICAL']} HIGH={s['HIGH']} MEDIUM={s['MEDIUM']} LOW={s['LOW']} TOTAL={sum(s.values())}")

    if total_crit > 0 or total_high > 0:
        print("WARNING: High-severity vulnerabilities detected!")

if __name__ == "__main__":
    main()
