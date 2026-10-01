"""Round 8 residuals (2026-10-01): an unmeasured side claim riding on a measured swap, and a
dual-goal question answered for one goal. Four pieces, tested offline and sim-free:

  * prompt (A): `chat.SYSTEM_PROMPT` restricts swap narration to the measured axis;
  * chat (B): `_goal_axes` / `_missing_goal_axes` and the one-nudge-per-turn dual-goal loop;
  * gate (C): check 7 (`verdicts.unmeasured_side_claims` + `ClaimBudget.swap_axes`), both
    directions plus unrelated-prose negatives (bias under test is UNDER-flagging);
  * bench (D): the `faster` / `weakest` side-claim rubric and the `dual` rubric.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from mythgauntlet.mentor import chat, gate, verdicts
from mythgauntlet.mentor.tools import ToolResult

_SPEC = importlib.util.spec_from_file_location(
    "mentor_holistic_rubrics",
    Path(__file__).resolve().parents[2] / "scripts" / "mentor_holistic_rubrics.py",
)
rub = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rub)


# ── A: prompt ───────────────────────────────────────────────────────────────────────

def test_prompt_restricts_swap_narration_to_the_measured_axis():
    p = chat.SYSTEM_PROMPT
    assert "Describe its effect ONLY on that axis" in p
    assert "NEVER say or imply that the swap leaves ANOTHER axis" in p
    assert "measured only that axis" in p
    assert "STILL call suggest_swap" in p and 'never answer with only "run Advise"' in p


def test_prompt_asks_for_each_goal_and_bans_the_generic_closer():
    p = chat.SYSTEM_PROMPT
    assert "address EACH" in p and "once per axis" in p
    assert "generic card-type advice that no tool backed" in p


# ── B: dual-goal detection and the nudge ────────────────────────────────────────────

@pytest.mark.parametrize("question, axes", [
    ("How could I make it faster or more resilient?", ["clock", "resilience"]),
    ("How can I speed up this deck and survive wipes?", ["clock", "resilience"]),
    ("Make it quicker and more consistent", ["clock", "consistency"]),
    ("How could I make this deck faster?", ["clock"]),                               # one goal
    ("How resilient is this deck to a board wipe, and how could I improve that?", ["resilience"]),
    ("What should I cut?", []),                                                       # no axis word
    ("Is my removal good enough, and what can it not answer?", []),                   # not a swap question
    ("Is it fast, and how resilient is it to a wipe?", []),                           # not a swap question
])
def test_goal_axes(question, axes):
    assert chat._goal_axes(question) == axes


def _t(name, axis, available=None):
    data = {} if available is None else {"available": available}
    return SimpleNamespace(name=name, args={"axis": axis}, result_data=data)


def test_missing_goal_axes_needs_an_answer_not_just_a_lookup():
    q = "How could I make it faster or more resilient?"
    assert chat._missing_goal_axes(q, []) == ["clock", "resilience"]
    assert chat._missing_goal_axes(q, [_t("get_measured_swaps", "clock", True)]) == ["resilience"]
    # an UNAVAILABLE cached search is not an answer: the suggest_swap fallback is still owed
    assert chat._missing_goal_axes(q, [_t("get_measured_swaps", "clock", False)]) == ["clock", "resilience"]
    assert chat._missing_goal_axes(q, [_t("suggest_swap", "clock"), _t("get_measured_swaps", "resilience", True)]) == []
    assert chat._missing_goal_axes("How could I make this deck faster?", []) == []   # single goal: never


def _call(name, args="{}"):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": "1", "function": {"name": name, "arguments": args}}]}


def _drive(monkeypatch, script, tool_data):
    seen, ran = [], []

    def fake_post(messages, *, model, temperature, max_tokens, timeout=120):
        seen.append(messages[-1].get("content"))
        return script[min(len(seen) - 1, len(script) - 1)]

    def fake_call(ctx, name, args):
        ran.append((name, args))
        return ToolResult(data=tool_data(name, args))

    monkeypatch.setattr(chat, "_post_chat", fake_post)
    monkeypatch.setattr(chat, "call_tool", fake_call)
    return seen, ran


def _swap_data(name, args):
    return {"available": True, "axis": args.get("axis"), "improving_swap_found": False,
            "found": True}


HONEST = {"role": "assistant", "content": "I didn't find a measured improvement from your collection."}


def test_dual_goal_question_with_one_lookup_is_nudged_for_the_other_axis(monkeypatch):
    seen, ran = _drive(
        monkeypatch,
        [_call("get_measured_swaps", '{"axis": "clock"}'), HONEST,        # draft before the nudge
         _call("get_measured_swaps", '{"axis": "resilience"}'), HONEST],
        _swap_data)
    reply = chat.ask(SimpleNamespace(all_card_names=frozenset()),
                     "How could I make it faster or more resilient?")
    assert [r[1]["axis"] for r in ran] == ["clock", "resilience"]
    assert "resilience" in seen[2] and "EACH goal" in seen[2]               # the nudge named the gap
    assert [t.args["axis"] for t in reply.tool_trace] == ["clock", "resilience"]


def test_dual_goal_nudge_is_once_per_turn(monkeypatch):
    seen, ran = _drive(monkeypatch, [_call("get_measured_swaps", '{"axis": "clock"}'), HONEST],
                       _swap_data)
    chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make it faster or more resilient?")
    assert sum("EACH goal" in (s or "") for s in seen) == 1                  # model ignores it: no loop


def test_single_goal_question_gets_no_dual_nudge(monkeypatch):
    seen, ran = _drive(monkeypatch, [_call("get_measured_swaps", '{"axis": "clock"}'), HONEST],
                       _swap_data)
    chat.ask(SimpleNamespace(all_card_names=frozenset()), "How could I make this deck faster?")
    assert len(seen) == 2 and not any("EACH goal" in (s or "") for s in seen)


# ── C: the phrase map ───────────────────────────────────────────────────────────────

LIVE_1 = "Cutting it doesn't hurt your deck's interaction or resilience."
LIVE_2 = "This swap improves the clock while maintaining its consistency and interaction."


def _claims(text, *axes):
    return verdicts.unmeasured_side_claims(text, axes or ("clock",))


def test_the_two_live_side_claims_are_flagged_for_a_clock_swap():
    assert len(_claims(LIVE_1)) == 1 and _claims(LIVE_1)[0][1] == LIVE_1
    assert len(_claims(LIVE_2)) == 1 and _claims(LIVE_2)[0][1] == LIVE_2


@pytest.mark.parametrize("text, family", [
    ("It won't affect your resilience to wipes.", "resilience"),
    ("You get there faster without sacrificing consistency.", "consistency"),
    ("The deck keeps its interaction suite intact.", "interaction"),
    ("There is no negative impact on your ceiling.", "ceiling"),
    ("Your removal is unaffected by this swap.", "interaction"),                  # state phrase, topic before
    ("Your wipe resilience stays intact.", "resilience"),
    ("It does not compromise the deck's consistency.", "consistency"),
])
def test_side_claim_phrasings_are_flagged(text, family):
    assert [f for f, _ in _claims(text)] == [family]


def test_a_resilience_swap_flags_a_claim_about_the_clock_not_about_resilience():
    assert [f for f, _ in _claims("It doesn't slow your clock at all.", "resilience")] == ["speed"]
    assert not _claims("It doesn't hurt your wipe resilience either.", "resilience")


def test_the_measured_axis_itself_is_never_flagged():
    assert not _claims("The swap doesn't hurt your clock; it moves it from 20.1 to 21.4.")
    assert not _claims("It keeps the deck's speed where it was.")
    assert not _claims("Cutting it won't affect how early the deck kills.")        # no axis topic word at all


def test_clock_and_speed_are_one_family():
    assert not _claims("It maintains the deck's speed.", "speed")
    assert not _claims("It doesn't hurt your clock.", "speed")


def test_both_axes_measured_leaves_the_other_two_checkable():
    text = "It doesn't hurt your resilience or your interaction."
    assert [f for f, _ in _claims(text, "clock", "resilience")] == ["interaction"]


@pytest.mark.parametrize("text", [
    "This keeps your mana base intact.",                                           # no axis topic word
    "It keeps your commander on the table longer.",
    "Cutting a land doesn't hurt your curve.",
    "The deck keeps its creatures and goes wide.",
    "Sol Ring maintains a steady stream of mana.",
    "Your interaction is thin: 4 removal spells and no counterspells.",             # no side-effect phrase
    "The deck is consistent and has plenty of removal.",
    "I only measured the clock, so I can't say whether it hurts your interaction.",  # honest disclosure
    "The effect on resilience has not been measured, so it may not leave your wipe resilience intact.",
    "I didn't test whether your consistency is unaffected.",
    "Maintaining a good curve matters, but removal is the real gap.",              # topic is NOT the phrase's object window
])
def test_unrelated_and_honest_prose_is_not_flagged(text):
    assert not _claims(text)


def test_no_measured_axes_checks_nothing():
    assert verdicts.unmeasured_side_claims(LIVE_1, ()) == []
    assert verdicts.side_claim_reasons(LIVE_1, ()) == []
    assert verdicts.side_claim_reasons(LIVE_1, ("nonsense",)) == []


def test_reason_names_the_family_and_the_measured_axis_once():
    reasons = verdicts.side_claim_reasons(LIVE_1 + " It doesn't hurt resilience at all.", ("clock",))
    assert len(reasons) == 1
    assert "resilience" in reasons[0] and "speed" in reasons[0] and "offer to measure" in reasons[0]


# ── C: the gate plumbing ────────────────────────────────────────────────────────────

def _result(**data):
    return ToolResult(data=data)


def test_budget_reads_swap_axes_from_the_swap_result_shape():
    b = gate.ClaimBudget.from_tool_results([
        _result(found=True, axis="clock", improving_swap_found=True, suggestions=[]),
        _result(available=True, axis="resilience", improving_swap_found=False, found=True),
        _result(available=False, axis="interaction", message="no search yet"),    # unavailable: not measured
        _result(found=False, message="no collection"),
    ])
    assert b.swap_axes == frozenset({"clock", "resilience"})


def _budget(*axes):
    return gate.ClaimBudget(swap_axes=frozenset(axes))


def test_gate_flags_the_live_reply_for_a_clock_swap():
    text = ("Adding a card and cutting another moves the clock. " + LIVE_1)
    reasons = gate.check(text, _budget("clock"))
    assert any("resilience" in r and "only measured speed" in r for r in reasons)


def test_gate_is_silent_without_a_swap_result_this_turn():
    assert not [r for r in gate.check(LIVE_1, _budget()) if "unharmed" in r]


def test_gate_is_silent_when_the_claimed_axis_was_measured():
    assert not [r for r in gate.check(LIVE_1, _budget("resilience", "interaction")) if "unharmed" in r]


def test_gate_passes_the_honest_narration():
    text = ("Adding a card and cutting another moves the clock earlier. I only measured the clock, "
            "so I can run a search for your interaction if you want.")
    assert not [r for r in gate.check(text, _budget("clock")) if "unharmed" in r]


# ── D: bench rubrics ────────────────────────────────────────────────────────────────

DECK = frozenset({"Shelob, Child of Ungoliant", "Gloomwidow's Feast", "Cultivate", "Sol Ring"})


def _reply(text, trace=()):
    return SimpleNamespace(
        text=text, gated=True, gate_rejections=[],
        tool_trace=[SimpleNamespace(name=n, args=a, result_data=d) for n, a, d in trace])


def _truth():
    return {"deck_names": DECK, "ctx": SimpleNamespace(all_card_names=DECK | {"Lightning Bolt"}),
            "identity": frozenset("BG"),
            "_swap_cache": {"clock": {"found": True}, "weakest": {"found": True}}}


def _swap(axis, found=True, add="Lightning Bolt", cut="Cultivate", before=9.5, after=9.2):
    d = {"found": True, "axis": axis, "improving_swap_found": found,
         "suggestions": ([{"add": add, "cut": cut,
                           "brief": {"kill_turn_before": before, "kill_turn_after": after}}]
                         if found else [])}
    return ("get_measured_swaps", {"axis": axis}, {**d, "available": True})


def test_faster_fails_an_unmeasured_side_claim_on_a_measured_swap():
    text = "Swap Cultivate for Lightning Bolt. Cutting it doesn't hurt your deck's interaction or resilience."
    ok, why = rub.grade("faster", _reply(text, [_swap("clock")]), _truth())
    assert ok is False and "unmeasured side claim" in why


def test_faster_passes_the_same_swap_narrated_on_its_own_axis():
    text = "Swap Cultivate for Lightning Bolt: the clock improves. I only measured speed, so ask if you want the rest."
    ok, _ = rub.grade("faster", _reply(text, [_swap("clock")]), _truth())
    assert ok is True


def test_faster_side_claim_check_also_covers_the_empty_search_reply():
    text = "I didn't find a measured improvement, but your interaction is unaffected either way."
    ok, why = rub.grade("faster", _reply(text, [_swap("clock", found=False)]), _truth())
    assert ok is False and "unmeasured side claim" in why


def test_weakest_shares_the_side_claim_check():
    text = "Cultivate for Lightning Bolt. Nothing else changes, and your consistency is maintained."
    ok, why = rub.grade("weakest", _reply(text, [_swap("resilience")]), _truth())
    assert ok is False and "unmeasured side claim" in why


def test_dual_needs_a_lookup_for_each_axis():
    text = "Swap Cultivate for Lightning Bolt to kill earlier; wipes are the other risk."
    ok, why = rub.grade("dual", _reply(text, [_swap("clock")]), _truth())
    assert ok is False and "resilience" in why and "no swap lookup" in why


def test_dual_passes_two_lookups_answered_on_their_own_axes():
    text = ("For speed, swap Cultivate for Lightning Bolt. For wipes, I didn't find a measured "
            "improvement from your collection.")
    ok, why = rub.grade("dual", _reply(text, [_swap("clock"), _swap("resilience", found=False)]), _truth())
    assert ok is True, why


def test_dual_fails_an_answer_for_one_goal_only():
    text = "Swap Cultivate for Lightning Bolt to be faster."
    ok, why = rub.grade("dual", _reply(text, [_swap("clock"), _swap("resilience", found=False)]), _truth())
    assert ok is False and "wipe resilience" in why


def test_dual_fails_a_side_claim_and_a_slower_clock_swap():
    text = ("Swap Cultivate for Lightning Bolt to be faster; your wipe resilience is unaffected "
            "and your interaction is intact.")
    ok, why = rub.grade("dual", _reply(text, [_swap("clock")] + [_swap("resilience", found=False)]), _truth())
    assert ok is False and "unmeasured side claim" in why
    ok, why = rub.grade("dual", _reply("Swap Cultivate for Lightning Bolt for speed. Wipes: none found.",
                                       [_swap("clock", before=9.2, after=9.5),
                                        _swap("resilience", found=False)]), _truth())
    assert ok is False and "does not kill earlier" in why


def test_the_dual_question_is_registered_and_old_saved_runs_still_regrade():
    assert "dual" in rub.QUESTION_IDS and "dual" in rub.GRADERS
    bench = importlib.util.spec_from_file_location(
        "mentor_holistic_bench_probe",
        Path(__file__).resolve().parents[2] / "scripts" / "mentor_holistic_bench.py")
    src = Path(bench.origin).read_text(encoding="utf-8")
    assert '("dual",' in src and "faster or more resilient" in src
    # --regrade walks the SAVED rows by qid, so a run saved before `dual` existed has no such row
    # and is simply graded without it; it needs no migration.
    assert "for row in rows:" in src and 'row["qid"] == "colour"' in src


def test_dual_goal_question_routes_a_stray_axis_to_a_named_goal():
    q = "How could I make it faster or more resilient?"
    assert chat._route_swap_axis(q, {"axis": "interaction"})["axis"] == "resilience"
    assert chat._route_swap_axis(q, {"axis": "ceiling"})["axis"] == "clock"
    assert chat._route_swap_axis(q, {"axis": "resilience"})["axis"] == "resilience"
    # single-goal behaviour is unchanged
    assert chat._route_swap_axis("How could I make this deck faster?", {"axis": "ceiling"})["axis"] == "clock"
    assert chat._route_swap_axis("What should I cut?", {"axis": "interaction"})["axis"] == "interaction"
