#!/usr/bin/env python3
"""Score the blind voice A/B: turn a listener's ranking into a per-voice verdict.

The listener hears, for every line, three clips labelled A, B and C. The three
voices behind those letters are hidden and re-shuffled per line, and the hidden
table lives in exactly one place: evals/voice-ab/key.json. This script joins the
listener's answers to that key and reports, per voice, the rank-1 count, the mean
rank and the detail of every line.

Answer format, one line per ranked line (letters from most to least natural):

    L1: B > A > C

An optional flags line per line records mispronunciations:

    L1 flags: "octobre" sounded like "octobre" with an English o

Usage:
    python3 scripts/voice_ab_score.py <answers file> [key.json]
    python3 scripts/voice_ab_score.py /tmp/answers.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KEY = ROOT / "evals" / "voice-ab" / "key.json"

# The three roles behind the hidden letters. No per-line information here.
ROLES = {
    "Q": "agent voice (Québec)",
    "F": "France French comparison",
    "M": "control (non-French premade)",
}

RANK_RE = re.compile(r"^L(\d+)\s*:\s*([A-C])\s*>\s*([A-C])\s*>\s*([A-C])\s*$")
FLAGS_RE = re.compile(r"^L(\d+)\s+flags?\s*:\s*(.*)$", re.IGNORECASE)
LOOKS_LIKE_ANSWER_RE = re.compile(r"^L(\d+)\s*:", re.IGNORECASE)


def line_id(number: str) -> str:
    return f"L{int(number)}"


def parse_answers(path: Path) -> tuple[dict[str, list[str]], dict[str, str], list[str]]:
    """(ranks, flags, problems). Ranks is line id -> [1st, 2nd, 3rd] letter."""
    ranks: dict[str, list[str]] = {}
    flags: dict[str, str] = {}
    problems: list[str] = []

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue

        m = RANK_RE.match(text)
        if m:
            lid = line_id(m.group(1))
            order = [m.group(2), m.group(3), m.group(4)]
            if len(set(order)) != 3:
                problems.append(f"line {lineno}: {lid} repeats a letter ({text})")
                continue
            if lid in ranks:
                problems.append(f"line {lineno}: {lid} answered twice, second one wins")
            ranks[lid] = order
            continue

        m = FLAGS_RE.match(text)
        if m:
            flags[line_id(m.group(1))] = m.group(2).strip()
            continue

        if LOOKS_LIKE_ANSWER_RE.match(text):
            problems.append(
                f"line {lineno}: cannot read this ranking ({text}) — "
                "expected 'L1: B > A > C'"
            )

    return ranks, flags, problems


def load_key(path: Path) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        sys.exit(f"{path}: expected a JSON object of line -> letter -> voice")
    return data


def role_label(role: str) -> str:
    return f"{role}  {ROLES.get(role, 'unknown role')}"


def score(ranks: dict[str, list[str]], key: dict[str, dict[str, str]]) -> tuple[list[dict], list[str]]:
    """One result row per answered line, in line order, plus warnings."""
    rows: list[dict] = []
    warnings: list[str] = []
    for lid in sorted(key, key=lambda x: int(x[1:])):
        if lid not in ranks:
            warnings.append(f"{lid}: no answer")
            continue
        letters = ranks[lid]
        missing = [x for x in letters if x not in key[lid]]
        if missing:
            warnings.append(f"{lid}: key has no voice for {', '.join(sorted(missing))}")
            continue
        roles = [key[lid][x] for x in letters]
        rows.append({"line": lid, "letters": letters, "roles": roles})
    for lid in sorted(ranks, key=lambda x: int(x[1:])):
        if lid not in key:
            warnings.append(f"{lid}: answered but not in the key")
    return rows, warnings


def report(rows: list[dict], flags: dict[str, str], key: dict[str, dict[str, str]],
           problems: list[str], warnings: list[str]) -> str:
    roles_seen = sorted({r for line in key.values() for r in line.values()})
    out: list[str] = []

    out.append(f"lines scored: {len(rows)} of {len(key)}")
    out.append("")

    if rows:
        out.append("Rank-1 count — how often each voice was judged most natural")
        for role in sorted(roles_seen, key=lambda r: (-sum(1 for x in rows if x["roles"][0] == r), r)):
            wins = sum(1 for x in rows if x["roles"][0] == role)
            out.append(f"  {role_label(role):<38} {wins} / {len(rows)}")
        out.append("")

        out.append("Mean rank — 1.00 is always first, 3.00 is always last")
        means = {
            role: sum(row["roles"].index(role) + 1 for row in rows) / len(rows)
            for role in roles_seen
        }
        for role in sorted(roles_seen, key=lambda r: (means[r], r)):
            out.append(f"  {role_label(role):<38} {means[role]:.2f}")
        out.append("")

        out.append("Per line")
        for row in rows:
            letters = " > ".join(row["letters"])
            roles = " > ".join(row["roles"])
            out.append(f"  {row['line']:<4} {letters}   ->   {roles}")
        out.append("")

    if flags:
        out.append("Flags written by the listener")
        for lid in sorted(flags, key=lambda x: int(x[1:])):
            out.append(f"  {lid:<4} {flags[lid] or '(empty)'}")
        out.append("")

    if problems:
        out.append("Answers this script could not read")
        out.extend(f"  {p}" for p in problems)
        out.append("")

    if warnings:
        out.append("Warnings")
        out.extend(f"  {w}" for w in warnings)

    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Score the blind voice A/B answers.")
    ap.add_argument("answers", help="the listener's filled-in answers file")
    ap.add_argument("key", nargs="?", default=str(DEFAULT_KEY),
                    help=f"blind mapping (default: {DEFAULT_KEY})")
    args = ap.parse_args()

    answers = Path(args.answers)
    key_path = Path(args.key)
    for path in (answers, key_path):
        if not path.exists():
            print(f"not found: {path}")
            return 2

    key = load_key(key_path)
    ranks, flags, problems = parse_answers(answers)
    rows, warnings = score(ranks, key)

    print(report(rows, flags, key, problems, warnings))
    return 0 if rows else 2


if __name__ == "__main__":
    sys.exit(main())
