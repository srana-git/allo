#!/usr/bin/env python3
"""Survey the ElevenLabs shared voice library for the voices allo needs.

Three pools:
  * Québec French (language=fr, accent containing "quebec"/"canadian"/"québécois")
  * North American English (language=en, accent containing "canadian"/"american")
  * France French (language=fr, accent parisian/standard) — recorded for the later A/B only

Prints a ranked candidate table per pool and the raw JSON to
evals/results/voices-<timestamp>.json so a choice can be justified from evidence.

Usage:
    uv run python scripts/pick_voices.py
    uv run python scripts/pick_voices.py --use-case conversational --gender female
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.elevenlabs.io"
ROOT = Path(__file__).resolve().parent.parent

QUEBEC_HINTS = ("quebec", "québec", "quebecois", "québécois", "canadian", "montreal", "montréal")
FRANCE_HINTS = ("parisian", "parisien", "standard", "meridional", "swiss")
NORTH_AMERICAN_HINTS = ("canadian", "american", "us", "north american")

# Direct relevance to a car-dealer service line.
USE_CASE_RANK = [
    "conversational",
    "informative_educational",
    "advertisement",
    "social_media",
    "narrative_story",
]


def api_key() -> str:
    """Read the key from `pass`; never from the environment or a file in the repo."""
    out = subprocess.run(
        ["pass", "show", "apis/elevenlabs-agents"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    key = out.splitlines()[0].strip()
    header = out.splitlines()[0]
    if not key:
        sys.exit("empty key from pass")
    # The pass entry's first line is the header name; the value is the next line in
    # some entries. Check both.
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    for candidate in lines:
        if candidate.lower() in ("xi-api-key", "api-key", "x-api-key"):
            continue
        if len(candidate) > 20:
            return candidate
    return header


def get(path: str, key: str, **params) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
    url = f"{API}{path}?{qs}" if qs else f"{API}{path}"
    req = urllib.request.Request(url, headers={"xi-api-key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def search(key: str, **params) -> list[dict]:
    """Page through /v1/shared-voices (100 per page) and return every voice."""
    voices: list[dict] = []
    page = 0
    while True:
        payload = get("/v1/shared-voices", key, page_size=100, page=page, **params)
        batch = payload.get("voices") or []
        voices.extend(batch)
        if not payload.get("has_more") or not batch:
            break
        page += 1
        if page > 12:
            break
    return voices


def accent_matches(voice: dict, hints: tuple[str, ...]) -> bool:
    haystack = " ".join(
        str(voice.get(f) or "") for f in ("accent", "locale", "description", "name")
    ).lower()
    return any(h in haystack for h in hints)


def score(voice: dict) -> tuple:
    use_case = str(voice.get("use_case") or "")
    rank = USE_CASE_RANK.index(use_case) if use_case in USE_CASE_RANK else len(USE_CASE_RANK)
    usage = int(voice.get("usage_character_count_1y") or 0)
    verified = 1 if voice.get("verified_languages") else 0
    return (rank, -verified, -usage)


def show(title: str, voices: list[dict], limit: int = 12) -> list[dict]:
    ranked = sorted(voices, key=score)[:limit]
    print(f"\n=== {title} — {len(voices)} candidates, top {len(ranked)} ===")
    print(f"{'voice_id':<24} {'name':<44} {'accent':<12} {'use_case':<24} gender")
    for v in ranked:
        print(
            f"{v.get('voice_id',''):<24} {str(v.get('name',''))[:43]:<44} "
            f"{str(v.get('accent','')):<12} {str(v.get('use_case','')):<24} {v.get('gender','')}"
        )
    if ranked:
        print(f"  preview: {ranked[0].get('preview_url','')}")
    return ranked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--use-case", default=None, help="filter to one use_case, e.g. conversational")
    ap.add_argument("--gender", default=None, help="filter to one gender, e.g. female")
    args = ap.parse_args()

    key = api_key()
    filters = {"use_cases": [args.use_case] if args.use_case else None, "gender": args.gender}

    print("Reading the ElevenLabs shared voice library…")
    fr_all = search(key, language="fr", **filters)
    en_all = search(key, language="en", **filters)

    quebec = [v for v in fr_all if accent_matches(v, QUEBEC_HINTS)]
    france = [v for v in fr_all if accent_matches(v, FRANCE_HINTS)]
    north_am = [v for v in en_all if accent_matches(v, NORTH_AMERICAN_HINTS)]

    top_qc = show("Québec French (language=fr)", quebec)
    top_fr = show("France French (language=fr, A/B only)", france)
    top_en = show("North American English (language=en)", north_am)

    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"voices-{stamp}.json"
    out.write_text(
        json.dumps(
            {"quebec_fr": quebec, "france_fr": france, "north_american_en": north_am},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    print(
        "\nChosen: see agent/VOICES.md — "
        f"qc_top={top_qc[0]['voice_id'] if top_qc else None} "
        f"en_top={top_en[0]['voice_id'] if top_en else None} "
        f"fr_france={top_fr[0]['voice_id'] if top_fr else None}"
    )


if __name__ == "__main__":
    main()
