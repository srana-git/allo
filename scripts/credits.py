#!/usr/bin/env python3
"""Print the ElevenLabs subscription usage — the "what did this cost" check.

Usage:
    uv run python scripts/credits.py
    uv run python scripts/credits.py --baseline   # also append to evals/credits.log
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from allo_common import ROOT, Api, api_key  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true", help="append this reading to evals/credits.log")
    args = ap.parse_args()

    sub = Api(api_key()).request("GET", "/v1/user/subscription")
    used = sub.get("character_count")
    limit = sub.get("character_limit")
    tier = sub.get("tier")
    pct = (used / limit * 100) if limit else 0

    line = (
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}  "
        f"tier={tier}  used={used}  limit={limit}  pct={pct:.2f}%"
    )
    print(line)
    print(f"remaining: {limit - used} characters" if limit else "")

    if args.baseline:
        log = ROOT / "evals" / "credits.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(f"appended to {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
