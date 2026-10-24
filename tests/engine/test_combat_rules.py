"""Command-zone combat-damage rules (toughness matters), pinned to verbatim oracle text.

Found 2026-10-23: a Doran, Besieged by Time deck read Ceiling 12 / "no finisher" / kill ~T11
because tier0 combat summed printed POWER only, while under Doran its attackers hit for 2.4x
that. Every commander in the class is listed with the rule it gets - or why it gets none.
"""
import pytest

from mythgauntlet.model.card import Card
from mythgauntlet.sim import combat_rules as cr

ORACLE = {
    "Doran, the Siege Tower":
        "Each creature assigns combat damage equal to its toughness rather than its power.",
    "Doran, Besieged by Time":
        "Each creature spell you cast with toughness greater than its power costs {1} less to cast.\n"
        "Whenever a creature you control attacks or blocks, it gets +X/+X until end of turn, where X "
        "is the difference between its power and toughness.",
    "Arcades, the Strategist":
        "Flying, vigilance\nWhenever a creature you control with defender enters, draw a card.\n"
        "Each creature you control with defender assigns combat damage equal to its toughness rather "
        "than its power and can attack as though it didn't have defender.",
    "Felothar the Steadfast":
        "Each creature you control assigns combat damage equal to its toughness rather than its power.\n"
        "Creatures you control can attack as though they didn't have defender.\n"
        "{3}, {T}, Sacrifice another creature: Draw cards equal to the sacrificed creature's toughness, "
        "then discard cards equal to its power.",
    "Baldin, Century Herdmaster":
        "During your turn, each creature assigns combat damage equal to its toughness rather than its "
        "power.\nWhenever Baldin attacks, up to one hundred target creatures each get +0/+X until end of "
        "turn, where X is the number of cards in your hand.",
    "Ghalta the Immovable":
        "This spell costs {X} less to cast, where X is the greatest toughness among creatures you "
        "control.\nCreatures you control can attack as though they didn't have defender.\nEach creature "
        "you control with toughness greater than its power assigns combat damage equal to its toughness "
        "rather than its power.",
    # Conditional: an optional life payment per attack. Declined (under-count), not assumed.
    "The Kingpin of Crime":
        "Extort (Whenever you cast a spell, you may pay {W/B}. If you do, each opponent loses 1 life "
        "and you gain that much life.)\nWhenever you attack, you may pay 2 life. If you do, until end "
        "of turn, creatures you control with toughness greater than their power assign combat damage "
        "equal to their toughness rather than their power.",
    # Activated, one creature, needs mana each turn. Declined.
    "Plagon, Lord of the Beach":
        "When Plagon enters, draw a card for each creature you control with toughness greater than "
        "its power.\n{W/U}: Target creature you control assigns combat damage equal to its toughness "
        "rather than its power this turn.",
}


def _cmd(name):
    return Card(name=name, type_line="Legendary Creature", oracle_text=ORACLE[name],
                power="0", toughness="5")


def _c(p, t, *kw):
    return Card(name=f"x{p}{t}", type_line="Creature", power=str(p), toughness=str(t),
                keywords=frozenset(kw))


@pytest.mark.parametrize("name", ["The Kingpin of Crime", "Plagon, Lord of the Beach"])
def test_conditional_rules_are_declined(name):
    assert cr.from_commanders([_cmd(name)]) is None


def test_plain_commander_has_no_rule():
    plain = Card(name="Krenko", type_line="Legendary Creature", oracle_text="{T}: Create goblins.")
    assert cr.from_commanders([plain]) is None


@pytest.mark.parametrize("name", ["Doran, the Siege Tower", "Felothar the Steadfast",
                                  "Baldin, Century Herdmaster"])
def test_toughness_for_power(name):
    rule = cr.from_commanders([_cmd(name)])
    assert rule.attack_power(_c(0, 4)) == 4
    assert rule.attack_power(_c(5, 1)) == 1        # it really is toughness, not the max


def test_ghalta_only_where_toughness_is_greater():
    rule = cr.from_commanders([_cmd("Ghalta the Immovable")])
    assert rule.attack_power(_c(1, 6)) == 6
    assert rule.attack_power(_c(5, 1)) == 5
    assert rule.attack_power(_c(0, 30, "defender")) == 30   # and defenders may attack


def test_arcades_only_defenders():
    rule = cr.from_commanders([_cmd("Arcades, the Strategist")])
    assert rule.attack_power(_c(0, 6, "defender")) == 6
    assert rule.attack_power(_c(2, 5)) == 2


def test_doran_besieged_pumps_by_the_gap_both_ways():
    rule = cr.from_commanders([_cmd("Doran, Besieged by Time")])
    assert rule.attack_power(_c(0, 4)) == 4
    assert rule.attack_power(_c(3, 7)) == 7
    assert rule.attack_power(_c(4, 3)) == 5        # X = |p - t|: a 4/3 attacks as 5/4
    assert rule.attack_power(_c(2, 2)) == 2
    assert rule.attack_power(_c(0, 30, "defender")) == 0    # Doran does not let defenders attack
    assert rule.creature_discount(_c(0, 4)) == 1
    assert rule.creature_discount(_c(4, 3)) == 0


def test_defender_never_attacks_without_permission():
    # CR 702.3b, independent of any rule: tier0 used to swing with defenders.
    assert cr.attack_power(_c(3, 3, "defender"), None) == 0
    assert cr.attack_power(_c(3, 3, "double strike"), None) == 6


def test_scope_flags():
    assert cr.from_commanders([_cmd("Doran, the Siege Tower")]).all_creatures is True
    assert cr.from_commanders([_cmd("Felothar the Steadfast")]).all_creatures is False
    baldin = cr.from_commanders([_cmd("Baldin, Century Herdmaster")])
    assert baldin.all_creatures is True and baldin.your_turn_only is True
