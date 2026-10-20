#!/usr/bin/env python3
"""Run an allo agent test suite against the live ElevenLabs agent.

Test definitions live in a suite directory as JSON files, as code. This script:
  1. loads them and fills {{TOOL_ID:...}} placeholders from agent/state.json
  2. creates them in ElevenLabs, or updates them if the name already exists
     (so editing a test file and re-running is enough — ids go in <suite>/state.json)
  3. optionally reseeds the Worker fixture (POST /admin/reset_fixture)
  4. runs the suite N times (--repeat, default 1), sequentially, waiting for every
     run to reach a terminal state each time
  5. prints a table and writes ONE evals/results/<stamp><label>.json holding all runs

Each result row keeps the scenario id (e.g. "F01"), name, type, status, the
evaluator reasons per success condition, and the full simulated transcript.

Usage:
    uv run python scripts/run_tests.py                          # tests/ (phase-1 set)
    uv run python scripts/run_tests.py --suite tests/suite-v1   # the 40-scenario suite
    uv run python scripts/run_tests.py --suite tests/suite-v1 --only 'F05*'
    uv run python scripts/run_tests.py --suite tests/suite-v1 --only 'F05*' --fixture
    uv run python scripts/run_tests.py --suite tests/suite-v1 --only 'S01*' --fixture --repeat 2
    uv run python scripts/run_tests.py --suite tests/suite-v1 --push-only
    uv run python scripts/run_tests.py --no-push --label iter2  # run what is already there
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from allo_common import ROOT, Api, api_key, load_json, pass_show, save_json  # noqa: E402

DEFAULT_SUITE = ROOT / "tests"
AGENT_STATE = ROOT / "agent" / "state.json"
DEPLOY = ROOT / "agent" / "deploy.json"
RESULTS_DIR = ROOT / "evals" / "results"

TERMINAL = {"passed", "failed", "cancelled"}

# Keys a test run may carry that point at a stored conversation. Our payloads
# have no conversation id (the transcript always ships inside agent_responses),
# so this path stays unexercised; it is here for payloads that drop it.
CONVERSATION_ID_KEYS = ("conversation_id", "conversation_ids", "conv_id")


# --------------------------------------------------------------------------- #


def substitute(node, values):
    if isinstance(node, str):
        out = node
        for k, v in values.items():
            out = out.replace("{{" + k + "}}", v)
        return out
    if isinstance(node, dict):
        return {k: substitute(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute(v, values) for v in node]
    return node


def build_payload(defn: dict, tool_ids: dict[str, str]) -> dict:
    """Turn a repo test definition into the ElevenLabs create-test payload."""
    values = {f"TOOL_ID:{name}": tid for name, tid in tool_ids.items()}
    d = substitute(defn, values)
    payload = {"name": d["name"], "type": d["type"]}

    if d["type"] == "simulation":
        payload["simulation_scenario"] = d["simulation_scenario"]
        payload["success_conditions"] = d["success_conditions"]
        payload["simulation_max_turns"] = d.get("simulation_max_turns", 12)
        payload["simulation_environment"] = d.get("simulation_environment", "production")
        # All mockable tools stay unmocked: the suite must exercise the real
        # Cloudflare Worker, including real bookings.
        payload["tool_mock_config"] = {"mocking_strategy": "none"}
    elif d["type"] == "tool":
        payload["chat_history"] = d["chat_history"]
        payload["tool_call_parameters"] = d["tool_call_parameters"]
        payload["check_any_tool_matches"] = d.get("check_any_tool_matches", True)
    return payload


def ensure_test(api: Api, payload: dict, state: dict) -> str:
    name = payload["name"]
    existing_id = state.get(name)
    if existing_id:
        api.request("PUT", f"/v1/convai/agent-testing/{existing_id}", json=payload,
                    expect=(200, 204))
        return existing_id

    listing = api.request("GET", "/v1/convai/agent-testing", params={"page_size": 100}) or {}
    for t in listing.get("tests") or []:
        if t.get("name") == name:
            api.request("PUT", f"/v1/convai/agent-testing/{t['id']}", json=payload,
                        expect=(200, 204))
            return t["id"]

    resp = api.request("POST", "/v1/convai/agent-testing/create", json=payload,
                       expect=(200, 201))
    return resp["id"]


def reseed_calendar() -> None:
    """Reset D1 slots + appointments to worker/seed.sql so every run starts from the same calendar.

    Test runs make real bookings; without this the calendar fills up across runs."""
    import subprocess
    cmd = ('eval "$(cf-env srana)" && CLOUDFLARE_ACCOUNT_ID=$CLOUDFLARE_ACCOUNT_SRANA '
           'npx wrangler d1 execute allo --remote --file seed.sql -y')
    r = subprocess.run(["bash", "-c", cmd], cwd=ROOT / "worker", capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"calendar reseed failed: {r.stderr[-400:]}")


def reset_fixture() -> dict:
    """Reseed the calendar, then the Worker's GAL-TEST1 booking, so move scenarios are repeatable."""
    reseed_calendar()
    deploy = load_json(DEPLOY)
    url = deploy["worker_url"].rstrip("/") + "/admin/reset_fixture"
    secret = pass_show(deploy["secrets"]["tools_pass_entry"])
    r = httpx.post(url, json={}, headers={"X-Allo-Secret": secret}, timeout=30.0)
    if r.status_code != 200:
        raise RuntimeError(f"POST /admin/reset_fixture -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def run_suite(api: Api, agent_id: str, test_ids: list[str]) -> str:
    resp = api.request(
        "POST",
        f"/v1/convai/agents/{agent_id}/run-tests",
        json={"tests": [{"test_id": t} for t in test_ids], "repeat_count": 1},
        expect=(200, 201),
    )
    return resp["id"]


def poll(api: Api, invocation_id: str, timeout_s: int = 900) -> dict:
    deadline = time.time() + timeout_s
    while True:
        inv = api.request("GET", f"/v1/convai/test-invocations/{invocation_id}")
        runs = inv.get("test_runs") or []
        done = [r for r in runs if r.get("status") in TERMINAL]
        print(f"    … {len(done)}/{len(runs)} runs finished", flush=True)
        if runs and len(done) == len(runs):
            return inv
        if time.time() > deadline:
            print("    … timed out waiting; reporting what we have")
            return inv
        time.sleep(10)


# --------------------------------------------------------------- row building


def scenario_id_of(file_name: str) -> str:
    """'F01_oil_change_simple.json' -> 'F01'; 'E02T_tool_check.json' -> 'E02T'."""
    return Path(file_name).stem.split("_")[0]


def transcript_of(run: dict) -> list[dict]:
    """The simulated transcript as a list of {role, message}.

    Tool-call-only turns carry a null message; they are not transcript turns.
    """
    out = []
    for turn in run.get("agent_responses") or []:
        role = turn.get("role")
        message = (turn.get("message") or "").strip()
        if role in ("agent", "user") and message:
            out.append({"role": role, "message": message})
    return out


def conversation_id_of(run: dict) -> str | None:
    for src in (run, run.get("metadata") or {}, run.get("test_info") or {}):
        for key in CONVERSATION_ID_KEYS:
            value = src.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, list) and value:
                return value[0]
    return None


def fetch_transcript(api: Api, conversation_id: str) -> list[dict]:
    """Fallback: read a stored conversation's transcript by id."""
    conv = api.request("GET", f"/v1/convai/conversations/{conversation_id}")
    out = []
    for turn in (conv or {}).get("transcript") or []:
        role = turn.get("role")
        message = (turn.get("message") or "").strip()
        if role in ("agent", "user") and message:
            out.append({"role": role, "message": message})
    return out


def row_of(run: dict, files_by_name: dict[str, str],
           run_index: int, api: Api) -> dict:
    cond = run.get("condition_result") or {}
    rationale = cond.get("rationale") or {}
    messages = rationale.get("messages") or []
    test_name = run.get("test_name")
    file_name = files_by_name.get(test_name, "")
    transcript = transcript_of(run)
    if not transcript:
        conv_id = conversation_id_of(run)
        if conv_id:
            transcript = fetch_transcript(api, conv_id)
    return {
        # legacy keys, unchanged in meaning
        "test_id": run.get("test_id"),
        "test_name": test_name,
        "status": run.get("status"),
        "result": cond.get("result"),
        "reason": (rationale.get("summary") or "").strip(),
        "messages": messages,
        "test_run_id": run.get("test_run_id"),
        "turns": len(run.get("agent_responses") or []),
        # added for repeat runs / scoring
        "scenario_id": scenario_id_of(file_name) if file_name else None,
        "type": (run.get("test_info") or {}).get("type")
        or (run.get("metadata") or {}).get("test_type"),
        "reasons": messages,
        "transcript": transcript,
        "run_index": run_index,
    }


def summarise(inv: dict, order: dict[str, int], files_by_name: dict[str, str],
              run_index: int, api: Api) -> list[dict]:
    rows = [row_of(r, files_by_name, run_index, api)
            for r in inv.get("test_runs") or []]
    rows.sort(key=lambda r: order.get(r["test_name"], 999))
    return rows


def credits_now(api: Api) -> dict:
    """Subscription character count — the 'what did this cost' reading."""
    sub = api.request("GET", "/v1/user/subscription") or {}
    return {
        "character_count": sub.get("character_count"),
        "character_limit": sub.get("character_limit"),
        "tier": sub.get("tier"),
    }


def run_once(api: Api, agent_id: str, ids: list[str], order: dict[str, int],
             files_by_name: dict[str, str], run_index: int, args) -> dict:
    started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.fixture:
        fx = reset_fixture()
        print(f"  fixture reseeded: {fx.get('booking_ref')} on {fx.get('slot_id')} "
              f"({fx.get('start_local_en') or fx.get('start_local_fr')})")
    print(f"\nRunning {len(ids)} tests against agent {agent_id} "
          f"(run {run_index}/{args.repeat}) …")
    inv_id = run_suite(api, agent_id, ids)
    print(f"  invocation {inv_id}")
    inv = poll(api, inv_id, args.timeout)
    rows = summarise(inv, order, files_by_name, run_index, api)
    return {
        "run_index": run_index,
        "started_at": started,
        "test_invocation_id": inv_id,
        "pass": sum(1 for r in rows if r["status"] == "passed"),
        "fail": sum(1 for r in rows if r["status"] == "failed"),
        "total": len(rows),
        "credits_used": sum((r.get("credits_used") or 0)
                            for r in (inv.get("test_runs") or [])),
        "rows": rows,
        "raw_invocation": inv,
    }


def print_table(runs: list[dict]) -> None:
    for run in runs:
        print("\n" + "=" * 78)
        print(f"RUN {run['run_index']}/{len(runs)}  ({run['test_invocation_id']})")
        print(f"{'#':<3} {'STATUS':<9} TEST")
        print("-" * 78)
        for n, r in enumerate(run["rows"], 1):
            print(f"{n:<3} {str(r['status']).upper():<9} {r['test_name']}")
            if r["status"] != "passed":
                reason = r["reason"] or "; ".join(r["messages"])[:300]
                print(f"    reason: {reason[:300]}")
        print("-" * 78)
        print(f"PASS {run['pass']}/{run['total']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default=str(DEFAULT_SUITE),
                    help="suite directory of test definitions (default: tests/)")
    ap.add_argument("--only", default="", help="only files matching these comma-separated globs, e.g. 'F05*,E0*'")
    ap.add_argument("--fixture", action="store_true",
                    help="POST /admin/reset_fixture on the Worker before each run")
    ap.add_argument("--repeat", type=int, default=1,
                    help="run the selected tests N times as N invocations (default 1)")
    ap.add_argument("--push-only", action="store_true",
                    help="create/update the tests and save their ids, then exit")
    ap.add_argument("--no-push", action="store_true", help="skip create/update of tests")
    ap.add_argument("--label", default="", help="suffix for the results filename")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    if args.repeat < 1:
        print("--repeat must be >= 1")
        return 2

    suite = Path(args.suite)
    if not suite.is_absolute():
        suite = ROOT / suite
    if not suite.is_dir():
        print(f"suite directory not found: {suite}")
        return 2
    state_path = suite / "state.json"

    agent_state = load_json(AGENT_STATE)
    agent_id = agent_state["agent_id"]
    tool_ids = agent_state.get("tool_ids") or {}
    state = load_json(state_path) if state_path.exists() else {}

    files = sorted(f for f in suite.glob("*.json") if f.name != "state.json")
    if args.only:
        globs = [g.strip() for g in args.only.split(",") if g.strip()]
        files = [f for f in files if any(fnmatch.fnmatch(f.name, g) for g in globs)]
        if not files:
            print(f"no files in {suite} match --only {args.only!r}")
            return 2
    print(f"{len(files)} test definition(s) in {suite}")

    api = Api(api_key())

    payloads = []
    for f in files:
        d = load_json(f)
        payload = build_payload(d, tool_ids)
        payload["_file"] = f.name
        payloads.append(payload)

    ids: list[str] = []
    order: dict[str, int] = {}
    files_by_name: dict[str, str] = {}
    for n, payload in enumerate(payloads):
        order[payload["name"]] = n
        files_by_name[payload["name"]] = payload["_file"]
        if args.no_push:
            tid = state.get(payload["name"])
            if not tid:
                print(f"  no stored id for '{payload['name']}' — run without --no-push")
                return 2
        else:
            tid = ensure_test(api, {k: v for k, v in payload.items() if k != "_file"}, state)
            state[payload["name"]] = tid
        ids.append(tid)
        print(f"  {payload['type']:<10} {payload['name']}  ->  {tid}")

    if not args.no_push:
        save_json(state_path, state)
        print(f"ids written to {state_path}")

    if args.push_only:
        print(f"\n--push-only: {len(ids)} tests pushed, nothing run.")
        return 0

    credits_before = credits_now(api)

    runs: list[dict] = []
    for run_index in range(1, args.repeat + 1):
        runs.append(run_once(api, agent_id, ids, order, files_by_name, run_index, args))

    credits_after = credits_now(api)
    delta = None
    if (credits_before.get("character_count") is not None
            and credits_after.get("character_count") is not None):
        delta = credits_after["character_count"] - credits_before["character_count"]

    print_table(runs)

    rows = [r for run in runs for r in run["rows"]]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = f"-{args.label}" if args.label else ""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"phase1-{stamp}{label}.json"
    payload_out = {
        "timestamp": stamp,
        "agent_id": agent_id,
        "label": args.label or None,
        "suite": str(suite.relative_to(ROOT)) if suite.is_relative_to(ROOT) else str(suite),
        "only": args.only or None,
        "repeat": args.repeat,
        "runs": [{k: v for k, v in run.items() if k != "raw_invocation"} for run in runs],
        # flat view across all runs, for single-run consumers
        "rows": rows,
        "pass": sum(1 for r in rows if r["status"] == "passed"),
        "fail": sum(1 for r in rows if r["status"] == "failed"),
        "total": len(rows),
        "credits": {
            "character_count_before": credits_before.get("character_count"),
            "character_count_after": credits_after.get("character_count"),
            "character_limit": credits_after.get("character_limit"),
            "delta": delta,
            "test_credits_used": sum(run.get("credits_used") or 0 for run in runs),
        },
    }
    if args.repeat == 1:
        # exact legacy shape: raw_invocation at the top level
        payload_out["test_invocation_id"] = runs[0]["test_invocation_id"]
        payload_out["raw_invocation"] = runs[0]["raw_invocation"]
    else:
        payload_out["raw_invocations"] = [run["raw_invocation"] for run in runs]
    save_json(out, payload_out)

    print("\n" + "=" * 78)
    print(f"repeat={args.repeat}  PASS {payload_out['pass']}/{payload_out['total']}")
    if delta is not None:
        print(f"credits: character_count {credits_before['character_count']} -> "
              f"{credits_after['character_count']} (delta {delta:+d})")
    print(f"results written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
