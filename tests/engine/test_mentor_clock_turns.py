"""Defect 2 (2026-10-01): a clock change is never reported in turns. The clock axis is a 0-100
score (+1.7 points is ~0.2 turns), but the model said "improve the clock by about 1.7 turns" and the
gate passed it because 1.7 is a licensed number.

  * `tools._swap_result`: clock suggestions carry kill_turn_before/after/change + clock_note;
  * gate check 8 (`verdicts.turn_confusion_reasons`): both directions plus negatives;
  * prompt: one line telling the model clock changes are score points.
"""

from __future__ import annotations

from mythgauntlet.mentor import chat, gate, verdicts
from mythgauntlet.mentor.tools import _swap_result

Q = "How could I make it faster or more resilient?"


def _clock_data(found=True):
    sugs = []
    if found:
        sugs = [{
            "add": "Sol Ring", "cut": "Return of the Wildspeaker",
            "before": 13.690476190476184, "after": 15.368852459016388,
            "reason": "Measured to raise clock.",
            "brief": {"axis": "clock", "before": 13.7, "after": 15.4, "delta": 1.7,
                      "kill_turn_before": 10.357142857142858, "kill_turn_after": 10.155737704918034,
                      "redundancy_backed": True,
                      "cut": {"redundancy_backed": True},
                      "allowed_card_names": ["Sol Ring", "Return of the Wildspeaker"]},
        }]
    return {"axis": "clock", "axis_label": "Clock", "baseline": 13.690476190476184,
            "evaluated": 4, "min_delta": 1.0, "cut": "X", "suggestions": sugs}


def _res_data(found=False):
    sugs = []
    if found:
        sugs = [{"add": "Mask of Memory", "cut": "Gloomwidow's Feast",
                 "before": 92.9, "after": 94.3, "reason": "Card flow.",
                 "brief": {"axis": "resilience", "before": 92.9, "after": 94.3, "delta": 1.4,
                           "kill_turn_before": 9.3, "kill_turn_after": 9.4,
                           "cut": {"redundancy_backed": False},
                           "allowed_card_names": ["Mask of Memory", "Gloomwidow's Feast"]}}]
    return {"axis": "resilience", "axis_label": "Resilience", "baseline": 92.9,
            "evaluated": 4, "min_delta": 1.0, "cut": "X", "suggestions": sugs}


# ── defect 2a: the swap result carries the turn change ───────────────────────────────

def test_clock_swap_carries_kill_turn_fields_and_note():
    data = _swap_result(_clock_data()).data
    s = data["suggestions"][0]
    assert s["kill_turn_before"] == 10.36 and s["kill_turn_after"] == 10.16
    assert s["kill_turn_change"] == 0.2          # positive = kills sooner
    assert "not turns" in data["clock_note"] and "kill_turn_change" in data["clock_note"]


def test_other_axes_carry_no_clock_fields():
    data = _swap_result(_res_data(found=True)).data
    assert "clock_note" not in data
    assert "kill_turn_change" not in data["suggestions"][0]


# ── defect 2b: gate check 8 ──────────────────────────────────────────────────────────

def _clock_budget():
    results = [_swap_result(_clock_data(found=True))]
    return gate.ClaimBudget.from_tool_results(
        results, frozenset({"Sol Ring", "Return of the Wildspeaker"}))


def _check8(text):
    return [r for r in gate.check(text, _clock_budget(), question="faster?") if "SCORE" in r]


def test_score_delta_reported_as_turns_is_flagged():
    assert _check8("Swapping them improves the deck's clock by about 1.7 turns.")
    assert _check8("The clock goes from 13.7 to 15.4 and that is 15.4 turns of improvement.")


def test_points_and_real_turn_figures_pass():
    assert _check8("This raises the clock score by 1.7 points.") == []
    assert _check8("The average kill turn moves from 10.4 to 10.2, which is 0.2 turns sooner.") == []
    assert _check8("Its best draws kill around turn 9, about 9 turns in.") == []
    assert _check8("Kills in 10.4 turns on average, down to 10.2 turns.") == []
    # a number that is no clock figure at all is check 3's business, not check 8's
    assert _check8("Over the next 5 turns the deck develops.") == []


def test_check8_needs_a_clock_swap_this_turn():
    budget = gate.ClaimBudget.from_tool_results([_swap_result(_res_data(found=True))])
    reasons = gate.check("It improves the clock by about 1.7 turns.", budget)
    assert not [r for r in reasons if "SCORE" in r]


def test_kill_turn_figure_matching_wins_over_score_match():
    # score 10.4 coincides with a kill turn of 10.4: matching a kill-turn figure is a pass
    data = _clock_data(found=True)
    data["baseline"] = 10.4
    data["suggestions"][0]["before"] = 10.4
    assert verdicts.turn_confusion_reasons(
        "it kills in about 10.4 turns", [_swap_result(data).data]) == []


def test_prompt_says_clock_changes_are_points():
    p = chat.SYSTEM_PROMPT
    assert "SCORE points" in p and "kill_turn_change" in p
