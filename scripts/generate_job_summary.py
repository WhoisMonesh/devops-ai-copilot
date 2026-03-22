#!/usr/bin/env python3
"""Generate GitHub Actions job summary from Trivy results."""

import json
import os
import subprocess

def count_severity(text, severity):
    return text.count(severity)

def main():
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null")
    trivy_dir = "trivy-results"

    lines = []
    lines.append("## Security Scan Results\n")
    lines.append("| Image | Critical | High | Medium | Low |")
    lines.append("|-------|----------|------|--------|-----|")

    total_critical = 0
    total_high = 0

    for img in ["agent", "gui", "ollama"]:
        summary_file = f"{trivy_dir}/trivy-summary-{img}.txt"
        crit = high = med = low = 0
        if os.path.exists(summary_file):
            with open(summary_file) as f:
                content = f.read()
            crit = content.count("CRITICAL")
            high = content.count("HIGH")
            med = content.count("MEDIUM")
            low = content.count("LOW")
        total_critical += crit
        total_high += high
        lines.append(f"| {img} | {crit} | {high} | {med} | {low} |")

    lines.append("")
    lines.append("**Full report:** [security-report artifact](#/./Security%20Report/results)")
    lines.append("")
    lines.append("### Critical Vulnerabilities\n")
    lines.append("```")

    for img in ["agent", "gui", "ollama"]:
        json_file = f"{trivy_dir}/trivy-results-{img}.json"
        if os.path.exists(json_file):
            with open(json_file) as f:
                data = json.load(f)
            crits = []
            for r in data.get("Results", []):
                for v in (r.get("Vulnerabilities") or []):
                    if v.get("Severity") == "CRITICAL":
                        crits.append(f"{v.get('PkgName','?')}@{v.get('InstalledVersion','?')}: {v.get('Title','?')[:80]}")
            if crits:
                lines.append(f"[{img}]")
                for c in crits[:5]:
                    lines.append(f"  - {c}")
                lines.append("")

    lines.append("```")

    output = "\n".join(lines)
    with open(summary_path, "a") as f:
        f.write(output + "\n")

    print(output)
    if total_critical > 0:
        print(f"\nWARNING: {total_critical} critical vulnerabilities detected!")

if __name__ == "__main__":
    main()
