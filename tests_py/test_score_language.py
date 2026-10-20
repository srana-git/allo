"""Unit tests for scripts/score_language.py, on handmade transcripts."""

from __future__ import annotations

import score_language as sl

# ----------------------------------------------------------------- helpers

FR_GREETING = "Bonjour, service à la clientèle de Groupe Auto Laval, ici Léa."
FR_BOOKED = "Très bien, je vous confirme le rendez-vous pour mardi matin à neuf heures."
FR_CALLER = ("Bonjour, je voudrais prendre un rendez-vous pour un changement d'huile "
             "la semaine prochaine.")
FR_CLOSE = "Nous fermons à quatorze heures le samedi."

EN_GREETING = "Hi, thanks for calling Groupe Auto Laval. How can I help you today?"
EN_BOOKED = "No problem at all, I have booked that for you for Tuesday morning."
EN_CALLER = "Hi, I need to book an appointment for an oil change next week."
EN_HOURS = "Of course, we close at two in the afternoon on Saturday."

SWITCH_EN = "Actually, can we speak English please?"
SWITCH_FR = "En fait, je préférerais parler en français s'il vous plaît."


def turns(*pairs):
    return [{"role": role, "message": text} for role, text in pairs]


def result_for(pairs, scenario_id="S01", run_index=1):
    return sl.score_transcript(turns(*pairs), scenario_id, "handmade", run_index)


# ------------------------------------------------------- word counting / skip


def test_words_counts_letters_not_digits():
    assert sl.count_words("514 555 0142") == 0
    assert sl.count_words("Bonjour, ça va?") == 3
    assert sl.count_words("") == 0
    assert sl.count_words(None) == 0


def test_min_words_boundary_is_three():
    assert sl.is_scorable("Oui, ça marche.")
    assert not sl.is_scorable("Oui.")
    assert not sl.is_scorable("Yes, sure.")


def test_short_turns_are_skipped():
    res = result_for([
        ("agent", FR_GREETING),
        ("user", FR_CALLER),
        ("agent", "Okay."),            # 1 word: skipped
        ("user", "Mardi."),            # 1 word: skipped, language unchanged
        ("agent", FR_BOOKED),
    ])
    assert (res["scored"], res["passed"]) == (2, 2)
    assert res["failures"] == []


def test_tool_call_only_turns_are_skipped():
    res = result_for([
        ("agent", FR_GREETING),
        ("user", FR_CALLER),
        ("agent", ""),                 # tool-call-only turn
        ("agent", "   "),              # whitespace only
        ("agent", FR_BOOKED),
    ])
    assert (res["scored"], res["passed"]) == (2, 2)


# ------------------------------------------------------------ language rules


def test_before_any_user_turn_the_expected_language_is_french():
    res = result_for([
        ("agent", FR_GREETING),
        ("agent", FR_BOOKED),
        ("user", FR_CALLER),
        ("agent", FR_BOOKED),
    ])
    assert (res["scored"], res["passed"]) == (3, 3)


def test_english_first_agent_turn_is_flagged_against_french_default():
    res = result_for([
        ("agent", EN_GREETING),
        ("user", FR_CALLER),
        ("agent", FR_BOOKED),
    ])
    assert (res["scored"], res["passed"]) == (2, 1)
    assert len(res["failures"]) == 1
    assert res["failures"][0]["expected"] == "fr"
    assert res["failures"][0]["got"] == "en"
    assert res["failures"][0]["turn_index"] == 0


def test_pure_french_transcript_all_pass():
    res = result_for([
        ("agent", FR_GREETING),
        ("user", FR_CALLER),
        ("agent", FR_BOOKED),
        ("user", "Parfait, merci beaucoup."),
        ("agent", "Merci, bonne journée."),
    ], scenario_id="F01")
    assert (res["scored"], res["passed"]) == (3, 3)
    assert res["failures"] == []


def test_pure_english_transcript_all_pass():
    """The agent greets in French by design, then follows the English caller."""
    res = result_for([
        ("agent", FR_GREETING),
        ("user", EN_CALLER),
        ("agent", EN_BOOKED),
        ("user", "Thanks, that works for me."),
        ("agent", "You are welcome, see you Tuesday."),
    ], scenario_id="E01")
    assert (res["scored"], res["passed"]) == (3, 3)
    assert res["failures"] == []


def test_fr_to_en_switch_moves_the_expected_language():
    res = result_for([
        ("agent", FR_GREETING),
        ("user", "Bonjour, j'appelle pour le service."),
        ("agent", FR_BOOKED),
        ("user", SWITCH_EN),
        ("agent", EN_HOURS),
    ])
    assert (res["scored"], res["passed"]) == (3, 3)
    assert res["first_switch_turn"] == 3
    assert (res["after_switch_scored"], res["after_switch_passed"]) == (1, 1)


def test_agent_that_stays_french_after_an_english_switch_is_flagged():
    res = result_for([
        ("agent", FR_GREETING),
        ("user", "Bonjour, j'appelle pour le service."),
        ("agent", FR_BOOKED),
        ("user", SWITCH_EN),
        ("agent", FR_CLOSE),           # French after the caller switched to English
    ])
    assert (res["scored"], res["passed"]) == (3, 2)
    assert res["failures"][0]["expected"] == "en"
    assert res["failures"][0]["got"] == "fr"
    assert res["failures"][0]["caller_text"].startswith("Actually")
    assert res["failures"][0]["scenario_id"] == "S01"
    assert (res["after_switch_scored"], res["after_switch_passed"]) == (1, 0)


def test_english_to_french_switch():
    res = result_for([
        ("agent", FR_GREETING),
        ("user", EN_CALLER),
        ("agent", EN_BOOKED),
        ("user", SWITCH_FR),
        ("agent", FR_BOOKED),
    ], scenario_id="S02")
    assert (res["scored"], res["passed"]) == (3, 3)
    assert res["first_switch_turn"] == 3


def test_english_loanwords_in_french_stay_french():
    """S06: English car terms must not flip the caller's language."""
    res = result_for([
        ("agent", FR_GREETING),
        ("user", "Allô, mon char fait un bruit bizarre quand je freine et le check "
                 "engine light allume aussi."),
        ("agent", "Je comprends, nous allons vérifier le check engine light et les "
                  "brakes rapidement."),
        ("agent", "Est-ce que le bruit arrive seulement quand vous freinez?"),
    ], scenario_id="S06")
    assert (res["scored"], res["passed"]) == (3, 3)
    assert res["failures"] == []
    assert res["first_switch_turn"] is None


def test_brand_and_model_turn_does_not_flip_a_french_caller():
    """F03: "C'est une Honda. Honda Civic 2018." is French with almost no signal.

    lingua reads it as English at 0.578 and the turn has only two words that are
    not proper nouns, so neither condition for a language change is met.
    """
    turn = "C'est une Honda. Honda Civic 2018."
    assert sl.detect_language(turn) == "en"
    confidence = sl.detect_language_confidence(turn)[1]
    assert confidence < sl.MIN_CONFIDENCE
    assert sl.detect_language(" ".join(sl.content_words(turn))) == "fr"
    assert not sl.is_language_change(turn, confidence)

    res = result_for([
        ("agent", FR_GREETING),
        ("user", "Bonjour, j'ai pas le NIV avec moi là."),
        ("agent", FR_BOOKED),
        ("user", turn),
        ("agent", FR_BOOKED),
    ], scenario_id="F03")
    assert (res["scored"], res["passed"]) == (3, 3)
    assert res["failures"] == []
    assert res["first_switch_turn"] is None


def test_subaru_outback_turn_does_not_flip_a_french_caller():
    """F14: this one is detected English at 0.885 — only the word count saves it.

    The follow-up turn is the one dev-v1-run1 actually produced, caught by the
    confidence gate instead (0.759 for English).
    """
    turn = "C'est un Subaru Outback 2020."
    assert sl.detect_language(turn) == "en"
    confidence = sl.detect_language_confidence(turn)[1]
    assert confidence >= sl.MIN_CONFIDENCE
    assert sl.detect_language(" ".join(sl.content_words(turn))) == "fr"
    # the scorer detects on content words, which read as French, so no change happens

    follow_up = "C'est pour mon Subaru Outback 2020."
    assert sl.detect_language(follow_up) == "en"
    assert sl.detect_language(" ".join(sl.content_words(follow_up))) == "fr"

    res = result_for([
        ("agent", FR_GREETING),
        ("user", "Bonjour, je voudrais poser mes pneus d'hiver."),
        ("agent", FR_BOOKED),
        ("user", turn),
        ("user", follow_up),
        ("agent", FR_BOOKED),
    ], scenario_id="F14")
    assert (res["scored"], res["passed"]) == (3, 3)
    assert res["failures"] == []
    assert res["first_switch_turn"] is None


def test_a_real_language_change_still_moves_the_language():
    """The guard must not stop a genuine switch: high confidence, real words."""
    for turn in (SWITCH_EN, SWITCH_FR):
        confidence = sl.detect_language_confidence(turn)[1]
        assert confidence >= sl.MIN_CONFIDENCE
        assert len(sl.content_words(turn)) >= sl.MIN_WORDS
        assert sl.is_language_change(turn, confidence)


def test_caller_language_follows_the_most_recent_user_turn():
    res = result_for([
        ("user", FR_CALLER),
        ("agent", FR_BOOKED),
        ("user", SWITCH_EN),
        ("agent", EN_HOURS),
        ("user", SWITCH_FR),
        ("agent", FR_BOOKED),         # back to French: must pass again
    ])
    assert (res["scored"], res["passed"]) == (3, 3)
    assert res["first_switch_turn"] == 2


def test_no_switch_reported_for_a_single_language_call():
    res = result_for([
        ("user", FR_CALLER),
        ("agent", FR_BOOKED),
    ])
    assert res["first_switch_turn"] is None
    assert res["after_switch_scored"] == 0


# ------------------------------------------------------- shapes and grouping


def test_iter_runs_handles_both_shapes():
    flat = {"rows": [{"test_name": "F01"}]}
    assert list(sl.iter_runs(flat)) == [(1, [{"test_name": "F01"}])]

    repeated = {"repeat": 2, "runs": [
        {"run_index": 1, "rows": [{"test_name": "F01"}]},
        {"run_index": 2, "rows": [{"test_name": "F01"}]},
    ]}
    assert [idx for idx, _ in sl.iter_runs(repeated)] == [1, 2]


def test_scenario_id_and_group_of_row():
    assert sl.scenario_id_of_row({"scenario_id": "F03T"}) == "F03T"
    assert sl.scenario_id_of_row({"test_name": "F10 FR — déplacer"}) == "F10"
    assert sl.scenario_id_of_row({"test_name": "S01 Switch FR → EN",
                                  "test_id": "test_x"}) == "S01"
    assert sl.scenario_id_of_row({"test_name": "04 Tool call — decode_vin",
                                  "test_id": "test_x"}) == "test_x"
    assert sl.group_of("F03T", "tool") == "tool"
    assert sl.group_of("F03T", "simulation") == "F"
    assert sl.group_of("A02", "simulation") == "A"


def test_type_of_row_sniffs_legacy_tool_tests():
    assert sl.type_of_row({"type": "tool"}) == "tool"
    assert sl.type_of_row({"test_name": "E02T Tool call — check_recalls"}) == "tool"
    assert sl.type_of_row({"test_name": "F01 FR — oil change"}) == "simulation"


def test_score_results_aggregates_both_shapes():
    row = {
        "scenario_id": "S01",
        "test_name": "S01 Switch FR → EN",
        "type": "simulation",
        "transcript": turns(
            ("agent", FR_GREETING),
            ("user", "Bonjour, j'appelle pour le service."),
            ("user", SWITCH_EN),
            ("agent", EN_HOURS),
            ("agent", FR_CLOSE),       # the flagged turn
        ),
    }
    tool_row = {"scenario_id": "F04T", "test_name": "F04T Tool call", "type": "tool",
                "transcript": []}

    short = sl.score_results({"rows": [row, tool_row]}, "short.json")
    # 3 agent turns scored: the French greeting passes against the French
    # default, the English turn after the switch passes, the French turn
    # after the switch fails.
    assert short["overall"] == {"scored": 3, "passed": 2, "fidelity": 0.6667}
    assert short["per_group"]["S"]["fidelity"] == 0.6667
    assert short["per_scenario"]["S01"]["scenario"] == "S01 Switch FR → EN"
    assert short["switch_after"]["S01"]["fidelity"] == 0.5
    assert short["switch_after_overall"] == {
        "scenarios": ["S01"], "scored": 2, "passed": 1, "fidelity": 0.5}
    assert len(short["failures"]) == 1
    assert set(short["failures"][0]) == {
        "scenario_id", "scenario", "run_index", "turn_index", "caller_text",
        "agent_text", "expected", "got"}
    assert short["skipped"] == [
        {"scenario_id": "F04T", "run_index": 1, "reason": "no transcript"}]

    repeated = sl.score_results({"repeat": 2, "runs": [
        {"run_index": 1, "rows": [row]},
        {"run_index": 2, "rows": [row]},
    ]}, "repeat.json")
    assert repeated["overall"]["scored"] == 6
    assert repeated["overall"]["passed"] == 4
    assert repeated["repeat"] == 2
    assert sorted(f["run_index"] for f in repeated["failures"]) == [1, 2]


def test_fidelity_is_none_when_nothing_was_scored():
    assert sl.fidelity(0, 0) is None
    data = sl.score_results({"rows": [
        {"scenario_id": "F01", "test_name": "F01", "type": "simulation",
         "transcript": turns(("agent", "Okay."), ("user", "Oui."))}]})
    assert data["overall"] == {"scored": 0, "passed": 0, "fidelity": None}

    # a simulation row with an empty transcript is reported, not scored
    data = sl.score_results({"rows": [
        {"scenario_id": "F01", "test_name": "F01", "type": "simulation",
         "transcript": []}]})
    assert data["skipped"][0]["scenario_id"] == "F01"


def test_short_english_question_with_a_brand_is_a_language_change():
    turn = "Do you take Amex?"
    lang, confidence = sl.detect_language_confidence(" ".join(sl.content_words(turn)))
    assert lang == "en"
    assert sl.is_language_change(turn, confidence)
