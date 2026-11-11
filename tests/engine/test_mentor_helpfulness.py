"""Mentor helpfulness fixes (2026-11-09 review of the owner's real transcripts): the command zone
is always in hand, synergy questions get the lens's answer (including its absence), weak/strong
card questions get the measured verdicts, "out of gas" is a card-draw question, and generic
card-type advice is gated."""
from types import SimpleNamespace

from mythgauntlet.mentor import chat, gate
from mythgauntlet.mentor.chat import ToolCallRecord


def _cmd(name, text):
    return SimpleNamespace(name=name, oracle_text=text)


SMAUG = _cmd("Smaug the Impenetrable", "Flying, indestructible, haste\nWhenever Smaug is dealt "
                                       "noncombat damage, create that many Treasure tokens.")


def test_generic_card_type_advice_is_gated():
    for text in ("In the meantime, consider looking for cards that provide a faster win condition.",
                 "You should focus on adding more payoff cards that can use the ramp.",
                 "Look for cards that can deal direct damage."):
        assert any("generic card-type advice" in r for r in gate.check(text, gate.ClaimBudget()))
    for text in ("Consider the cards that the swap measured.",
                 "Adding more card draw options could help your deck."):
        assert not any("generic card-type advice" in r for r in gate.check(text, gate.ClaimBudget()))


def test_out_of_gas_reads_as_a_draw_question():
    assert chat._OUT_OF_GAS_RE.search("My deck keeps running out of gas. What should I change?")
    assert chat._OUT_OF_GAS_RE.search("I always end up top-decking by turn 6")
    assert not chat._OUT_OF_GAS_RE.search("How can I make this deck faster?")


def test_no_lens_fact_synergy_answer_quotes_the_commander():
    ctx = SimpleNamespace(resolved=SimpleNamespace(commanders=[SMAUG]))
    trace = [ToolCallRecord("lookup_card", {"name": "Smaug the Impenetrable"},
                            {"found": True, "name": "Smaug the Impenetrable"}),
             ToolCallRecord("lookup_card", {"name": "Dauthi Voidwalker"},
                            {"found": True, "name": "Dauthi Voidwalker",
                             "oracle_text": "Shadow\nIf a card would be put into an opponent's "
                                            "graveyard from anywhere, instead exile it with a "
                                            "void counter on it."})]
    q = "does Dauthi Voidwalker synergise with my commander?"
    absent = chat._no_lens_fact_cards(ctx, q, trace)
    assert [d["name"] for d in absent] == ["Dauthi Voidwalker"]          # never the commander
    text = chat._synergy_absence_answer(ctx, absent)
    assert text.startswith("Not directly.")
    assert "noncombat damage, create that many Treasure" in text
    assert chat._NO_COMMANDER_INFO_RE.search(
        "I cannot determine if Dauthi Voidwalker synergizes with your commander")
    assert chat._NO_COMMANDER_INFO_RE.search(
        "we don't have information about who your commander is")
    # a card the lens HAS a fact for is not an absence
    trace[1] = ToolCallRecord("lookup_card", {"name": "Lightning Bolt"},
                              {"found": True, "name": "Lightning Bolt",
                               "commander_synergy": {"kind": "damage_to_self_payoff"}})
    assert chat._no_lens_fact_cards(ctx, "does Lightning Bolt synergise with my commander?",
                                    trace) == []


def test_weak_card_question_leads_with_the_measured_list():
    verdicts = {"found": True, "strong": [],
                "weak": [{"name": "Controvert", "kind": "redundant",
                          "why": "Controvert: the deck runs 10 counterspell cards against a "
                                 "typical 1"}]}
    trace = [ToolCallRecord("get_card_verdicts", {}, verdicts)]
    q = "What are the three weakest cards in the deck?"
    out = chat._verdict_paragraph(q, trace, "I didn't find a measured improvement.")
    assert out.startswith("Measured weakest cards:\n- Controvert:")
    # a draft that already names the measured card is left alone
    named = "Controvert is the most replaceable counterspell."
    assert chat._verdict_paragraph(q, trace, named) == named
    # nothing measured as weak is said, not guessed
    trace = [ToolCallRecord("get_card_verdicts", {}, {"found": True, "strong": [], "weak": []})]
    assert chat._verdict_paragraph(q, trace, "x").startswith("No card in the deck measured as weak.")


def test_measured_swaps_reads_only_its_own_axis_from_a_mixed_auto_search():
    """A fallback auto search carries swaps for several axes; the mentor asked about clock must
    see only the clock swap, on the clock baseline, never the resilience one."""
    from mythgauntlet.mentor import tools
    result = {"axis": "ceiling", "axis_label": "Ceiling", "baseline": 31.0, "evaluated": 16,
              "min_delta": 1.6, "suggestions": [
                  {"add": "Flusterstorm", "cut": "Controvert", "axis": "resilience",
                   "axis_label": "Resilience", "before": 61.0, "after": 67.0, "delta": 6.0,
                   "brief": None},
                  {"add": "Skullclamp", "cut": "Rewind", "axis": "clock", "axis_label": "Clock",
                   "before": 24.4, "after": 26.0, "delta": 1.6, "brief": None}]}
    ctx = SimpleNamespace(advice={"auto": {"result": result, "computed_at": "now"}})
    clock = tools.tool_get_measured_swaps(ctx, "clock").data
    assert clock["available"] and [s["add"] for s in clock["suggestions"]] == ["Skullclamp"]
    assert clock["axis"] == "clock" and clock["baseline"] == 24.4
    ceiling = tools.tool_get_measured_swaps(ctx, "ceiling").data
    assert ceiling["available"] and ceiling["improving_swap_found"] is False


def test_a_stated_commander_identity_must_be_its_identity():
    b = gate.ClaimBudget(commander_names=frozenset({"Smaug the Impenetrable"}),
                         identities=(("Smaug the Impenetrable", frozenset("BR")),))
    wrong = ("Both Dauthi Voidwalker and Smaug the Impenetrable are legal and share the same "
             "color identity, which is black.")
    assert gate.identity_reasons(wrong, b)
    for ok in ("Your commander, Smaug the Impenetrable, has a color identity of black and red.",
               "Red is part of your commander's color identity, so Lightning Bolt is legal.",
               "Lightning Bolt has a color identity of red."):
        assert gate.identity_reasons(ok, b) == []


def test_a_measured_role_swap_is_the_swap_answer_even_when_none_cleared():
    """2026-11-10: 'no measured role swap for draw' was followed by a second quick search on an
    axis the model picked, and the reply reported 'no improvement for speed'."""
    rec = ToolCallRecord("suggest_role_swap", {}, {"role_swap_found": False, "pairs_measured": 6})
    assert chat._has_swap_answer([rec])
    assert chat._owed_fallback_axes("what should I cut?", [rec]) == []
