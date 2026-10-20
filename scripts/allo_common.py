"""Shared helpers for the allo scripts: keys from pass, JSON, the API client."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.elevenlabs.io"


def pass_show(entry: str) -> str:
    """First non-empty, non-header line of a pass entry. Never logged."""
    try:
        out = subprocess.run(
            ["pass", "show", entry], capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError as e:
        sys.exit(f"pass entry '{entry}' not available: {e.stderr.strip()}")
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower() in ("xi-api-key", "api-key", "x-api-key"):
            continue
        return line
    sys.exit(f"pass entry '{entry}' is empty")


def pass_insert(entry: str, value: str) -> None:
    subprocess.run(
        ["pass", "insert", "-m", "-f", entry],
        input=value + "\n",
        text=True,
        check=True,
    )


def pass_exists(entry: str) -> bool:
    return (
        subprocess.run(["pass", "show", entry], capture_output=True).returncode == 0
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def api_key() -> str:
    return pass_show("apis/elevenlabs-agents")


class Api:
    """Thin ElevenLabs client that raises a readable error instead of a traceback."""

    def __init__(self, key: str, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.client = httpx.Client(
            base_url=API,
            headers={"xi-api-key": key},
            timeout=httpx.Timeout(120.0, connect=20.0),
        )

    def request(
        self, method: str, path: str, *, expect: tuple[int, ...] = (200,), **kw
    ) -> Any:
        if self.dry_run:
            print(f"  [dry-run] {method} {path}")
            return None
        r = self.client.request(method, path, **kw)
        if r.status_code not in expect:
            raise RuntimeError(
                f"{method} {path} -> HTTP {r.status_code}: {r.text[:600]}"
            )
        if not r.content:
            return None
        try:
            return r.json()
        except json.JSONDecodeError:
            return r.text
