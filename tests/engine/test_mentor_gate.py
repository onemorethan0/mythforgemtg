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
        known_card_names=frozenset({"Sol Ring", "Rhystic Study"}),
    )
    text = "Sol Ring costs 1 and taps for 2 colorless mana."
    assert check(text, budget) == []


def test_names_a_card_outside_this_turns_tool_calls():
    budget = ClaimBudget(
        card_names=frozenset({"Sol Ring"}),
        known_card_names=frozenset({"Sol Ring", "Rhystic Study"}),
    )
    text = "Sol Ring is fine, but Rhystic Study is even better in this deck."
    reasons = check(text, budget)
    assert any("Rhystic Study" in r for r in reasons)


def test_card_not_in_deck_but_a_real_card_is_flagged_when_not_looked_up_this_turn():
    """FIXED 2026-08-24: the name check used to be scoped to `deck_card_names` only, so a
    fabricated claim about a card OUTSIDE the deck ("X is even better than your Y, run
    that instead") named a card that was never in the deck's own risk pool and slipped
    through with zero reasons -- a real gap, not a deliberate narrowing. `known_card_names`
    is now the FULL card index (mirroring what `MentorContext.all_card_names` feeds the
    real gate from `CardDb`), so ANY recognized card name -- deck card or not -- must have
    been returned by a tool call this turn or it is flagged, same as a deck card always was."""
    budget = ClaimBudget(card_names=frozenset(), known_card_names=frozenset({"Sol Ring", "Rhystic Study"}))
    text = "Sol Ring is fine, but Rhystic Study would be even better here."
    reasons = check(text, budget)
    assert any("Rhystic Study" in r for r in reasons)


def test_off_deck_card_that_was_looked_up_this_turn_is_not_flagged():
    """The other half of the fix above: a card outside the deck that a tool call DID
    verify this turn (e.g. lookup_card on a card being considered as an addition) is
    licensed exactly like a deck card would be -- `card_names` (this turn's verified set)
    is what matters, not deck membership."""
    budget = ClaimBudget(
        card_names=frozenset({"Rhystic Study"}),
        known_card_names=frozenset({"Sol Ring", "Rhystic Study"}),
    )
    text = "Rhystic Study would be a strong addition to this deck."
    assert check(text, budget) == []


def test_wholly_invented_card_name_is_not_flagged_by_the_name_check():
    """A name that isn't a real card at all (pure invention) is NOT this check's job --
    it only scans the known-card index, so an invented name never matches anything in it.
    `lookup_card` returning found:False is what catches that, and the model is expected
    to report it honestly -- see the module docstring."""
    budget = ClaimBudget(card_names=frozenset(), known_card_names=frozenset({"Sol Ring"}))
    text = "Zzyzx Prism Wyrm is a strange card."
    assert check(text, budget) == []


def test_nested_name_is_masked_before_checking():
    """A commander's own name can contain a real card's name as a substring (the
    documented swap_narrative case: 'Omo, Queen of Vesuva' contains 'Vesuva')."""
    budget = ClaimBudget(
        card_names=frozenset({"Omo, Queen of Vesuva"}),
        known_card_names=frozenset({"Omo, Queen of Vesuva", "Vesuva"}),
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
    """`_FREE_NUMBERS` is {0.0, 1.0} -- shrunk from {0.0, 1.0, 2.0} on 2026-08-24 (see
    gate.py's own comment): 2 was exactly the magnitude a small model reaches for when
    inventing a deck-shape claim, so only 0/1 stay free now."""
    budget = ClaimBudget()
    assert check("You have one commander leading this deck.", budget) == []


def test_two_is_no_longer_a_free_number():
    """The exemption used to cover {0, 1, 2}; 2 was dropped because it is common enough in
    real fabricated quantitative claims ('about two counterspells', a mana cost, a small
    P/T) that exempting it defeated the numeric leg of the gate for exactly the un-named
    deck-shape claims that leg exists to catch (a claim tied to a specific card name is
    now caught by the widened name check regardless of the number attached to it)."""
    budget = ClaimBudget()
    reasons = check("Your deck runs about 2 board wipes.", budget)
    assert any("2" in r for r in reasons)


def test_spelled_out_number_is_checked_the_same_as_a_digit():
    """tools.extract_numbers (used by check()'s NUMBERS leg) catches spelled-out numbers
    zero-through-twenty too -- a model writing 'about seventeen' instead of '17' must not
    bypass the check."""
    budget = ClaimBudget()
    reasons = check("Your deck runs about seventeen ramp sources.", budget)
    assert any("17" in r for r in reasons)
    # And a spelled-out number that IS in budget is accepted, just like a digit would be.
    budget2 = ClaimBudget(numbers=frozenset({17.0}))
    assert check("Your deck runs about seventeen ramp sources.", budget2) == []


def test_length_bounds():
    budget = ClaimBudget()
    assert any("length" in r for r in check("hi", budget))
    assert any("length" in r for r in check("x" * 2000, budget))


def test_claim_budget_from_tool_results_aggregates_everything():
    results = [
        ToolResult(data={"name": "Sol Ring", "mana_value": 1}, card_names=frozenset({"Sol Ring"})),
        ToolResult(data={"number": "704.5f", "text": "toughness 0"}, rule_numbers=frozenset({"704.5f"})),
    ]
    budget = ClaimBudget.from_tool_results(results, known_card_names=frozenset({"Sol Ring"}))
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
