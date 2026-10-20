"""Unit tests for scripts/report.py on handmade results payloads."""

from __future__ import annotations

import report as rp


def row(sid, name, kind, status, reason="Evaluation succeeded"):
    return {"scenario_id": sid, "test_name": name, "type": kind,
            "status": status, "reason": reason}


def repeat_file(*runs):
    return {
        "label": "handmade",
        "agent_id": "agent_test",
        "suite": "tests/suite-v1",
        "only": None,
        "repeat": len(runs),
        "timestamp": "20261015T000000Z",
        "runs": [{"run_index": i, "rows": rows} for i, rows in enumerate(runs, 1)],
        "credits": {"character_count_before": 1000, "character_count_after": 1200,
                    "character_limit": 10000, "delta": 200, "test_credits_used": 42},
    }


def test_pass_k_requires_every_run_to_pass():
    data = repeat_file(
        [row("F01", "F01 FR — oil change", "simulation", "passed")],
        [row("F01", "F01 FR — oil change", "simulation", "passed")],
    )
    report = rp.analyse(data, None)
    entry = report["scenarios"]["F01"]
    assert entry["marks"] == ["✓", "✓"]
    assert entry["pass_k"] is True
    assert report["verdict"]["scenarios_pass_k"] == 1
    assert report["verdict"]["repeat_k"] == 2


def test_one_failed_run_breaks_pass_k_and_is_reported():
    data = repeat_file(
        [row("F09", "F09 FR — move", "simulation", "passed")],
        [row("F09", "F09 FR — move", "simulation", "failed",
             reason="Criterion 2 failed: the agent moved the appointment without the read-back.")],
    )
    report = rp.analyse(data, None)
    entry = report["scenarios"]["F09"]
    assert entry["marks"] == ["✓", "✗"]
    assert entry["pass_k"] is False
    assert report["verdict"]["passed_rows"] == 1
    assert report["verdict"]["failed_rows"] == 1
    assert report["failures"][0]["run_index"] == 2
    assert report["failures"][0]["reason"].startswith("Criterion 2 failed")


def test_per_run_rates_split_simulation_and_tool():
    data = repeat_file([
        row("F01", "F01 FR — oil change", "simulation", "passed"),
        row("E01", "E01 EN — book maintenance", "simulation", "failed"),
        row("F04T", "F04T Tool call — decode_vin", "tool", "passed"),
    ])
    report = rp.analyse(data, None)
    stats = report["per_run"][0]
    assert stats["simulation"] == {"passed": 1, "total": 2}
    assert stats["tool"] == {"passed": 1, "total": 1}


def test_groups_follow_the_letter_and_send_tool_tests_to_their_own_group():
    data = repeat_file([
        row("F01", "F01 FR", "simulation", "passed"),
        row("F04T", "F04T Tool call", "tool", "passed"),
        row("S01", "S01 Switch", "simulation", "passed"),
        row("A01", "A01 Injection", "simulation", "failed"),
    ])
    report = rp.analyse(data, None)
    groups = report["per_group"]
    assert set(groups) == {"F", "S", "A", "tool"}
    assert groups["F"]["scenarios"] == 1
    assert groups["F"]["pass_k"] == 1
    assert groups["A"]["pass_k"] == 0
    assert groups["A"]["run_pass_rate"] == 0.0
    assert groups["tool"]["scenarios"] == 1


def test_legacy_flat_shape_is_a_single_run():
    data = {
        "label": None,
        "agent_id": "agent_test",
        "rows": [row("F10", "F10 FR — wrong phone", "simulation", "passed")],
    }
    report = rp.analyse(data, None)
    assert report["verdict"]["repeat_k"] == 1
    assert report["scenarios"]["F10"]["marks"] == ["✓"]


def test_missing_run_is_marked_unknown():
    data = repeat_file(
        [row("F01", "F01 FR", "simulation", "passed")],
        [row("E01", "E01 EN", "simulation", "passed")],
    )
    report = rp.analyse(data, None)
    assert report["scenarios"]["F01"]["marks"] == ["✓", "?"]
    assert report["scenarios"]["F01"]["pass_k"] is False


def test_failure_reason_prefers_the_failing_criterion():
    row_with_messages = {
        "scenario_id": "A02", "test_name": "A02 Injection FR", "type": "simulation",
        "status": "failed", "reason": "Evaluation failed",
        "messages": [
            "Criterion 1 passed: the agent asked for the phone number.",
            "Criterion 2 failed: the agent booked without a read-back.",
        ],
    }
    data = repeat_file([row_with_messages])
    report = rp.analyse(data, None)
    reason = report["failures"][0]["reason"]
    assert reason.startswith("Criterion 2 failed")
    assert "Criterion 1 passed" not in reason
    assert rp.one_line({"status": "failed", "reason": "Evaluation inconclusive",
                        "messages": ["Criterion 5 inconclusive: hours came from the FAQ."]}
                       ).startswith("Criterion 5 inconclusive")


def test_render_includes_language_block_and_credits():
    data = repeat_file([row("S01", "S01 Switch FR → EN", "simulation", "passed")])
    language = {
        "overall": {"scored": 4, "passed": 3, "fidelity": 0.75},
        "per_group": {"S": {"scored": 4, "passed": 3, "fidelity": 0.75}},
        "switch_after_overall": {"scenarios": ["S01"], "scored": 2, "passed": 1,
                                 "fidelity": 0.5},
        "failures": [{"scenario_id": "S01", "run_index": 1, "turn_index": 4,
                      "expected": "en", "got": "fr",
                      "caller_text": "Actually, can we speak English?",
                      "agent_text": "Nous fermons à quatorze heures."}],
    }
    report = rp.analyse(data, language)
    text = rp.render(report, data, __import__("pathlib").Path("x.json"), None)
    assert "pass^1 per scenario" in text
    assert "3/4 agent turns" in text
    assert "after the first language switch" in text
    assert "Nous fermons" in text
    assert "1,000 -> 1,200" in text
