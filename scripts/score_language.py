#!/usr/bin/env python3
"""Deterministic language-fidelity scoring of a test results file. No LLM.

Reads one evals/results/*.json (either the repeat shape with top-level "runs"
or the older flat shape with top-level "rows") and scores every agent turn
against the language the caller was speaking at that moment.

Rules (from the runner spec):
  - The caller's current language is the detected language of the most recent
    user turn with 3 or more words. For a mixed sentence the higher-confidence
    language wins.
  - The caller's language only CHANGES on a turn that actually carries signal:
    lingua's confidence for the newly detected language must be >= 0.75, AND the
    turn must hold 3 or more words that are neither capitalized proper nouns nor
    numbers. A turn made of a brand and a model — "C'est une Honda. Honda Civic
    2018." — is short and almost all proper nouns, and used to flip a French
    caller to English on 0.578 confidence.
  - Before any user turn the expected language is French: the agent greets in
    French by design.
  - An agent turn is scored when it has 3 or more words. Tool-call-only turns
    and short turns ("Okay.", "Yes.") are skipped.
  - A scored turn passes when its detected language equals the caller's current
    language.

Usage:
    uv run python scripts/score_language.py evals/results/<file>.json
    uv run python scripts/score_language.py evals/results/<file>.json -o /tmp/lang.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

LANGUAGES = ("fr", "en")
GROUPS = ("F", "E", "S", "A")
MIN_WORDS = 3
MIN_CONFIDENCE = 0.75
EXCERPT = 140

_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)


@lru_cache(maxsize=1)
def detector():
    from lingua import Language, LanguageDetectorBuilder

    return LanguageDetectorBuilder.from_languages(
        Language.FRENCH, Language.ENGLISH
    ).build()


@lru_cache(maxsize=1)
def _language_names():
    from lingua import Language

    return {Language.FRENCH: "fr", Language.ENGLISH: "en"}


def words(text: str) -> list[str]:
    """Alphabetic words only: digits and punctuation do not count."""
    return _WORDS.findall(text or "")


def count_words(text: str) -> int:
    return len(words(text))


def detect_language_confidence(text: str) -> tuple[str | None, float]:
    """('fr' | 'en', confidence) for the higher-confidence language."""
    text = (text or "").strip()
    if not text:
        return None, 0.0
    values = detector().compute_language_confidence_values(text)
    if not values:
        return None, 0.0
    return _language_names().get(values[0].language), float(values[0].value)


def detect_language(text: str) -> str | None:
    """'fr' or 'en' — the higher-confidence language for this text."""
    return detect_language_confidence(text)[0]


def is_scorable(text: str) -> bool:
    return count_words(text) >= MIN_WORDS


def content_words(text: str) -> list[str]:
    """Words that carry language signal: no numbers, no capitalized proper nouns.

    "C'est une Honda. Honda Civic 2018." keeps only "est" and "une". Numbers are
    already gone — `words()` matches letters only.
    """
    out = []
    for sentence in re.split(r"[.!?]+", text or ""):
        ws = words(sentence)
        # Keep the sentence-initial word ("Do you take Amex?" keeps "Do"); drop other
        # capitalized words, which are names, brands and models.
        out += [w for i, w in enumerate(ws) if i == 0 or not w[:1].isupper()]
    return out


def is_language_change(text: str, confidence: float) -> bool:
    """True when a caller turn is strong enough evidence to move the language."""
    return confidence >= MIN_CONFIDENCE and len(content_words(text)) >= MIN_WORDS


# ------------------------------------------------------------- shape handling


def iter_runs(data: dict):
    """Yield (run_index, rows) for both the repeat shape and the flat shape."""
    runs = data.get("runs")
    if isinstance(runs, list) and runs:
        for run in runs:
            yield run.get("run_index") or 1, run.get("rows") or []
        return
    yield data.get("run_index") or 1, data.get("rows") or []


def scenario_id_of_row(row: dict) -> str:
    sid = row.get("scenario_id")
    if sid:
        return sid
    name = (row.get("test_name") or "").strip()
    token = name.split()[0] if name else ""
    if len(token) >= 2 and token[0] in GROUPS and token[1].isdigit():
        return token
    return row.get("test_id") or name or "unknown"


def type_of_row(row: dict) -> str:
    kind = row.get("type")
    if kind:
        return kind
    # older flat files carry no type: the tool tests are named "… Tool call …"
    return "tool" if "tool call" in (row.get("test_name") or "").lower() else "simulation"


def group_of(scenario_id: str, kind: str) -> str:
    if kind == "tool":
        return "tool"
    first = (scenario_id or "")[:1]
    return first if first in GROUPS else "other"


def excerpt(text: str) -> str:
    flat = " ".join((text or "").split())
    return flat[:EXCERPT] + ("…" if len(flat) > EXCERPT else "")


# ------------------------------------------------------------------ scoring


def score_transcript(turns: list[dict], scenario_id: str, scenario_name: str,
                     run_index: int) -> dict:
    """Score one conversation. Returns counts, switch point and failures."""
    caller_lang = "fr"  # before any user turn, expected = French
    prev_caller_lang = None
    first_switch_turn = None
    scored = passed = 0
    after_scored = after_passed = 0
    failures: list[dict] = []
    last_caller_text = ""

    for index, turn in enumerate(turns):
        text = (turn.get("message") or "").strip()
        role = turn.get("role")

        if role == "user":
            if is_scorable(text):
                # Detect on content words so brand and model names do not decide the language.
                detected, confidence = detect_language_confidence(" ".join(content_words(text)) or text)
                lang = detected or caller_lang
                # A weak or thin turn is not evidence of a language change: keep
                # the language the caller was already speaking.
                if lang != caller_lang and not is_language_change(text, confidence):
                    lang = caller_lang
                if (prev_caller_lang is not None and lang != prev_caller_lang
                        and first_switch_turn is None):
                    first_switch_turn = index
                prev_caller_lang = lang
                caller_lang = lang
                last_caller_text = text
            continue

        if role != "agent" or not is_scorable(text):
            continue  # tool-call-only and short turns are skipped

        expected = caller_lang
        got = detect_language(text)
        ok = got == expected
        scored += 1
        if ok:
            passed += 1
        else:
            failures.append({
                "scenario_id": scenario_id,
                "scenario": scenario_name,
                "run_index": run_index,
                "turn_index": index,
                "caller_text": excerpt(last_caller_text),
                "agent_text": excerpt(text),
                "expected": expected,
                "got": got,
            })
        if first_switch_turn is not None and index > first_switch_turn:
            after_scored += 1
            after_passed += int(ok)

    return {
        "scenario_id": scenario_id,
        "scenario": scenario_name,
        "run_index": run_index,
        "scored": scored,
        "passed": passed,
        "first_switch_turn": first_switch_turn,
        "after_switch_scored": after_scored,
        "after_switch_passed": after_passed,
        "failures": failures,
    }


def fidelity(passed: int, scored: int) -> float | None:
    return round(passed / scored, 4) if scored else None


def score_results(data: dict, path: str = "") -> dict:
    per_scenario: dict[str, dict] = {}
    per_group: dict[str, dict] = {}
    switch_after: dict[str, dict] = {}
    failures: list[dict] = []
    skipped: list[dict] = []
    total_scored = total_passed = 0

    for run_index, rows in iter_runs(data):
        for row in rows:
            sid = scenario_id_of_row(row)
            kind = type_of_row(row)
            name = row.get("test_name") or ""
            turns = row.get("transcript") or []
            if not turns:
                skipped.append({"scenario_id": sid, "run_index": run_index,
                                "reason": "no transcript"})
                continue

            res = score_transcript(turns, sid, name, run_index)
            failures.extend(res["failures"])
            total_scored += res["scored"]
            total_passed += res["passed"]

            acc = per_scenario.setdefault(
                sid, {"scenario": name, "group": group_of(sid, kind),
                      "scored": 0, "passed": 0})
            acc["scored"] += res["scored"]
            acc["passed"] += res["passed"]

            acc = per_group.setdefault(group_of(sid, kind), {"scored": 0, "passed": 0})
            acc["scored"] += res["scored"]
            acc["passed"] += res["passed"]

            if sid.startswith("S"):
                acc = switch_after.setdefault(
                    sid, {"scenario": name, "first_switch_turn": None,
                          "scored": 0, "passed": 0})
                acc["scored"] += res["after_switch_scored"]
                acc["passed"] += res["after_switch_passed"]
                if acc["first_switch_turn"] is None:
                    acc["first_switch_turn"] = res["first_switch_turn"]

    for acc in list(per_scenario.values()) + list(per_group.values()) \
            + list(switch_after.values()):
        acc["fidelity"] = fidelity(acc["passed"], acc["scored"])

    switch_scored = sum(a["scored"] for a in switch_after.values())
    switch_passed = sum(a["passed"] for a in switch_after.values())

    return {
        "file": path,
        "label": data.get("label"),
        "repeat": data.get("repeat") or len(data.get("runs") or []) or 1,
        "rules": {
            "min_words": MIN_WORDS,
            "min_confidence_for_a_language_change": MIN_CONFIDENCE,
            "language_change_needs_content_words": MIN_WORDS,
            "default_language_before_first_user_turn": "fr",
            "detector": "lingua-language-detector, French vs English only",
        },
        "overall": {"scored": total_scored, "passed": total_passed,
                    "fidelity": fidelity(total_passed, total_scored)},
        "per_scenario": per_scenario,
        "per_group": per_group,
        "switch_after": switch_after,
        "switch_after_overall": {
            "scenarios": sorted(switch_after),
            "scored": switch_scored, "passed": switch_passed,
            "fidelity": fidelity(switch_passed, switch_scored),
        },
        "failures": failures,
        "skipped": skipped,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", help="evals/results/<file>.json")
    ap.add_argument("-o", "--out", default="",
                    help="write the JSON here (default: <results>-language.json)")
    args = ap.parse_args()

    path = Path(args.results)
    if not path.exists():
        print(f"not found: {path}")
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))
    payload = score_results(data, str(path))

    out = Path(args.out) if args.out else path.with_name(f"{path.stem}-language.json")
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nwritten to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
