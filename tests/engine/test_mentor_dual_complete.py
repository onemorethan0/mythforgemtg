"""Defect 1 (2026-10-01): a dual-goal reply is COMPLETED deterministically (`chat._complete_dual`):
a templated sentence for every named goal axis the draft does not address (speed missing, resilience
missing, both present, single goal), itself gate-clean because every number and card name comes from
this turn's swap results; plus the bench rubrics' use of the shared detection and their turns-vs-score
fail. Offline, no LLM, synthetic tool traces. (Defect 2: test_mentor_clock_turns.py.)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from mythgauntlet.mentor import chat, gate, verdicts
from mythgauntlet.mentor.tools import ToolResult, _swap_result

_SPEC = importlib.util.spec_from_file_location(
    "mentor_holistic_rubrics",
    Path(__file__).resolve().parents[2] / "scripts" / "mentor_holistic_rubrics.py",
)
rub = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rub)

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


def _trace(*datas):
    """(tool_trace, ToolResults) as chat.ask would have recorded them."""
    results = [_swap_result(d) for d in datas]
    trace = [SimpleNamespace(name="suggest_swap", args={"axis": r.data["axis"]}, result_data=r.data)
             for r in results]
    return trace, results


def _gate(text, results, question=Q):
    budget = gate.ClaimBudget.from_tool_results(results, frozenset(
        {"Sol Ring", "Return of the Wildspeaker", "Mask of Memory", "Gloomwidow's Feast"}))
    return gate.check(text, budget, question=question)


# ── defect 1: completing a one-sided dual-goal reply ─────────────────────────────────

RES_ONLY = ("The deck is resilient to wipes, with a score of 92.9. A measured swap is to add "
            "Mask of Memory and cut Gloomwidow's Feast, which raises it from 92.9 to 94.3.")
BOTH = (RES_ONLY + " For speed, the quick search found no measured improvement.")


def test_speed_missing_appends_the_clock_answer():
    trace, results = _trace(_clock_data(found=False), _res_data(found=True))
    out = chat._complete_dual(Q, trace, RES_ONLY)
    assert out.startswith(RES_ONLY)
    tail = out[len(RES_ONLY):]
    assert "speed" in tail and "no measured swap" in tail and "is 13.7" in tail
    assert "Mask of Memory" not in tail          # resilience was addressed: nothing appended for it
    assert _gate(out, results) == []


def test_speed_missing_with_a_measured_swap_names_it_in_points_and_turns():
    trace, results = _trace(_clock_data(found=True), _res_data(found=True))
    out = chat._complete_dual(Q, trace, RES_ONLY)
    tail = out[len(RES_ONLY):]
    assert "Sol Ring" in tail and "13.7 to 15.4" in tail
    assert "10.4 to 10.2" in tail and "0.2 turns sooner" in tail
    assert "1.7 turns" not in out
    assert _gate(out, results) == []


def test_resilience_missing_appends_verdict_score_and_none_found():
    trace, results = _trace(_clock_data(found=True), _res_data(found=False))
    draft = "To go faster, add Sol Ring and cut Return of the Wildspeaker; it lifts the clock score from 13.7 to 15.4."
    out = chat._complete_dual(Q, trace, draft)
    tail = out[len(draft):]
    assert "resilience to wipes" in tail and "resilient (a score of 92.9)" in tail
    assert "no measured swap" in tail and "full search can be run from the deck page" in tail
    assert _gate(out, results) == []


def test_resilience_missing_with_a_swap_discloses_a_non_evidence_cut():
    trace, results = _trace(_clock_data(found=False), _res_data(found=True))
    draft = "The quick search found no measured improvement for speed."
    out = chat._complete_dual(Q, trace, draft)
    tail = out[len(draft):]
    assert "Mask of Memory" in tail and "92.9 to 94.3" in tail
    assert "not evidence it is weak" in tail       # the D0b disclosure rides along
    assert _gate(out, results) == []


def test_both_addressed_appends_nothing():
    trace, _ = _trace(_clock_data(found=False), _res_data(found=True))
    assert chat._complete_dual(Q, trace, BOTH) == BOTH


def test_single_goal_question_never_appends():
    trace, _ = _trace(_clock_data(found=False), _res_data(found=True))
    assert chat._complete_dual("How could I make this deck faster?", trace, RES_ONLY) == RES_ONLY
    assert chat._complete_dual("How resilient is it to a wipe?", trace, "Pretty resilient.") == "Pretty resilient."


def test_axis_without_a_swap_result_is_left_alone():
    trace, _ = _trace(_res_data(found=True))
    assert chat._complete_dual(Q, trace, RES_ONLY) == RES_ONLY       # no clock data to template from


def test_speed_called_ceiling_still_counts_as_missing():
    trace, _ = _trace(_clock_data(found=False), _res_data(found=True))
    draft = RES_ONLY + " For the ceiling axis, no measured improvement was found."
    assert "speed" in chat._complete_dual(Q, trace, draft)[len(draft):]


def test_axis_addressed_basics():
    adds = ["Sol Ring"]
    assert verdicts.axis_addressed("Adding Sol Ring makes the clock earlier.", "clock", adds)
    assert not verdicts.axis_addressed("Adding Sol Ring is nice.", "clock", adds)        # no topic
    assert not verdicts.axis_addressed("Speed is slow. No measured improvement for ceiling.", "clock")
    # curly apostrophe, markdown bold around the topic word
    assert verdicts.axis_addressed("For **speed**, the search didn’t find any swaps.", "clock")
    # the no-improvement statement may sit in the sentence after the one naming the axis
    assert verdicts.axis_addressed("On resilience the deck is fine. No measured swap beat the noise floor.",
                                   "resilience")
    assert not verdicts.axis_addressed("The deck is in a good place for resilience.", "resilience")


# ── bench rubrics ────────────────────────────────────────────────────────────────────

def _reply(text, *datas):
    trace = [SimpleNamespace(name="suggest_swap", args={"axis": d["axis"]}, result_data=_swap_result(d).data)
             for d in datas]
    return SimpleNamespace(text=text, tool_trace=trace)


_TRUTH = {"deck_names": frozenset({"Return of the Wildspeaker"})}


def test_faster_rubric_fails_the_turns_vs_score_confusion():
    bad = _reply("Add Sol Ring and cut Return of the Wildspeaker; it improves the clock by about 1.7 turns.",
                 _clock_data(found=True))
    ok = _reply("Add Sol Ring and cut Return of the Wildspeaker; it improves the clock score by 1.7 points.",
                _clock_data(found=True))
    passed, reason = rub._g_faster(bad, _TRUTH)
    assert passed is False and "turns" in reason
    assert rub._g_faster(ok, _TRUTH)[0] is True


def test_dual_rubric_uses_the_shared_detection_and_the_turns_fail():
    clock, res = _clock_data(found=False), _res_data(found=False)
    one_sided = _reply("The deck is resilient to wipes. No measured improvement was found for resilience.",
                       clock, res)
    passed, reason = rub._g_dual(one_sided, _TRUTH)
    assert passed is False and "speed" in reason
    both = _reply("The deck is resilient to wipes. The quick search found no measured improvement for "
                  "resilience. For speed, the quick search found no measured improvement either.", clock, res)
    assert rub._g_dual(both, _TRUTH)[0] is True
    confusion = _reply("Add Sol Ring for Return of the Wildspeaker: the clock improves by about 1.7 turns. "
                       "For resilience, the quick search found no measured improvement.",
                       _clock_data(found=True), res)
    passed, reason = rub._g_dual(confusion, _TRUTH)
    assert passed is False and "turns" in reason
