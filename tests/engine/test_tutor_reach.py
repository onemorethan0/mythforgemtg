"""What a tutor can fetch (B33): the object is gated from its own search text, the cost is
subtracted, and anything the reader cannot verify is not a counted tutor."""
from __future__ import annotations

import math

import pytest

from mythgauntlet.semantics.tutor_reach import tutor_reach


@pytest.fixture
def pieces(make_card):
    oracle = make_card("Thassa's Oracle", mana_cost="{U}{U}", type_line="Creature — Merfolk Wizard",
                       colors=("U",), power="1", toughness="3")
    consult = make_card("Demonic Consultation", mana_cost="{B}", type_line="Instant", colors=("B",))
    reversal = make_card("Dramatic Reversal", mana_cost="{1}{U}", type_line="Instant", colors=("U",))
    scepter = make_card("Isochron Scepter", mana_cost="{2}", type_line="Artifact")
    krenko = make_card("Krenko, Mob Boss", mana_cost="{2}{R}{R}",
                       type_line="Legendary Creature — Goblin Warrior", colors=("R",),
                       power="3", toughness="3")
    sabertooth = make_card("Temur Sabertooth", mana_cost="{2}{G}{G}", type_line="Creature — Cat",
                           colors=("G",), power="4", toughness="3")
    blood = make_card("Exquisite Blood", mana_cost="{4}{B}", type_line="Enchantment", colors=("B",))
    depths = make_card("Dark Depths", type_line="Legendary Snow Land")
    return {c.name: c for c in (oracle, consult, reversal, scepter, krenko, sabertooth, blood, depths)}


def _can(reach, pieces):
    return sorted(n for n, c in pieces.items() if reach.can_fetch(c))


def test_a_card_tutor_reaches_everything_and_says_where_it_goes(make_card, pieces):
    demonic = tutor_reach(make_card("Demonic Tutor", mana_cost="{1}{B}", type_line="Sorcery",
                                    oracle_text="Search your library for a card, put that card "
                                                "into your hand, then shuffle."))
    assert (demonic.timing, demonic.destination, demonic.cast_cost) == ("spell", "hand", 2)
    assert _can(demonic, pieces) == sorted(pieces)
    vampiric = tutor_reach(make_card("Vampiric Tutor", mana_cost="{B}", type_line="Instant",
                                     oracle_text="Search your library for a card, then shuffle and "
                                                 "put that card on top. You lose 2 life."))
    assert vampiric.destination == "top"          # on top AFTER the shuffle still counts


def test_the_object_is_gated(make_card, pieces):
    mystical = tutor_reach(make_card(
        "Mystical Tutor", mana_cost="{U}", type_line="Instant",
        oracle_text="Search your library for an instant or sorcery card, reveal it, then "
                    "shuffle and put that card on top."))
    assert _can(mystical, pieces) == ["Demonic Consultation", "Dramatic Reversal"]
    merchant = tutor_reach(make_card(
        "Merchant Scroll", mana_cost="{1}{U}", type_line="Sorcery",
        oracle_text="Search your library for a blue instant card, reveal that card, put it into "
                    "your hand, then shuffle."))
    assert _can(merchant, pieces) == ["Dramatic Reversal"]
    gsz = tutor_reach(make_card(
        "Green Sun's Zenith", mana_cost="{X}{G}", type_line="Sorcery",
        oracle_text="Search your library for a green creature card with mana value X or less, "
                    "put it onto the battlefield, then shuffle. Shuffle Green Sun's Zenith into "
                    "its owner's library."))
    assert _can(gsz, pieces) == ["Temur Sabertooth"] and gsz.x_cost
    assert gsz.destination == "battlefield"


def test_an_adjective_alternative_takes_the_last_noun(make_card, pieces):
    r = tutor_reach(make_card("RG Tutor", mana_cost="{1}", type_line="Sorcery",
                              oracle_text="Search your library for a red or green creature card, "
                                          "put it into your hand, then shuffle."))
    assert _can(r, pieces) == ["Krenko, Mob Boss", "Temur Sabertooth"]   # not Exquisite Blood


def test_negated_types(make_card, pieces):
    r = tutor_reach(make_card("Nonthing", mana_cost="{1}", type_line="Sorcery",
                              oracle_text="Search your library for a noncreature, nonland card, "
                                          "put it into your hand, then shuffle."))
    assert _can(r, pieces) == ["Demonic Consultation", "Dramatic Reversal", "Exquisite Blood",
                               "Isochron Scepter"]


def test_power_and_mana_value_postfixes(make_card, pieces):
    recruiter = tutor_reach(make_card(
        "Imperial Recruiter", mana_cost="{2}{R}", type_line="Creature — Human Advisor",
        oracle_text="When this creature enters, search your library for a creature card with "
                    "power 2 or less, reveal it, put it into your hand, then shuffle."))
    assert recruiter.timing == "trigger"
    assert _can(recruiter, pieces) == ["Thassa's Oracle"]
    tribute = tutor_reach(make_card(
        "Tribute Mage", mana_cost="{2}{U}", type_line="Creature — Human Wizard",
        oracle_text="When this creature enters, you may search your library for an artifact card "
                    "with mana value 2, reveal that card, put it into your hand, then shuffle."))
    assert _can(tribute, pieces) == ["Isochron Scepter"]


def test_loyalty_x_is_bounded_by_loyalty(make_card, pieces):
    tez = make_card("Tezzeret the Seeker", mana_cost="{3}{U}{U}",
                    type_line="Legendary Planeswalker — Tezzeret",
                    oracle_text="+1: Untap up to two target artifacts.\n"
                                "−X: Search your library for an artifact card with mana value X "
                                "or less, put it onto the battlefield, then shuffle.")
    tez.loyalty = "1"
    r = tutor_reach(tez)
    assert r.timing == "loyalty" and not r.x_cost
    assert _can(r, pieces) == []                  # Scepter costs 2 > loyalty 1
    tez.loyalty = "4"
    assert _can(tutor_reach(tez), pieces) == ["Isochron Scepter"]


def test_activated_tutors_and_repeatability(make_card):
    survival = tutor_reach(make_card(
        "Survival of the Fittest", mana_cost="{1}{G}", type_line="Enchantment",
        oracle_text="{G}, Discard a creature card: Search your library for a creature card, "
                    "reveal that card, put it into your hand, then shuffle."))
    assert (survival.timing, survival.use_cost, survival.repeatable) == ("activated", 1, True)
    emap = tutor_reach(make_card(
        "Expedition Map", mana_cost="{1}", type_line="Artifact",
        oracle_text="{2}, {T}, Sacrifice this artifact: Search your library for a land card, "
                    "reveal it, put it into your hand, then shuffle."))
    assert (emap.use_cost, emap.repeatable) == (2, False)
    raz = tutor_reach(make_card(
        "Razaketh, the Foulblooded", mana_cost="{5}{B}{B}{B}",
        type_line="Legendary Creature — Demon",
        oracle_text="Flying, trample\nPay 2 life, Sacrifice another creature: Search your library "
                    "for a card, put that card into your hand, then shuffle."))
    assert raz.needs_creature and raz.repeatable
    recruiter = tutor_reach(make_card(
        "Goblin Recruiter", mana_cost="{1}{R}", type_line="Creature — Goblin",
        oracle_text="When this creature enters, search your library for any number of Goblin "
                    "cards, reveal them, then shuffle and put those cards on top in any order."))
    assert recruiter.per_use == math.inf and recruiter.destination == "top"


def test_the_most_conservative_destination_is_credited(make_card):
    charm = tutor_reach(make_card(
        "Archdruid's Charm", mana_cost="{G}{G}{G}", type_line="Instant",
        oracle_text="Choose one —\n• Search your library for a creature or land card and reveal "
                    "it. Put it onto the battlefield tapped if it's a land card. Otherwise, put "
                    "it into your hand. Then shuffle.\n• Exile target artifact or enchantment."))
    assert charm.timing == "spell" and charm.destination == "hand"


def test_additional_cost_sacrifice_a_creature(make_card):
    intent = tutor_reach(make_card(
        "Diabolic Intent", mana_cost="{1}{B}", type_line="Sorcery",
        oracle_text="As an additional cost to cast this spell, sacrifice a creature.\nSearch your "
                    "library for a card, put that card into your hand, then shuffle."))
    assert intent.needs_creature
    rotation = tutor_reach(make_card(
        "Crop Rotation", mana_cost="{G}", type_line="Instant",
        oracle_text="As an additional cost to cast this spell, sacrifice a land.\nSearch your "
                    "library for a land card, put that card onto the battlefield, then shuffle."))
    assert rotation is None                       # a cost the clock does not track


@pytest.mark.parametrize("name,cost,type_line,text", [
    ("Gamble", "{R}", "Sorcery", "Search your library for a card, put that card into your hand, "
     "discard a card at random, then shuffle."),
    ("Intuition", "{2}{U}", "Instant", "Search your library for three cards and reveal them. "
     "Target opponent chooses one. Put that card into your hand and the rest into your "
     "graveyard. Then shuffle."),
    ("Eldritch Evolution", "{1}{G}{G}", "Sorcery", "As an additional cost to cast this spell, "
     "sacrifice a creature.\nSearch your library for a creature card with mana value X or less, "
     "where X is 2 plus the sacrificed creature's mana value. Put that card onto the "
     "battlefield, then shuffle. Exile Eldritch Evolution."),
    ("Muddle the Mixture", "{U}{U}", "Instant", "Counter target instant or sorcery spell.\n"
     "Transmute {1}{U}{U} ({1}{U}{U}, Discard this card: Search your library for a card with the "
     "same mana value as this card, reveal it, put it into your hand, then shuffle. Transmute "
     "only as a sorcery.)"),
    ("Profane Tutor", "", "Sorcery", "Suspend 2—{1}{B}\nSearch your library for a card, put that "
     "card into your hand, then shuffle."),
    ("Entomb", "{B}", "Instant", "Search your library for a card, put that card into your "
     "graveyard, then shuffle."),
    ("Sidisi, Undead Vizier", "{3}{B}{B}", "Legendary Creature — Zombie Snake", "Deathtouch\n"
     "Exploit\nWhen Sidisi exploits a creature, you may search your library for a card, put it "
     "into your hand, then shuffle."),
    ("Weathered Wayfarer", "{W}", "Creature — Human Nomad Cleric", "{W}, {T}: Search your library "
     "for a land card, reveal it, put it into your hand, then shuffle. Activate only if an "
     "opponent controls more lands than you."),
    ("Odd Tutor", "{1}", "Sorcery", "Search your library for a card with flash, put it into your "
     "hand, then shuffle."),
])
def test_unverifiable_tutors_are_not_counted(make_card, name, cost, type_line, text):
    assert tutor_reach(make_card(name, mana_cost=cost, type_line=type_line,
                                 oracle_text=text)) is None


def test_a_tutor_never_fetches_itself(make_card):
    c = make_card("Self Tutor", mana_cost="{1}", type_line="Sorcery",
                  oracle_text="Search your library for a card, put it into your hand, then shuffle.")
    assert not tutor_reach(c).can_fetch(c)
