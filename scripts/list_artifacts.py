"""List artifacts of a CI run as id<TAB>name<TAB>size.

Usage: python scripts/list_artifacts.py <run_id>
"""
from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/list_artifacts.py <run_id>", file=sys.stderr)
        return 2

    run_id = sys.argv[1]
    completed = subprocess.run(
        ["gh", "api", f"repos/peter0429-ux/pdf-review/actions/runs/{run_id}/artifacts"],
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout.decode("utf-8"))
    for item in payload.get("artifacts", []):
        print(f"{item['id']}\t{item['name']}\t{item['size_in_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
