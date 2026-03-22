#!/usr/bin/env python3
"""Generate a plain-text summary from Trivy JSON results."""

import json
import os
import sys

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <image-name>", file=sys.stderr)
        sys.exit(1)

    img = sys.argv[1]
    json_file = f"trivy-results-{img}.json"
    out_file = f"trivy-summary-{img}.txt"

    with open(out_file, "w") as out:
        out.write(f"=== Trivy Scan Summary: {img} ===\n")
        out.write(f"Scanned at: {os.environ.get('SCAN_DATE', 'unknown')}\n\n")

        if os.path.exists(json_file):
            with open(json_file) as f:
                data = json.load(f)
            results = data.get("Results", [])
            summary = {}
            for r in results:
                for v in r.get("Vulnerabilities", []) or []:
                    sev = v.get("Severity", "UNKNOWN")
                    summary[sev] = summary.get(sev, 0) + 1

            out.write("Vulnerability Summary:\n")
            for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]:
                count = summary.get(sev, 0)
                if count > 0:
                    out.write(f"  {sev}: {count}\n")
        else:
            out.write("Summary unavailable\n")

    print(f"Written to {out_file}")

if __name__ == "__main__":
    main()
