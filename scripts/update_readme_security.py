#!/usr/bin/env python3
"""Update README.md with latest Trivy security scan results."""

import json
import os
import re
import sys

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <commit-sha>", file=sys.stderr)
        sys.exit(1)

    commit = sys.argv[1]
    trivy_dir = "trivy-results"
    readme_path = "README.md"

    # Collect vuln counts from all images
    images = ["agent", "gui", "ollama"]
    totals = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
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
        for sev in totals:
            totals[sev] += summary[sev]

    total_vulns = sum(totals.values())
    crit = totals["CRITICAL"]
    high = totals["HIGH"]

    # Build new security section
    new_section = f"""## Security Scan

> Scanned with [Trivy](https://github.com/aquasecurity/trivy) on every push to `main`.

| Image | Critical | High | Medium | Low | Total |
|-------|----------|------|--------|-----|-------|
| `agent` | {per_image["agent"]["CRITICAL"]} | {per_image["agent"]["HIGH"]} | {per_image["agent"]["MEDIUM"]} | {per_image["agent"]["LOW"]} | {sum(per_image["agent"].values())} |
| `gui` | {per_image["gui"]["CRITICAL"]} | {per_image["gui"]["HIGH"]} | {per_image["gui"]["MEDIUM"]} | {per_image["gui"]["LOW"]} | {sum(per_image["gui"].values())} |
| `ollama` | {per_image["ollama"]["CRITICAL"]} | {per_image["ollama"]["HIGH"]} | {per_image["ollama"]["MEDIUM"]} | {per_image["ollama"]["LOW"]} | {sum(per_image["ollama"].values())} |

**Latest scan:** `{commit}` — Total: {total_vulns} vulnerabilities (CRITICAL: {crit}, HIGH: {high})

"""

    # Read current README
    with open(readme_path) as f:
        content = f.read()

    # Replace existing Security Scan section if present, else insert after Features
    pattern = r"(?:\n## Security Scan\n>.*?\n\n\| Image.*?\n\n\*\*Latest scan:.*?\n\n)"
    if re.search(pattern, content, re.DOTALL):
        new_content = re.sub(pattern, new_section, content, flags=re.DOTALL)
    else:
        # Insert after Features section (before Quick Start)
        marker = "\n---\n\n## Quick Start"
        if marker in content:
            new_content = content.replace(marker, "\n" + new_section + "---\n\n## Quick Start")
        else:
            # Fallback: append before License
            marker2 = "\n---\n\n## License"
            if marker2 in content:
                new_content = content.replace(marker2, "\n" + new_section + "---\n\n## License")
            else:
                new_content = content + "\n" + new_section

    with open(readme_path, "w") as f:
        f.write(new_content)

    print(f"Updated {readme_path}")
    print(f"Total vulns: {total_vulns} (CRITICAL: {crit}, HIGH: {high})")
    if crit > 0 or high > 0:
        print("WARNING: High-severity vulnerabilities detected!")

if __name__ == "__main__":
    main()
