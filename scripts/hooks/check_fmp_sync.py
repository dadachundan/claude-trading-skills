#!/usr/bin/env python3
"""
Pre-push hook: verify all skill fmp_client.py files are in sync with shared/fmp_base.py.
Fails with a clear message if any file is out of date.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "shared" / "fmp_base.py"
HEADER_LINES = 3  # AUTO-SYNCED header + blank line

SKILL_CLIENTS = [
    "skills/canslim-screener/scripts/fmp_client.py",
    "skills/earnings-trade-analyzer/scripts/fmp_client.py",
    "skills/ftd-detector/scripts/fmp_client.py",
    "skills/ibd-distribution-day-monitor/scripts/fmp_client.py",
    "skills/macro-regime-detector/scripts/fmp_client.py",
    "skills/market-top-detector/scripts/fmp_client.py",
    "skills/parabolic-short-trade-planner/scripts/fmp_client.py",
    "skills/pead-screener/scripts/fmp_client.py",
    "skills/vcp-screener/scripts/fmp_client.py",
]


def main() -> int:
    if not SOURCE.exists():
        return 0  # shared/ not present — skip check

    source_body = SOURCE.read_text()
    stale = []

    for rel in SKILL_CLIENTS:
        dest = REPO_ROOT / rel
        if not dest.exists():
            continue
        content = dest.read_text()
        # Strip the AUTO-SYNCED header before comparing
        lines = content.splitlines(keepends=True)
        body = "".join(lines[HEADER_LINES:])
        if body != source_body:
            stale.append(rel)

    if stale:
        print("ERROR: The following fmp_client.py files are out of sync with shared/fmp_base.py:")
        for f in stale:
            print(f"  {f}")
        print("\nRun:  python3 scripts/sync_fmp_client.py")
        print("Then re-stage the updated files and push again.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
