#!/usr/bin/env python3
"""Turn a test results file into a pass^k report.

Writes two files:
  - evals/results/<label>-summary.json   (machine readable)
  - docs/RESULTS.md                      (human readable)

Reads either the repeat shape (top-level "runs") or the older flat shape
(top-level "rows"). Optionally takes the language JSON from score_language.py.

Usage:
    uv run python scripts/report.py evals/results/<file>.json
    uv run python scripts/report.py evals/results/<file>.json evals/results/<file>-language.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "evals" / "results"
DOCS = ROOT / "docs"
GROUPS = ("F", "E", "S", "A")
REASON_WIDTH = 160


# ------------------------------------------------------------- shape handling


def iter_runs(data: dict):
    """Yield (run_index, rows) for both the repeat shape and the flat shape."""
    runs = data.get("runs")
    if isinstance(runs, list) and runs:
        for n, run in enumerate(runs, 1):
            yield run.get("run_index") or n, run.get("rows") or []
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
    return "tool" if "tool call" in (row.get("test_name") or "").lower() else "simulation"


def group_of(scenario_id: str, kind: str) -> str:
    if kind == "tool":
        return "tool"
    first = (scenario_id or "")[:1]
    return first if first in GROUPS else "other"


def one_line(row: dict) -> str:
    """One line for a failed row: the failing criterion, else the summary."""
    messages = row.get("reasons") or row.get("messages") or []
    flagged = [m for m in messages
               if "failed" in m.lower() or "inconclusive" in m.lower()]
    text = "; ".join(flagged) if flagged else (
        row.get("reason") or "; ".join(messages) or "")
    text = " ".join(text.split())
    return text[:REASON_WIDTH] + ("…" if len(text) > REASON_WIDTH else "")


# ------------------------------------------------------------------ analysis


def analyse(data: dict, language: dict | None) -> dict:
    per_run = []
    scenarios: dict[str, dict] = {}

    for run_index, rows in iter_runs(data):
        stats = {"run_index": run_index,
                 "simulation": {"passed": 0, "total": 0},
                 "tool": {"passed": 0, "total": 0}}
        for row in rows:
            kind = type_of_row(row)
            bucket = "tool" if kind == "tool" else "simulation"
            stats[bucket]["total"] += 1
            if row.get("status") == "passed":
                stats[bucket]["passed"] += 1
            sid = scenario_id_of_row(row)
            entry = scenarios.setdefault(sid, {
                "scenario_id": sid,
                "scenario": row.get("test_name") or "",
                "type": kind,
                "group": group_of(sid, kind),
                "results": {},
                "reasons": {},
            })
            entry["results"][run_index] = row.get("status")
            if row.get("status") != "passed":
                entry["reasons"][run_index] = one_line(row)
        per_run.append(stats)

    k = max((r["run_index"] for r in per_run), default=1)
    run_indexes = [r["run_index"] for r in per_run]

    for entry in scenarios.values():
        marks = [entry["results"].get(i) for i in run_indexes]
        entry["marks"] = ["?" if m is None else ("✓" if m == "passed" else "✗")
                          for m in marks]
        entry["pass_k"] = bool(marks) and all(m == "passed" for m in marks)

    def group_block(selector) -> dict:
        picked = [e for e in scenarios.values() if selector(e)]
        runs_passed = sum(1 for e in picked for i in run_indexes
                          if e["results"].get(i) == "passed")
        runs_total = sum(1 for e in picked for i in run_indexes if i in e["results"])
        return {
            "scenarios": len(picked),
            "pass_k": sum(1 for e in picked if e["pass_k"]),
            "runs_passed": runs_passed,
            "runs_total": runs_total,
            "run_pass_rate": round(runs_passed / runs_total, 4) if runs_total else None,
            "pass_k_rate": (round(sum(1 for e in picked if e["pass_k"]) / len(picked), 4)
                            if picked else None),
        }

    groups = {g: group_block(lambda e, g=g: e["group"] == g)
              for g in GROUPS + ("tool",)}
    groups = {g: v for g, v in groups.items() if v["scenarios"]}

    all_rows = [r for _, rows in iter_runs(data) for r in rows]
    verdict = {
        "repeat_k": k,
        "runs": len(per_run),
        "rows": len(all_rows),
        "scenarios": len(scenarios),
        "passed_rows": sum(1 for r in all_rows if r.get("status") == "passed"),
        "failed_rows": sum(1 for r in all_rows if r.get("status") == "failed"),
        "scenarios_pass_k": sum(1 for e in scenarios.values() if e["pass_k"]),
    }
    return {
        "verdict": verdict,
        "per_run": per_run,
        "per_group": groups,
        "scenarios": scenarios,
        "failures": [{"scenario_id": e["scenario_id"], "scenario": e["scenario"],
                      "run_index": i, "reason": reason}
                     for e in scenarios.values()
                     for i, reason in sorted(e["reasons"].items())],
        "language": language,
        "credits": data.get("credits"),
    }


# ------------------------------------------------------------------- render


def render(report: dict, data: dict, path: Path, language_path: Path | None) -> str:
    v = report["verdict"]
    k = v["repeat_k"]
    out: list[str] = []
    lines = out

    lines.append("# allo — suite results")
    lines.append("")
    lines.append(
        f"Verdict: {v['passed_rows']}/{v['rows']} test runs passed. "
        f"pass^{k} {v['scenarios_pass_k']}/{v['scenarios']} scenarios."
    )
    lines.append("")
    lines.append(f"- Results file: `{path}`")
    lines.append(f"- Label: {data.get('label') or path.stem}")
    lines.append(f"- Agent: `{data.get('agent_id')}`")
    lines.append(f"- Suite: {data.get('suite')} · only: {data.get('only') or 'all'}"
                 f" · repeat: {k}")
    lines.append(f"- Timestamp: {data.get('timestamp')}")
    if data.get("only"):
        lines.append("- Note: this file holds a filtered run, not the full suite.")
    if language_path:
        lines.append(f"- Language file: `{language_path}`")
    lines.append("")

    lines.append("## Pass rate per run")
    lines.append("")
    lines.append("| Run | Simulation | Tool |")
    lines.append("| --- | --- | --- |")
    for r in report["per_run"]:
        s, t = r["simulation"], r["tool"]
        lines.append(f"| {r['run_index']} | {s['passed']}/{s['total']} | "
                     f"{t['passed']}/{t['total']} |")
    lines.append("")

    lines.append(f"## pass^{k} per scenario")
    lines.append("")
    lines.append(f"| Scenario | Id | Type | Runs (k={k}) | pass^{k} | Failure reason |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for entry in sorted(report["scenarios"].values(), key=lambda e: e["scenario_id"]):
        reason = " | ".join(f"run {i}: {t}" for i, t in sorted(entry["reasons"].items()))
        lines.append(
            f"| {entry['scenario']} | {entry['scenario_id']} | {entry['type']} | "
            f"{''.join(entry['marks'])} | {'yes' if entry['pass_k'] else 'no'} | {reason} |"
        )
    lines.append("")

    lines.append(f"## pass^{k} per group")
    lines.append("")
    lines.append(f"| Group | Scenarios | pass^{k} | Run pass rate |")
    lines.append("| --- | --- | --- | --- |")
    for name, block in report["per_group"].items():
        rate = block["run_pass_rate"]
        rate_text = "n/a" if rate is None else (
            f"{block['runs_passed']}/{block['runs_total']} ({rate:.0%})")
        lines.append(f"| {name} | {block['scenarios']} | "
                     f"{block['pass_k']}/{block['scenarios']} | {rate_text} |")
    lines.append("")

    lang = report["language"]
    lines.append("## Language fidelity")
    lines.append("")
    if not lang:
        lines.append("Not scored. Pass the score_language.py output to include this block.")
    else:
        overall = lang.get("overall") or {}
        if not overall.get("scored"):
            lines.append("No turn could be scored. This file carries no transcripts "
                         "(older results files do not), or it holds tool tests only.")
        else:
            lines.append(
                f"Deterministic check with lingua (French vs English). "
                f"{overall.get('passed')}/{overall.get('scored')} agent turns "
                f"in the caller's current language ({pct(overall.get('fidelity'))})."
            )
            lines.append("")
            lines.append("| Group | Turns scored | Fidelity |")
            lines.append("| --- | --- | --- |")
            for name, block in sorted((lang.get("per_group") or {}).items()):
                lines.append(f"| {name} | {block['scored']} | "
                             f"{block['passed']}/{block['scored']} "
                             f"({pct(block.get('fidelity'))}) |")
            lines.append("")
            after = lang.get("switch_after_overall") or {}
            if after.get("scored"):
                lines.append(f"Agent turns after the first language switch, S scenarios: "
                             f"{after['passed']}/{after['scored']} "
                             f"({pct(after.get('fidelity'))}).")
                lines.append("")
            elif after.get("scenarios"):
                lines.append("No language switch was detected in the S scenarios, so "
                             "there are no turns after a first switch to score. Check "
                             "the transcripts: the caller may never have switched.")
                lines.append("")
            failures = lang.get("failures") or []
            if not failures:
                lines.append("No turn was flagged.")
            else:
                lines.append(f"{len(failures)} turn(s) flagged for a human check:")
                lines.append("")
                lines.append("| Scenario | Run | Turn | Expected | Got | Caller said | Agent said |")
                lines.append("| --- | --- | --- | --- | --- | --- | --- |")
                for f in failures:
                    lines.append(
                        f"| {f['scenario_id']} | {f['run_index']} | {f['turn_index']} | "
                        f"{f['expected']} | {f['got']} | {f['caller_text']} | "
                        f"{f['agent_text']} |"
                    )
    lines.append("")

    lines.append("## Credits")
    lines.append("")
    credits = report.get("credits") or {}
    if not credits or credits.get("character_count_before") is None:
        lines.append("Not recorded for this run.")
    else:
        lines.append(f"- Subscription characters: "
                     f"{credits.get('character_count_before'):,} -> "
                     f"{credits.get('character_count_after'):,} "
                     f"(delta {credits.get('delta')})")
        lines.append(f"- Test credits used, summed from the API: "
                     f"{credits.get('test_credits_used')}")
    lines.append("")
    return "\n".join(lines)


def pct(value) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", help="evals/results/<file>.json")
    ap.add_argument("language", nargs="?", default="",
                    help="optional score_language.py JSON")
    ap.add_argument("--docs", default=str(DOCS / "RESULTS.md"),
                    help="markdown output path")
    args = ap.parse_args()

    path = Path(args.results)
    if not path.exists():
        print(f"not found: {path}")
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))

    language = None
    language_path = None
    if args.language:
        language_path = Path(args.language)
        if not language_path.exists():
            print(f"not found: {language_path}")
            return 2
        language = json.loads(language_path.read_text(encoding="utf-8"))

    report = analyse(data, language)
    label = data.get("label") or path.stem

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = RESULTS_DIR / f"{label}-summary.json"
    summary_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")

    docs_path = Path(args.docs)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(render(report, data, path, language_path), encoding="utf-8")

    v = report["verdict"]
    print(f"{label}: {v['passed_rows']}/{v['rows']} test runs passed; "
          f"pass^{v['repeat_k']} {v['scenarios_pass_k']}/{v['scenarios']} scenarios")
    print(f"summary written to {summary_path}")
    print(f"markdown written to {docs_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
