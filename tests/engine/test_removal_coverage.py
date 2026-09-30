"""Interaction coverage (`mentor/removal.py`): gold set from the REAL card DB + hermetic logic.

The gold rows below were written AFTER reading each card's oracle text out of the live card
DB (2026-09-30), never from memory. They are skipped (not failed) when the DB is unavailable,
like the other data-dependent engine tests; the synthetic section needs nothing and always
runs.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mythgauntlet.mentor import removal

# (name, kind, hits, mode, speed, restrictions)
GOLD = [
    ("Swords to Plowshares", "spot", ["creature"], "exile", "instant", []),
    ("Path to Exile", "spot", ["creature"], "exile", "instant", []),
    ("Beast Within", "spot", ["any_permanent"], "destroy", "instant", []),
    ("Chaos Warp", "spot", ["any_permanent"], "unknown", "instant", []),
    ("Cyclonic Rift", "spot", ["nonland_permanent"], "bounce", "instant",
     ["you don't control", "overload {6}{u}"]),
    ("Damnation", "wipe", ["creature"], "destroy", "sorcery", []),
    ("Blasphemous Act", "wipe", ["creature"], "damage", "sorcery", ["13 damage"]),
    ("Vandalblast", "spot", ["artifact"], "destroy", "sorcery",
     ["you don't control", "overload {4}{r}"]),
    ("Naturalize", "spot", ["artifact", "enchantment"], "destroy", "instant", []),
    ("Counterspell", "counter", ["spell"], "counter", "instant", []),
    ("Negate", "counter", ["spell"], "counter", "instant", ["noncreature"]),
    ("Pongify", "spot", ["creature"], "destroy", "instant", []),
    ("Doom Blade", "spot", ["creature"], "destroy", "instant", ["nonblack"]),
    ("Culling Sun", "wipe", ["creature"], "destroy", "sorcery", ["with mana value 3 or less"]),
    ("Eaten by Spiders", "spot", ["creature"], "destroy", "instant", ["with flying"]),
    ("Skyfisher Spider", "spot", ["nonland_permanent"], "destroy", "sorcery",
     ["sacrifice another creature"]),
    ("Assassin's Trophy", "spot", ["any_permanent"], "destroy", "instant",
     ["an opponent controls"]),
    ("Anguished Unmaking", "spot", ["nonland_permanent"], "exile", "instant", []),
    ("Generous Gift", "spot", ["any_permanent"], "destroy", "instant", []),
    ("Toxic Deluge", "wipe", ["creature"], "minus", "sorcery", ["get -x/-x", "pay x life"]),
    # beyond the required set -- each one a class the parser had to learn
    ("Lightning Bolt", "spot", ["creature", "planeswalker"], "damage", "instant", ["3 damage"]),
    ("Terror", "spot", ["creature"], "destroy", "instant", ["nonartifact", "nonblack"]),
    ("Abrade", "spot", ["creature", "artifact"], "unknown", "instant", ["creature: 3 damage"]),
    ("Royal Assassin", "spot", ["creature"], "destroy", "instant", ["tapped"]),
    ("Condemn", "spot", ["creature"], "unknown", "instant", ["attacking"]),
    ("Tergrid's Shadow", "spot", ["creature"], "sacrifice", "instant", ["each player"]),
    ("Lay Down Arms", "spot", ["creature"], "exile", "sorcery",
     ["with mana value less than or equal to the number of plains you control"]),
    ("Mana Leak", "counter", ["spell"], "counter", "instant",
     ["unless its controller pays {3}"]),
]

# Cards that must NOT produce a row. Each one reads like removal to a verb-only pattern.
NOT_INTERACTION = [
    "Heroic Intervention",  # permanents gain hexproof/indestructible
    "Ephemerate",           # "exile target creature you control, then return it" (tags.py flags it)
    "Flicker",              # exile target nontoken permanent, then return it
    "Momentary Blink",
    "Liberate",
]


def _load_db():
    try:
        from mythgauntlet.data.scryfall import load_card_db

        return load_card_db()
    except Exception as exc:  # store absent / wrong schema: same skip as other data tests
        pytest.skip(f"card DB unavailable: {exc}")


@pytest.fixture(scope="module")
def db():
    return _load_db()


@pytest.mark.parametrize("name,kind,hits,mode,speed,restrictions", GOLD, ids=[g[0] for g in GOLD])
def test_gold_row(db, name, kind, hits, mode, speed, restrictions):
    card = db.get(name)
    assert card is not None, name
    cov = removal.coverage_for_cards([card])
    assert len(cov["cards"]) == 1, cov
    row = cov["cards"][0]
    assert row == {
        "name": card.name, "kind": kind, "hits": hits, "mode": mode, "speed": speed,
        "restrictions": restrictions,
    }


@pytest.mark.parametrize("name", NOT_INTERACTION)
def test_non_interaction_has_no_row(db, name):
    card = db.get(name)
    assert card is not None, name
    assert removal.coverage_for_cards([card])["cards"] == []


def test_object_noun_gates_the_verb(db):
    """The repeated project lesson: 'destroy target' must not sweep Naturalize into creatures."""
    cov = removal.coverage_for_cards(
        [db.get(n) for n in ("Naturalize", "Vandalblast", "Counterspell", "Stone Rain")]
    )
    assert cov["answers_by_type"]["creature"] == []
    assert cov["no_answer_for"] == ["creature", "planeswalker"]
    assert cov["answers_by_type"]["artifact"] == ["Naturalize", "Vandalblast"]
    assert cov["answers_by_type"]["land"] == ["Stone Rain"]
    # a counterspell answers a SPELL, never a permanent type
    assert cov["answers_by_type"]["spell"] == ["Counterspell"]


def test_shelob_deck(db):
    from mythgauntlet.model.deck import Deck, resolve

    path = Path(__file__).resolve().parents[2] / "corpus" / "decks" / "archidekt-1010839.txt"
    if not path.exists():
        pytest.skip("corpus deck not present")
    deck = resolve(Deck.parse_text(path.read_text(encoding="utf-8"), name="shelob"), db)
    cov = removal.coverage(deck)
    names = {r["name"] for r in cov["cards"]}
    # the deck's own plan: flyer-hate, a real nonland answer, and Naturalize-class modes
    assert {"Eaten by Spiders", "Gloomwidow's Feast", "Skyfisher Spider", "Return to Nature"} <= names
    by = {r["name"]: r for r in cov["cards"]}
    assert by["Eaten by Spiders"]["restrictions"] == ["with flying"]
    assert by["Return to Nature"]["hits"] == ["artifact", "enchantment"]
    assert by["Spider Food"]["restrictions"] == ["creature with flying"]
    assert cov["no_answer_for"] == []
    assert "Shelob, Dread Weaver" not in names


# ------------------------------------------------------------------ hermetic (synthetic)


def _c(make_card, name, text, type_line="Instant"):
    return make_card(name, type_line=type_line, oracle_text=text)


def _row(make_card, text, type_line="Instant"):
    cov = removal.coverage_for_cards([_c(make_card, "X", text, type_line)])
    return cov["cards"][0] if cov["cards"] else None


def test_aggregate_answers_and_no_answer_for(make_card):
    cards = [
        _c(make_card, "Kill", "Destroy target creature."),
        _c(make_card, "Smash", "Destroy target artifact."),
        _c(make_card, "Beast", "Destroy target permanent."),
        _c(make_card, "Rift", "Return target nonland permanent to its owner's hand."),
        _c(make_card, "Counter", "Counter target spell."),
        _c(make_card, "Exiler", "Exile target creature or planeswalker."),
    ]
    cov = removal.coverage_for_cards(cards)
    a = cov["answers_by_type"]
    assert a["creature"] == ["Kill", "Beast", "Rift", "Exiler"]
    assert a["artifact"] == ["Smash", "Beast", "Rift"]
    assert a["enchantment"] == ["Beast", "Rift"]
    assert a["planeswalker"] == ["Beast", "Rift", "Exiler"]
    assert a["land"] == ["Beast"]  # any_permanent reaches lands; nonland_permanent does not
    assert a["spell"] == ["Counter"]
    assert cov["no_answer_for"] == []
    assert cov["exile_count"] == 1
    assert cov["instant_speed_count"] == 6


def test_no_answer_for_lists_uncovered_types_and_spell_does_not_count(make_card):
    cov = removal.coverage_for_cards([
        _c(make_card, "Kill", "Destroy target creature."),
        _c(make_card, "Counter", "Counter target spell."),
    ])
    assert cov["no_answer_for"] == ["artifact", "enchantment", "planeswalker"]


def test_commanders_are_included_and_duplicates_collapse(make_card):
    kill = _c(make_card, "Kill", "Destroy target creature.")
    cmdr = make_card("Cmdr", type_line="Legendary Creature — Bear",
                     oracle_text="{T}: Destroy target artifact.")
    resolved = SimpleNamespace(commanders=[cmdr], cards=[(kill, 1), (kill, 1)])
    cov = removal.coverage(resolved)
    assert [r["name"] for r in cov["cards"]] == ["Cmdr", "Kill"]
    assert cov["answers_by_type"]["artifact"] == ["Cmdr"]


def test_empty_deck(make_card):
    cov = removal.coverage_for_cards([make_card("Bear", oracle_text="")])
    assert cov["cards"] == []
    assert cov["no_answer_for"] == ["creature", "artifact", "enchantment", "planeswalker"]
    assert cov["exile_count"] == 0 and cov["instant_speed_count"] == 0


def test_exile_count_includes_mixed_mode_cards(make_card):
    card = _c(make_card, "Charm", "Choose one —\n• Exile target creature.\n• Destroy target artifact.")
    cov = removal.coverage_for_cards([card])
    assert cov["cards"][0]["mode"] == "unknown"  # mixed modes: not guessed
    assert cov["exile_count"] == 1


# ---- speed


def test_speed_rules(make_card):
    assert _row(make_card, "Destroy target creature.")["speed"] == "instant"
    assert _row(make_card, "Destroy target creature.", "Sorcery")["speed"] == "sorcery"
    flash = _row(make_card, "Flash\nWhen this enters, destroy target artifact.", "Creature — Bear")
    assert flash["speed"] == "instant"
    etb = _row(make_card, "When this enters, destroy target artifact.", "Creature — Spider")
    assert etb["speed"] == "sorcery"  # Skyfisher-style ETB
    act = _row(make_card, "{T}, Sacrifice this: Destroy target enchantment.", "Artifact")
    assert act["speed"] == "instant"
    sorc_act = _row(
        make_card, "{T}: Destroy target tapped creature. Activate only as a sorcery.", "Artifact"
    )
    assert sorc_act["speed"] == "sorcery"


def test_planeswalker_loyalty_ability_is_sorcery_speed(make_card):
    row = _row(make_card, "−3: Destroy target creature.", "Legendary Planeswalker — Bob")
    assert row["speed"] == "sorcery"
    row = _row(make_card, "+1: Destroy target creature.", "Legendary Planeswalker — Bob")
    assert row["speed"] == "sorcery"


# ---- clause-by-clause object gating


def test_object_gate_per_clause(make_card):
    assert _row(make_card, "Destroy target artifact or enchantment.")["hits"] == [
        "artifact", "enchantment"]
    assert _row(make_card, "Destroy target land.")["hits"] == ["land"]
    assert _row(make_card, "Exile target nonland permanent.")["hits"] == ["nonland_permanent"]
    assert _row(make_card, "Exile target permanent.")["hits"] == ["any_permanent"]
    # graveyard / card objects are not battlefield interaction
    assert _row(make_card, "Exile target card from a graveyard.") is None
    assert _row(make_card, "Return target creature card from your graveyard to your hand.") is None
    assert _row(make_card, "Exile all creature cards from all graveyards.") is None


def test_noncreature_permanent_expands_to_its_types(make_card):
    row = _row(make_card, "Destroy target noncreature permanent.")
    assert row["hits"] == ["artifact", "enchantment", "planeswalker", "land"]


def test_modifier_list_belongs_to_the_noun(make_card):
    row = _row(make_card, "Destroy target nonartifact, nonblack creature.")
    assert row["hits"] == ["creature"]
    assert row["restrictions"] == ["nonartifact", "nonblack"]


def test_restriction_binds_to_last_alternative(make_card):
    # Spider Food: "with flying" modifies the creature, not the artifact or enchantment
    row = _row(make_card, "Destroy up to one target artifact, enchantment, or creature with flying.",
               "Sorcery")
    assert row["restrictions"] == ["creature with flying"]


def test_modal_union_binds_restrictions_to_their_hits(make_card):
    row = _row(make_card, "Choose one —\n• This deals 3 damage to target player or planeswalker.\n"
                          "• This deals 4 damage to target creature with flying.")
    assert row["hits"] == ["creature", "planeswalker"]
    assert "creature: with flying" in row["restrictions"]
    assert "planeswalker: 3 damage" in row["restrictions"]


def test_quoted_granted_abilities_are_ignored(make_card):
    text = 'Creatures you control have "{T}: Destroy target creature."'
    card = _c(make_card, "Granter", text, "Enchantment")
    assert removal.coverage_for_cards([card])["cards"][0]["mode"] == "unknown"  # tags flags it


def test_own_permanent_and_flicker_are_not_removal(make_card):
    assert _row(make_card, "Exile target creature you control, then return it to the battlefield.") is None
    assert _row(make_card, "Return target creature you control to its owner's hand.") is None
    assert _row(make_card, "This deals 2 damage to target creature you control.") is None
    assert _row(make_card, "Destroy target artifact you control.") is None


def test_conditional_return_is_kept_with_its_catch(make_card):
    row = _row(make_card,
               "Exile target nontoken creature. If the gift wasn't promised, return that card to "
               "the battlefield under its owner's control at the beginning of the next end step.")
    assert row["mode"] == "exile"
    assert any(r.startswith("if the gift wasn't promised") for r in row["restrictions"])


def test_count_expression_control_is_not_an_own_permanent_filter(make_card):
    row = _row(make_card, "Exile target creature with mana value less than or equal to the "
                          "number of Plains you control.", "Sorcery")
    assert row["hits"] == ["creature"]


def test_each_creature_damage_is_a_wipe_and_amount_is_a_restriction(make_card):
    row = _row(make_card, "This deals 2 damage to each creature.", "Sorcery")
    assert row["kind"] == "wipe" and row["hits"] == ["creature"]
    assert row["restrictions"] == ["2 damage"]


def test_minus_needs_toughness_reduction(make_card):
    assert _row(make_card, "All creatures get -2/-0 until end of turn.", "Sorcery") is None
    row = _row(make_card, "All creatures get -2/-2 until end of turn.", "Sorcery")
    assert row["kind"] == "wipe" and row["mode"] == "minus"


def test_edict(make_card):
    row = _row(make_card, "Target opponent sacrifices a creature.", "Sorcery")
    assert row["mode"] == "sacrifice" and row["hits"] == ["creature"] and row["kind"] == "spot"


def test_counterspell_restrictions(make_card):
    row = _row(make_card, "Counter target noncreature spell unless its controller pays {2}.")
    assert row["kind"] == "counter" and row["hits"] == ["spell"]
    assert row["restrictions"] == ["noncreature", "unless its controller pays {2}"]


def test_additional_cost_and_reflexive_gate_are_reported(make_card):
    row = _row(make_card, "As an additional cost to cast this spell, sacrifice a creature.\n"
                          "Destroy target creature an opponent controls.", "Sorcery")
    assert row["restrictions"] == ["an opponent controls", "sacrifice a creature"]
    row = _row(make_card, "When this enters, you may sacrifice another creature. When you do, "
                          "destroy target nonland permanent.", "Creature — Spider")
    assert "sacrifice another creature" in row["restrictions"]


def test_oring_carries_its_return_clause(make_card):
    row = _row(make_card,
               "When this enchantment enters, exile target nonland permanent an opponent controls.\n"
               "When this enchantment leaves the battlefield, return the exiled card to the "
               "battlefield under its owner's control.", "Enchantment")
    assert any("leaves the battlefield, return the exiled card" in r for r in row["restrictions"])


def test_multi_face_text_reads_each_face(make_card):
    card = make_card("Front // Back", type_line="Creature — Bear // Instant",
                     oracle_text="Vigilance\n//\nDestroy target artifact.")
    row = removal.coverage_for_cards([card])["cards"][0]
    assert row["hits"] == ["artifact"] and row["speed"] == "instant"


def test_tags_flagged_but_unparseable_card_is_unknown_not_guessed(make_card):
    card = _c(make_card, "Weird", 'Whenever this attacks, creatures gain "{T}: Destroy target creature."',
              "Creature — Bear")
    row = removal.coverage_for_cards([card])["cards"][0]
    assert row["mode"] == "unknown" and row["hits"] == []


# ---- unrestricted coverage (B2-wiring)

@pytest.mark.parametrize("text,limits", [
    ("an opponent controls", False), ("you don't control", False),
    ("your opponents control", False), ("that player controls", False),
    ("sacrifice a creature", False), ("sacrifice another creature", False),
    ("pay x life", False), ("pay {2}", False), ("discard a card", False),
    ("overload {6}{u}", False), ("cleave {4}{w}", False),
    ("until this enchantment leaves the battlefield", False),
    ("until this creature leaves the battlefield", False),
    ("x damage", False), ("get -x/-x", False), ("13 damage", False), ("get -10/-10", False),
    # limiting
    ("with flying", True), ("without flying", True), ("nonblack", True), ("nonartifact", True),
    ("power 3 or less", True), ("with power 4 or greater", True),
    ("with mana value 3 or less", True), ("tapped", True), ("attacking", True),
    ("nontoken", True), ("noncreature", True), ("3 damage", True), ("get -2/-2", True),
    ("9 damage", True), ("unless its controller pays {3}", True), ("red", True),
    ("if it was kicked", True), ("instant or sorcery", True),
    ("some parser residue we do not understand", True),   # unknown => limiting (under-count)
    ("", True),
])
def test_restriction_limits_targets(text, limits):
    assert removal.restriction_limits_targets(text) is limits


def test_unrestricted_aggregate_separates_restricted_answers(make_card):
    cards = [
        _c(make_card, "Flyer Hate", "Destroy target creature with flying."),
        _c(make_card, "Black Hate", "Destroy target nonblack creature."),
        _c(make_card, "Tax Kill", "As an additional cost to cast this spell, sacrifice a creature.\n"
                                   "Destroy target creature an opponent controls."),
        _c(make_card, "Smash", "Destroy target artifact."),
        _c(make_card, "Bolt", "Bolt deals 3 damage to target creature or planeswalker."),
    ]
    cov = removal.coverage_for_cards(cards)
    assert cov["answers_by_type"]["creature"] == ["Flyer Hate", "Black Hate", "Tax Kill", "Bolt"]
    assert cov["unrestricted_answers_by_type"]["creature"] == ["Tax Kill"]
    assert cov["unrestricted_answers_by_type"]["artifact"] == ["Smash"]
    assert cov["unrestricted_answers_by_type"]["planeswalker"] == []   # Bolt's 3 damage limits it
    # planeswalker is answered (by Bolt) but only under a restriction
    assert "planeswalker" not in cov["no_answer_for"]
    assert cov["no_unrestricted_answer_for"] == ["enchantment", "planeswalker"]


def test_hit_prefixed_restriction_applies_only_to_its_own_hits(make_card):
    card = _c(make_card, "Thunder", "Choose one —\n• Thunder deals 3 damage to target planeswalker.\n"
                                    "• Destroy target artifact.")
    cov = removal.coverage_for_cards([card])
    assert cov["unrestricted_answers_by_type"]["artifact"] == ["Thunder"]
    assert cov["unrestricted_answers_by_type"]["planeswalker"] == []


def test_edicts_and_soft_counters_are_not_unrestricted(make_card):
    cov = removal.coverage_for_cards([
        _c(make_card, "Edict", "Target opponent sacrifices a creature."),
        _c(make_card, "Soft", "Counter target spell unless its controller pays {3}."),
        _c(make_card, "Hard", "Counter target spell."),
    ])
    assert cov["answers_by_type"]["creature"] == ["Edict"]
    assert cov["unrestricted_answers_by_type"]["creature"] == []
    assert cov["unrestricted_answers_by_type"]["spell"] == ["Hard"]


def test_empty_deck_has_no_unrestricted_answers(make_card):
    cov = removal.coverage_for_cards([make_card("Bear", oracle_text="")])
    assert cov["no_unrestricted_answer_for"] == ["creature", "artifact", "enchantment", "planeswalker"]


# gold set (real card DB): card -> answer types with NO limiting restriction
UNRESTRICTED_GOLD = [
    ("Swords to Plowshares", ["creature"]),
    ("Beast Within", ["creature", "artifact", "enchantment", "planeswalker", "land"]),
    ("Cyclonic Rift", ["creature", "artifact", "enchantment", "planeswalker"]),
    ("Damnation", ["creature"]),
    ("Blasphemous Act", ["creature"]),
    ("Doom Blade", []),
    ("Culling Sun", []),
    ("Eaten by Spiders", []),
    ("Lightning Bolt", []),
    ("Negate", []),
    ("Mana Leak", []),
    ("Counterspell", ["spell"]),
    ("Assassin's Trophy", ["creature", "artifact", "enchantment", "planeswalker", "land"]),
    ("Skyfisher Spider", ["creature", "artifact", "enchantment", "planeswalker"]),
    ("Toxic Deluge", ["creature"]),
    ("Tergrid's Shadow", []),
    ("Abrade", ["artifact"]),
]


@pytest.mark.parametrize("name,types", UNRESTRICTED_GOLD, ids=[g[0] for g in UNRESTRICTED_GOLD])
def test_unrestricted_gold(db, name, types):
    cov = removal.coverage_for_cards([db.get(name)])
    got = [t for t, names in cov["unrestricted_answers_by_type"].items() if names]
    assert got == types


def test_shelob_creature_answers_are_mostly_restricted(db):
    from mythgauntlet.model.deck import Deck, resolve
    path = Path(__file__).resolve().parents[2] / "corpus" / "decks" / "archidekt-1010839.txt"
    if not path.exists():
        pytest.skip("corpus deck absent")
    cov = removal.coverage(resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db))
    assert len(cov["answers_by_type"]["creature"]) > 2 * len(cov["unrestricted_answers_by_type"]["creature"])
    assert "Eaten by Spiders" not in cov["unrestricted_answers_by_type"]["creature"]
