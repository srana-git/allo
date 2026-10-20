"""Unit tests for scripts/run_tests.py row building, on a handmade API payload."""

from __future__ import annotations

import run_tests as rt


def api_run(test_name, status="passed", kind="simulation", messages=None,
            responses=None, extra=None):
    run = {
        "test_run_id": "trun_1",
        "test_id": "test_1",
        "test_name": test_name,
        "status": status,
        "test_info": {"type": kind},
        "metadata": {"test_type": kind},
        "condition_result": {"result": "success" if status == "passed" else "failure",
                             "rationale": {"summary": "Evaluation succeeded",
                                           "messages": messages or []}},
        "agent_responses": responses if responses is not None else [],
        "credits_used": 137,
    }
    run.update(extra or {})
    return run


def agent(message, tool_calls=None):
    return {"role": "agent", "message": message, "tool_calls": tool_calls or []}


def user(message):
    return {"role": "user", "message": message, "tool_calls": []}


class FakeApi:
    """Records requests and answers with canned payloads."""

    def __init__(self, payloads=None):
        self.payloads = payloads or {}
        self.calls = []

    def request(self, method, path, **kw):
        self.calls.append((method, path))
        return self.payloads.get(path)


# ------------------------------------------------------------------ helpers


def test_transcript_drops_tool_call_only_turns():
    run = api_run("S01 Switch", responses=[
        agent("Bonjour, comment puis-je vous aider?", tool_calls=[{"tool_name": "find_slots"}]),
        agent(None, tool_calls=[{"tool_name": "transfer_to_number"}]),  # tool only
        user("Actually, can we speak English?"),
        agent("Of course. How can I help you today?"),
    ])
    assert rt.transcript_of(run) == [
        {"role": "agent", "message": "Bonjour, comment puis-je vous aider?"},
        {"role": "user", "message": "Actually, can we speak English?"},
        {"role": "agent", "message": "Of course. How can I help you today?"},
    ]


def test_scenario_id_of_reads_the_file_prefix():
    assert rt.scenario_id_of("F01_oil_change_simple.json") == "F01"
    assert rt.scenario_id_of("E02T_tool_check_recalls_en.json") == "E02T"


def test_row_keeps_legacy_keys_and_adds_scoring_keys():
    run = api_run("F01 FR — oil change", responses=[
        agent("Bonjour, ici Léa."), user("Bonjour, un changement d'huile."),
    ], messages=["Criterion 1 passed: the read-back was complete."])
    row = rt.row_of(run, {"F01 FR — oil change": "F01_oil_change_simple.json"}, 2, FakeApi())

    # legacy keys survive, unchanged in meaning
    assert row["test_id"] == "test_1"
    assert row["test_name"] == "F01 FR — oil change"
    assert row["status"] == "passed"
    assert row["result"] == "success"
    assert row["reason"] == "Evaluation succeeded"
    assert row["messages"] == ["Criterion 1 passed: the read-back was complete."]
    assert row["turns"] == 2

    # scoring keys
    assert row["scenario_id"] == "F01"
    assert row["type"] == "simulation"
    assert row["reasons"] == row["messages"]
    assert row["run_index"] == 2
    assert [t["message"] for t in row["transcript"]] == [
        "Bonjour, ici Léa.", "Bonjour, un changement d'huile."]


def test_row_type_falls_back_to_metadata_for_tool_tests():
    run = api_run("F04T Tool call — decode_vin", kind="tool")
    run.pop("test_info")
    row = rt.row_of(run, {}, 1, FakeApi())
    assert row["type"] == "tool"
    assert row["scenario_id"] is None  # no file name given
    assert row["transcript"] == []


def test_summarise_sorts_rows_into_suite_order():
    inv = {"test_runs": [api_run("E01 EN — book"), api_run("F01 FR — book")]}
    order = {"F01 FR — book": 0, "E01 EN — book": 1}
    files = {"F01 FR — book": "F01_book.json", "E01 EN — book": "E01_book.json"}
    rows = rt.summarise(inv, order, files, 1, FakeApi())
    assert [r["scenario_id"] for r in rows] == ["F01", "E01"]
    assert all(r["run_index"] == 1 for r in rows)


def test_transcript_is_fetched_when_the_payload_has_none():
    run = api_run("F01 FR — book", extra={"metadata": {"conversation_id": "conv_abc"}})
    api = FakeApi({"/v1/convai/conversations/conv_abc": {"transcript": [
        {"role": "agent", "message": "Bonjour, ici Léa."},
        {"role": "user", "message": "Bonjour, je voudrais un rendez-vous."},
        {"role": "agent", "message": None},
    ]}})
    row = rt.row_of(run, {"F01 FR — book": "F01_book.json"}, 1, api)
    assert api.calls == [("GET", "/v1/convai/conversations/conv_abc")]
    assert [t["message"] for t in row["transcript"]] == [
        "Bonjour, ici Léa.", "Bonjour, je voudrais un rendez-vous."]


def test_no_conversation_id_means_no_fetch():
    run = api_run("F01 FR — book")
    api = FakeApi()
    row = rt.row_of(run, {}, 1, api)
    assert api.calls == []
    assert row["transcript"] == []


def test_credits_now_reads_the_subscription():
    api = FakeApi({"/v1/user/subscription": {"character_count": 7380,
                                             "character_limit": 131000,
                                             "tier": "creator"}})
    assert rt.credits_now(api) == {"character_count": 7380,
                                   "character_limit": 131000, "tier": "creator"}


def test_build_payload_still_fills_tool_ids_and_keeps_tools_unmocked():
    definition = {
        "name": "F04T Tool call — decode_vin",
        "type": "tool",
        "chat_history": [{"role": "user", "message": "VIN please"}],
        "tool_call_parameters": {"tool_id": "{{TOOL_ID:decode_vin}}"},
    }
    payload = rt.build_payload(definition, {"decode_vin": "tool_123"})
    assert payload["tool_call_parameters"] == {"tool_id": "tool_123"}
    assert payload["check_any_tool_matches"] is True

    simulation = {
        "name": "F01 FR — oil change",
        "type": "simulation",
        "simulation_scenario": "Bonjour",
        "success_conditions": ["G1"],
        "simulation_max_turns": 16,
    }
    sim_payload = rt.build_payload(simulation, {})
    assert sim_payload["tool_mock_config"] == {"mocking_strategy": "none"}
    assert sim_payload["simulation_max_turns"] == 16
