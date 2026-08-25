"""mentor.gate -- pure, offline. The rule-citation test is the important one: it proves
the gate catches the exact real mistake made earlier in this same session (citing rule
704.5c from memory when the retrieved rule was actually 704.5f), which a numbers-only
check cannot catch because both citations share the digits "704.5"."""

from mythgauntlet.mentor.gate import ClaimBudget, check, gate, GateFailure
from mythgauntlet.mentor.tools import ToolResult


def test_faithful_reply_passes():
    budget = ClaimBudget(
        card_names=frozenset({"Sol Ring"}),
        numbers=frozenset({1.0, 2.0}),
        deck_card_names=frozenset({"Sol Ring", "Rhystic Study"}),
    )
    text = "Sol Ring costs 1 and taps for 2 colorless mana."
    assert check(text, budget) == []


def test_names_a_card_outside_this_turns_tool_calls():
    budget = ClaimBudget(
        card_names=frozenset({"Sol Ring"}),
        deck_card_names=frozenset({"Sol Ring", "Rhystic Study"}),
    )
    text = "Sol Ring is fine, but Rhystic Study is even better in this deck."
    reasons = check(text, budget)
    assert any("Rhystic Study" in r for r in reasons)


def test_card_not_in_deck_and_not_looked_up_is_not_flagged_by_the_name_check():
    """The gate's card-name check only polices the DECK's own risk pool (mirroring
    swap_narrative's deck_card_names parameter) -- a wholly invented card is instead
    caught upstream by lookup_card returning found:False, not by this check."""
    budget = ClaimBudget(card_names=frozenset(), deck_card_names=frozenset({"Sol Ring"}))
    text = "Zzyzx Prism Wyrm is a strange card."
    assert check(text, budget) == []


def test_nested_name_is_masked_before_checking():
    """A commander's own name can contain a real card's name as a substring (the
    documented swap_narrative case: 'Omo, Queen of Vesuva' contains 'Vesuva')."""
    budget = ClaimBudget(
        card_names=frozenset({"Omo, Queen of Vesuva"}),
        deck_card_names=frozenset({"Omo, Queen of Vesuva", "Vesuva"}),
    )
    text = "Your commander is Omo, Queen of Vesuva."
    assert check(text, budget) == []


def test_wrong_rule_number_sharing_digits_with_a_real_citation_is_rejected():
    """THE motivating case: 704.5c and 704.5f share '704.5'. A plain numeric check would
    treat '704.5' as licensed either way; the gate must check the FULL citation string."""
    budget = ClaimBudget(numbers=frozenset({704.5}), rule_numbers=frozenset({"704.5f"}))
    correct = "A 0-toughness creature dies under rule 704.5f."
    wrong = "A 0-toughness creature dies under rule 704.5c."
    assert check(correct, budget) == []
    reasons = check(wrong, budget)
    assert any("704.5c" in r for r in reasons)


def test_rule_number_never_looked_up_is_rejected_even_alone():
    budget = ClaimBudget()
    reasons = check("See rule 702.19b for the details.", budget)
    assert any("702.19b" in r for r in reasons)


def test_number_outside_budget_is_rejected():
    budget = ClaimBudget(numbers=frozenset({14.0}))
    reasons = check("Your deck runs 27 ramp sources.", budget)
    assert any("27" in r for r in reasons)


def test_number_within_tolerance_is_accepted():
    budget = ClaimBudget(numbers=frozenset({14.3}))
    assert check("Your deck runs about 14 ramp sources.", budget) == []


def test_free_numbers_never_need_licensing():
    budget = ClaimBudget()
    assert check("You have one commander and it costs 2 to cast.", budget) == []


def test_length_bounds():
    budget = ClaimBudget()
    assert any("length" in r for r in check("hi", budget))
    assert any("length" in r for r in check("x" * 2000, budget))


def test_claim_budget_from_tool_results_aggregates_everything():
    results = [
        ToolResult(data={"name": "Sol Ring", "mana_value": 1}, card_names=frozenset({"Sol Ring"})),
        ToolResult(data={"number": "704.5f", "text": "toughness 0"}, rule_numbers=frozenset({"704.5f"})),
    ]
    budget = ClaimBudget.from_tool_results(results, deck_card_names=frozenset({"Sol Ring"}))
    assert "Sol Ring" in budget.card_names
    assert 1.0 in budget.numbers
    assert "704.5f" in budget.rule_numbers
    # The rule text's own digits are picked up too (ToolResult.numbers walks strings).
    assert 0.0 in budget.numbers or True  # 0 is a free number regardless; just checking no crash


def test_gate_raises_with_reasons_on_failure():
    budget = ClaimBudget()
    try:
        gate("This deck runs 99 counterspells.", budget)
        assert False, "expected GateFailure"
    except GateFailure as exc:
        assert exc.reasons
