"""Gate check 9: a looked-up card given a card type its own type line lacks.

Found 2026-10-01 in a live mentor_bench trap reply: "Sol Ring is a non-basic land, so you can
only run one copy" -- Sol Ring was legitimately looked up (name licensed), the TYPE was invented.
"""

from mythgauntlet.mentor import gate, verdicts
from mythgauntlet.mentor.tools import ToolResult

SOL_RING = ("Sol Ring", "Artifact")
SWORDS = ("Swords to Plowshares", "Instant")
TITHE = ("Smothering Tithe", "Enchantment")
DRYAD = ("Dryad Arbor", "Land Creature — Forest Dryad")
SOLEMN = ("Solemn Simulacrum", "Artifact Creature — Golem")


def _reasons(text, *cards):
    return verdicts.type_claim_reasons(text, cards)


def test_the_live_sol_ring_land_claim_is_flagged():
    r = _reasons("Sol Ring is a non-basic land, so you can only run one copy.", SOL_RING)
    assert len(r) == 1 and "Sol Ring" in r[0] and "land" in r[0]


def test_appositive_wrong_type_is_flagged():
    assert _reasons("Swords to Plowshares, a cheap sorcery, exiles a creature.", SWORDS)


def test_correct_types_pass():
    assert not _reasons("Sol Ring is a colorless artifact.", SOL_RING)
    assert not _reasons("Swords to Plowshares is an instant.", SWORDS)
    assert not _reasons("Smothering Tithe is an enchantment that makes Treasure.", TITHE)
    assert not _reasons("Solemn Simulacrum is an artifact creature.", SOLEMN)
    assert not _reasons("Solemn Simulacrum is a creature, and it ramps.", SOLEMN)


def test_multi_type_cards_accept_either_type():
    assert not _reasons("Dryad Arbor is a land.", DRYAD)
    assert not _reasons("Dryad Arbor is a creature, so it dies to wipes.", DRYAD)


def test_attributive_uses_never_fire():
    # the type word does not end the noun phrase -> not a type claim about the card itself
    assert not _reasons("Swords to Plowshares is a creature removal spell.", SWORDS)
    assert not _reasons("Swords to Plowshares is an instant-speed answer.", SWORDS)
    assert not _reasons("Sol Ring is a land-light deck's best friend.", SOL_RING)


def test_unrelated_cards_and_unlooked_up_cards_are_ignored():
    assert not _reasons("Your deck has 36 lands and Sol Ring.", SOL_RING)
    # a card not in card_types is not this check's business
    assert not _reasons("Cultivate is a land.", SOL_RING)


def test_gate_wires_lookup_card_results_into_check_9():
    lookup = ToolResult(
        data={"found": True, "name": "Sol Ring", "mana_cost": "{1}", "mana_value": 1,
              "type_line": "Artifact", "oracle_text": "{T}: Add {C}{C}.",
              "color_identity": [], "commander_legal": True, "game_changer": True,
              "edhrec_rank": 1},
        card_names=frozenset({"Sol Ring"}))
    budget = gate.ClaimBudget.from_tool_results([lookup])
    assert budget.card_types == (("Sol Ring", "Artifact"),)
    bad = gate.check("Sol Ring is a non-basic land, so you can only run one copy.", budget)
    assert any("calls 'Sol Ring' a land" in r for r in bad)
    good = gate.check("Sol Ring is an artifact that adds two colorless mana.", budget)
    assert not any("calls 'Sol Ring'" in r for r in good)


def test_a_name_licensed_by_another_tool_still_gets_its_real_type():
    # Live 2026-10-01: the turn licensed Sol Ring via check_legality (no type_line in its result),
    # so check 9 had nothing to compare against and "Sol Ring is a non-basic land" passed.
    from types import SimpleNamespace
    from mythgauntlet.mentor import chat

    legality = ToolResult(
        data={"found": True, "card": "Sol Ring", "card_color_identity": [],
              "deck_color_identity": ["B", "G"], "legal": True, "colors_not_in_deck_identity": []},
        card_names=frozenset({"Sol Ring"}))
    budget = gate.ClaimBudget.from_tool_results([legality])
    assert budget.card_types == ()
    db = {"Sol Ring": SimpleNamespace(type_line="Artifact")}
    ctx = SimpleNamespace(card_db=SimpleNamespace(get=db.get))
    budget = chat._with_card_types(budget, ctx)
    assert budget.card_types == (("Sol Ring", "Artifact"),)
    bad = gate.check("Since Sol Ring is a non-basic land, you can only run one copy.", budget)
    assert any("calls 'Sol Ring' a land" in r for r in bad)


def test_singleton_contradiction_is_flagged():
    # the live reply once the type was fixed (2026-10-01)
    for text in ("Sol Ring is not a land, it's an artifact. Therefore, you can run multiple "
                 "copies of Sol Ring in your deck if you choose to do so.",
                 "You could include two copies of Cultivate for consistency.",
                 "Running more than one copy of Rhystic Study is a fine idea."):
        assert verdicts.singleton_reasons(text), text


def test_singleton_correct_statements_pass():
    for text in ("You can only run one copy of Sol Ring, because Commander is singleton.",
                 "You cannot run two copies of Sol Ring.",
                 "You can run multiple copies of basic lands like Forest.",
                 "Your deck can't have more than one copy of a non-basic card.",
                 "Sol Ring is an artifact with mana value 1."):
        assert not verdicts.singleton_reasons(text), text


def test_singleton_exception_cards_are_exempt():
    text = "You can run multiple copies of Relentless Rats in this deck."
    assert verdicts.singleton_reasons(text)                       # unknown exception -> flagged
    assert not verdicts.singleton_reasons(text, {"Relentless Rats"})


def test_gate_learns_exceptions_from_tool_results():
    rats = ToolResult(
        data={"found": True, "name": "Relentless Rats", "type_line": "Creature — Rat",
              "oracle_text": "Relentless Rats gets +1/+1 for each other creature on the battlefield "
                             "named Relentless Rats.\nA deck can have any number of cards named "
                             "Relentless Rats."},
        card_names=frozenset({"Relentless Rats"}))
    budget = gate.ClaimBudget.from_tool_results([rats])
    assert budget.copy_exception_names == frozenset({"Relentless Rats"})
    reasons = gate.check("You can run multiple copies of Relentless Rats in this deck.", budget)
    assert not any("singleton" in r for r in reasons)


def test_question_card_detection_skips_names_embedded_in_a_fake_card():
    # live 2026-10-01: "Quantum Flux Behemoth" (a trap) contains the real card "Flux"
    from mythgauntlet.mentor import chat
    names = frozenset({"Flux", "Void", "Sol Ring", "Craterhoof Behemoth", "Cyclonic Rift",
                       "Exile", "Rhystic Study"})
    q = chat._question_card_names
    assert q("What does the card Quantum Flux Behemoth do?", names) == []
    assert q("Can you explain the ability on Nebulous Void Chancellor?", names) == []
    assert q("What does Sol Ring actually do?", names) == ["Sol Ring"]
    assert q("What do the rulings say about Craterhoof Behemoth's trigger?", names) == [
        "Craterhoof Behemoth"]
    assert q("Given that Rhystic Study is a Sorcery, when do I cast it?", names) == ["Rhystic Study"]
    assert q("Should I exile it with Cyclonic Rift?", names) == ["Cyclonic Rift"]  # 'exile' common


def test_a_fraction_licenses_its_percent_form():
    from mythgauntlet.mentor.tools import _numbers_in
    found = _numbers_in({"consistency": 0.78, "rate": 1.0, "count": 3})
    assert 78.0 in found and 0.8 in found
    assert 100.0 not in found          # an integer-valued 1.0 is not a fraction


def test_an_unresolvable_name_is_left_out_rather_than_guessed():
    from types import SimpleNamespace
    from mythgauntlet.mentor import chat

    budget = gate.ClaimBudget(card_names=frozenset({"Zzyzx Prism Wyrm"}))
    ctx = SimpleNamespace(card_db=SimpleNamespace(get=lambda name: None))
    assert chat._with_card_types(budget, ctx) is budget
