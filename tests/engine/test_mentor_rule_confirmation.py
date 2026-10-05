"""Gate check 14 + the asked-rule prefetch (2026-10-05): a reply must not confirm the player's
rule number when a retrieved sibling's text is the one that says what the question describes."""
from __future__ import annotations

from types import SimpleNamespace

from mythgauntlet.mentor import chat, gate
from mythgauntlet.mentor.tools import ToolResult

# Real CR text (trimmed), as the corpus holds it.
RULES = {
    "603.3": ("Once an ability has triggered, its controller puts it on the stack as an object "
              "that's not a card the next time a player would receive priority."),
    "603.3a": ("A triggered ability is controlled by the player who controlled its source at the "
               "time it triggered, unless it's a delayed triggered ability."),
    "603.3d": ("The remainder of the process for putting a triggered ability on the stack is "
               "identical to the process for casting a spell listed in rules 601.2c-d."),
    "704.5": "The state-based actions are as follows:",
    "704.5c": "If a player has ten or more poison counters, that player loses the game.",
    "704.5f": ("If a creature has toughness 0 or less, it's put into its owner's graveyard. "
               "Regeneration can't replace this event."),
}

Q_603 = ("Doesn't the rule about a triggered ability waiting for the next time a player would "
         "get priority live at exactly 603.3d?")
Q_704 = "Under exactly which rule number does a 0-toughness creature go to the graveyard -- is it 704.5c?"


def _budget(*numbers):
    results = [ToolResult(data={"found": True, "number": n, "text": RULES[n]},
                          rule_numbers=frozenset({n})) for n in numbers]
    return gate.ClaimBudget.from_tool_results(results)


def _check14(text, question, budget):
    return gate._unsupported_rule_confirmation_reasons(text, question, budget.rule_texts)


def test_the_live_603_3d_confirmation_is_flagged():
    reply = ("You're absolutely correct. Based on the tool results, **rule 603.3d** is the one "
             "that directly addresses the process of putting a triggered ability on the stack.")
    reasons = _check14(reply, Q_603, _budget("603.3", "603.3a", "603.3d"))
    assert len(reasons) == 1 and "603.3's text does" in reasons[0]
    assert any("603.3d" in r for r in gate.check(reply, _budget("603.3", "603.3a", "603.3d"),
                                                 question=Q_603))


def test_a_bare_affirmation_without_an_opener_is_flagged():
    reply = "Rule 704.5c is the rule: the creature is put into its owner's graveyard."
    assert _check14(reply, Q_704, _budget("704.5", "704.5c", "704.5f"))


def test_correcting_the_player_passes():
    budget = _budget("603.3", "603.3a", "603.3d")
    for reply in (
        "No -- that's rule 603.3. Rule 603.3d covers the rest of the process, which matches casting a spell.",
        "It isn't 603.3d. Rule 603.3 says the ability goes on the stack the next time a player would receive priority.",
        "The rule is **704.5f**, which states that a creature with toughness 0 or less is put into its owner's graveyard.",
    ):
        q = Q_704 if "704" in reply else Q_603
        b = _budget("704.5", "704.5c", "704.5f") if "704" in reply else budget
        assert _check14(reply, q, b) == [], reply


LIVE_CORRECTION = (
    "You're correct. The rule about a triggered ability waiting for the next time a player would "
    "get priority is not found in **603.3d**. Instead, this behavior is described in **603.3**, "
    "which states that once an ability has triggered, its controller puts it on the stack as an "
    "object that's not a card the next time a player would receive priority.")


def test_a_correction_that_opens_by_agreeing_is_check_12s_not_check_14s():
    # Live 2026-10-05: check 14 rejected this three times (it read "not found in 603.3d" as a
    # confirmation) and the turn fell back. It IS a correction -- but its "You're correct" opener
    # reads to a player as confirming 603.3d, which check 12 asks to lead with the correction.
    budget = _budget("603.3", "603.3a", "603.3d")
    assert _check14(LIVE_CORRECTION, Q_603, budget) == []
    reasons = gate._affirmed_wrong_rule_reasons(LIVE_CORRECTION, Q_603)
    assert len(reasons) == 1 and "No, it isn't 603.3d" in reasons[0]


def test_negations_around_the_number_count_as_dismissals():
    for s in ("It is **not** found in 603.3d.", "It isn't 603.3d.", "Not 603.3d, but 603.3.",
              "Rule 603.3d does not address this timing.", "603.3d isn't the one."):
        assert gate._rule_dismissed(s, "603.3d"), s
    for s in ("Rule 603.3d is the one.", "Yes, 603.3d covers it.",
              "Rule 603.3d says it waits; the ability does not resolve at once."):
        assert not gate._rule_dismissed(s, "603.3d"), s
    # "not 603.3d" must not dismiss the parent rule 603.3.
    assert not gate._rule_dismissed("Not 603.3d -- 603.3 is the one.", "603.3")


def test_a_clean_correction_passes_both_checks():
    reply = ("No, it isn't 603.3d; it's **603.3**. Rule 603.3 says a triggered ability goes on the "
             "stack the next time a player would receive priority.")
    budget = _budget("603.3", "603.3a", "603.3d")
    assert _check14(reply, Q_603, budget) == []
    assert gate._affirmed_wrong_rule_reasons(reply, Q_603) == []


def test_confirming_a_rule_that_really_says_it_passes():
    q = "Is the 0-toughness rule 704.5f?"
    assert _check14("Yes, 704.5f is the one: toughness 0 or less goes to the graveyard.",
                    q, _budget("704.5", "704.5c", "704.5f")) == []


def test_no_sibling_text_in_hand_means_no_verdict():
    # Only the asked rule was retrieved: nothing to compare against, so the check stays silent
    # (the prefetch is what puts the siblings in hand).
    reply = "You're absolutely correct, rule 603.3d is the one."
    assert _check14(reply, Q_603, _budget("603.3d")) == []


def test_budget_collects_rule_text_from_search_results_too():
    res = ToolResult(data={"results": [{"kind": "rule", "ref": "704.5f", "text": RULES["704.5f"]},
                                       {"kind": "glossary", "ref": "Dies", "text": "x"}]})
    assert dict(gate.ClaimBudget.from_tool_results([res]).rule_texts) == {"704.5f": RULES["704.5f"]}


def test_prefetch_fetches_the_asked_rule_family_before_the_model_answers():
    cr = SimpleNamespace(rules=dict(RULES), get_rule=RULES.get)
    ctx = SimpleNamespace(cr=cr)
    trace, results, messages = [], [], []
    calls = []

    def fake_call_tool(_ctx, name, args):
        calls.append((name, args["number"]))
        return ToolResult(data={"found": True, "number": args["number"], "text": RULES[args["number"]]},
                          rule_numbers=frozenset({args["number"]}))

    orig = chat.call_tool
    chat.call_tool = fake_call_tool
    try:
        fetched = chat._prefetch_question_rules(ctx, Q_603, trace, results, messages)
    finally:
        chat.call_tool = orig
    assert fetched == ["603.3", "603.3a", "603.3d"]
    assert messages[0]["tool_calls"][0]["id"].startswith("auto-q-rule-")
    assert {n for _, n in calls} == {"603.3", "603.3a", "603.3d"}


def test_prefetch_is_a_no_op_without_a_rule_number():
    ctx = SimpleNamespace(cr=SimpleNamespace(rules=dict(RULES)))
    assert chat._prefetch_question_rules(ctx, "What does Sol Ring do?", [], [], []) == []
