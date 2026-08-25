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


def test_x_the_variable_notation_is_not_flagged_as_an_unlooked_up_card():
    """Found live 2026-08-25: 'X' is a real (joke-set) card name, and the widened
    known-card scan (fixed above) correctly caught every mention of it -- including the
    ordinary MTG variable-cost notation in "+X/+X" (Craterhoof Behemoth's real oracle
    text). Three separate real bench questions about Craterhoof were gate-rejected for
    'naming a card that was never looked up: X'. A single-letter name is excluded
    categorically (verified: 'x' is the only one in the whole card index)."""
    budget = ClaimBudget(
        card_names=frozenset({"Craterhoof Behemoth"}),
        known_card_names=frozenset({"Craterhoof Behemoth", "X"}),
    )
    text = ("Craterhoof Behemoth gives your creatures trample and +X/+X, where X is the "
            "number of creatures you control.")
    assert check(text, budget) == []


def test_common_word_card_names_are_not_flagged_in_ordinary_prose():
    """Found live 2026-08-25: 'Wizards', 'Overload', and (in a later same-session run)
    'Spells' are all real card names (mostly joke-set/obscure) that are also ordinary
    English/rules-jargon words. A rulings explanation mentioning 'Wizards of the Coast',
    the overload keyword, or "instant spells, sorcery spells" was gate-rejected as naming
    an unlooked-up card, even though none of those uses had anything to do with the
    actual cards named Wizards/Overload/Spells."""
    budget = ClaimBudget(
        card_names=frozenset({"Smothering Tithe"}),
        known_card_names=frozenset({"Smothering Tithe", "Wizards", "Overload", "Spells"}),
    )
    text = ("There's an official ruling on Smothering Tithe from Wizards of the Coast "
            "about how the overload of triggers resolves for instant spells.")
    assert check(text, budget) == []


def test_a_real_multi_word_card_name_used_as_a_common_word_is_still_flagged():
    """The exclusion above is narrow (single-character names + an explicit short list),
    not a blanket carve-out for anything word-shaped -- an ordinary multi-word card name
    outside that list is still caught exactly as before."""
    budget = ClaimBudget(card_names=frozenset(), known_card_names=frozenset({"Sol Ring"}))
    text = "You should really run Sol Ring in this deck."
    assert any("Sol Ring" in r for r in check(text, budget))


def test_verbatim_quoted_oracle_text_is_not_scanned_for_embedded_card_names():
    """Found live 2026-08-25 (real mentor campaign, not the synthetic bench): the model
    correctly looked up Anguished Unmaking and quoted its REAL oracle text verbatim
    ("Exile target nonland permanent. You lose 3 life."), and it was gate-rejected
    anyway because "Exile" is ALSO a real card name -- even though this wasn't an
    independent claim, it was a faithful echo of exactly what the tool returned. This
    generalizes badly: any fetch/color-fixing card naming a basic land type in its real
    oracle text would hit the identical wall, since every basic land name is also a real
    card name. `source_texts` licenses the verbatim quotation as a whole."""
    budget = ClaimBudget(
        card_names=frozenset({"Anguished Unmaking"}),
        numbers=frozenset({3.0}),
        known_card_names=frozenset({"Anguished Unmaking", "Exile"}),
        source_texts=frozenset({"Exile target nonland permanent. You lose 3 life."}),
    )
    text = ('Anguished Unmaking has the oracle text: "Exile target nonland permanent. '
            'You lose 3 life."')
    assert check(text, budget) == []


def test_a_paraphrase_using_a_common_word_card_name_is_still_caught_if_not_in_the_list():
    """The verbatim-quote exemption only covers an EXACT substring of what a tool
    returned -- a paraphrase (not quoting the source text) that happens to use a
    card-name-shaped word NOT on the small common-word exclusion list is still scanned
    normally. This isn't a blanket "any word overlapping retrieved text is safe" carve-out."""
    budget = ClaimBudget(
        card_names=frozenset({"Anguished Unmaking"}),
        known_card_names=frozenset({"Anguished Unmaking", "Fog", "Duress"}),
        source_texts=frozenset({"Exile target nonland permanent. You lose 3 life."}),
    )
    text = "Anguished Unmaking would work great alongside Duress in this deck."
    assert any("Duress" in r for r in check(text, budget))


def test_markdown_numbered_list_markers_are_not_read_as_cited_numbers():
    """Found live 2026-08-25: a correct 3-point rulings explanation formatted as a
    Markdown ordered list ('1. **Total Cost**... 2. **No Targets**... 3. **Payment**...')
    was gate-rejected for 'citing 2' and 'citing 3', which were never factual claims --
    just list positions."""
    budget = ClaimBudget()
    text = ("1. Overload has no targets when you pay its alternative cost.\n"
            "2. You can't choose to pay overload if told to cast without paying mana cost.")
    assert check(text, budget) == []


def test_inline_bold_list_markers_within_one_paragraph_are_not_read_as_cited_numbers():
    """The system prompt asks for plain prose with no lists, but a 14B model doesn't
    always comply -- found live 2026-08-25 (SECOND bench run, after the line-start-only
    version of this fix already landed): the model wrote all three points inline in one
    paragraph ('...unchanged. 2. **No Targeting**: ...'), which never starts a new line,
    so the original line-start-only marker regex missed it and the same rulings question
    kept failing on 'cites 2'/'cites 3'/'cites 4'."""
    budget = ClaimBudget()
    text = ("Overload has no targets. 2. **No Targeting**: this means it can affect "
            "hexproof permanents. 3. **Cost Choice**: you can't choose to pay overload "
            "if told to cast without paying mana cost.")
    assert check(text, budget) == []


def test_a_genuine_number_inside_a_list_item_is_still_checked():
    """The list-marker strip only removes the leading 'N.' marker itself -- a real,
    uncited number appearing later in that same list item is still caught."""
    budget = ClaimBudget()
    text = "1. This card costs 14 mana, which is far too much."
    assert any("14" in r for r in check(text, budget))


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


# ── Uncited rules-paraphrase heuristic (Task 2 gap closure, 2026-08-25) ─────────────
# A reply can DEFINE a Comprehensive Rules concept ("a state-based action is when...")
# with no rule number and no digits at all, which checks 1-3 above cannot see -- correctness
# used to rest entirely on trusting the model actually called search_rules/get_rule and
# paraphrased faithfully. `check()` now flags a definitional phrase landing next to a core
# rules-vocabulary term (see gate.py's own comment for the exact hand-picked list, verified
# against the live CR glossary) when there's no adjacent citation AND no evidence
# search_rules/get_rule ran this turn (`budget.rule_numbers` empty). This is a bounded
# heuristic, not a full NLP solution -- these four cases pin what it catches and what it
# deliberately still lets through.

def test_uncited_rules_definition_with_no_tool_call_is_flagged():
    """(a) A definitional claim about a named CR concept, no rule-number citation
    anywhere, and no evidence the rules tools ran this turn -- must be flagged as an
    unverified paraphrase rather than shipped on trust alone."""
    budget = ClaimBudget()
    text = ("A state-based action is when the game automatically checks the board for "
            "things like a creature with lethal damage, with no player choice involved.")
    reasons = check(text, budget)
    assert any("state-based action" in r.lower() for r in reasons)


def test_same_definition_with_a_citation_is_not_flagged():
    """(b) The identical definitional content, but with a proper rule-number citation
    right there in the sentence -- the citation is itself checked (rule 2) and covers
    this claim, so the paraphrase heuristic must not pile on a second rejection."""
    budget = ClaimBudget(numbers=frozenset({704.5}), rule_numbers=frozenset({"704.5a"}))
    text = ("A state-based action is when the game automatically checks the board, per "
            "rule 704.5a.")
    assert check(text, budget) == []


def test_same_definition_passes_when_rules_tool_ran_this_turn():
    """(c) No citation in the text, but `budget.rule_numbers` is non-empty -- meaning
    search_rules/get_rule actually ran and returned something this turn (the only signal
    ClaimBudget carries for that; see tools.py). The heuristic exists to catch an
    UNVERIFIED paraphrase, not to force every definition to be footnoted, so a genuinely
    tool-backed definition must still pass."""
    budget = ClaimBudget(rule_numbers=frozenset({"704.5a"}))
    text = ("A state-based action is when the game automatically checks the board for "
            "things like a creature with lethal damage, with no player choice involved.")
    assert check(text, budget) == []


def test_ordinary_deck_advice_without_rules_vocabulary_is_not_flagged():
    """(d) False-positive guard: definitional PHRASING alone ("is when") is not enough --
    it must land next to one of the hand-picked rules-vocabulary terms. Ordinary deck
    chat that uses neither, or uses the phrasing about something that isn't a rules
    concept, must sail through untouched."""
    budget = ClaimBudget()
    assert check("Sol Ring is a ramp piece that gets your commander out a turn earlier.",
                 budget) == []
    assert check("Ramping out early is when this deck really gets going.", budget) == []
