"""Commander lens: how the commander changes what a card does (offline, synthetic cards)."""

import pytest

from dataclasses import replace

from mythgauntlet.semantics.commander_lens import (
    LensDeckContext, admits, build_lens, lens_self_names, x_budget,
)

SMAUG = dict(name="Smaug the Impenetrable", mana_cost="{5}{B}{R}",
    type_line="Legendary Creature — Dragon", power="8", toughness="7",
    keywords=frozenset({"flying", "indestructible", "haste", "treasure"}),
    oracle_text="Flying, indestructible, haste\nWhenever Smaug is dealt noncombat damage, create that many Treasure tokens.")
WRATH = dict(name="Wrath of God", mana_cost="{2}{W}{W}", type_line="Sorcery",
    oracle_text="Destroy all creatures. They can't be regenerated.")
FAREWELL = dict(name="Farewell", mana_cost="{4}{W}{W}", type_line="Sorcery",
    oracle_text="Choose one or more —\n• Exile all artifacts.\n• Exile all creatures.\n• Exile all enchantments.\n• Exile all graveyards.")
DELUGE = dict(name="Toxic Deluge", mana_cost="{2}{B}", type_line="Sorcery",
    oracle_text="As an additional cost to cast this spell, pay X life.\nAll creatures get -X/-X until end of turn.")
RUINOUS = dict(name="Ruinous Ultimatum", mana_cost="{R}{R}{W}{W}{W}{B}{B}", type_line="Sorcery",
    oracle_text="Destroy all nonland permanents your opponents control.")
DESOLATION = dict(name="Desolation of Smaug", mana_cost="{2}{R}{R}", type_line="Sorcery",
    oracle_text="Desolation of Smaug deals 3 damage to each non-Dragon creature.\nAdd four mana in any combination of colors. Spend this mana only to cast Dragon spells.")


BLASPHEMOUS = dict(name="Blasphemous Act", mana_cost="{8}{R}", type_line="Sorcery",
    oracle_text="This spell costs {1} less to cast for each creature on the battlefield.\nBlasphemous Act deals 13 damage to each creature.")
EARTHQUAKE = dict(name="Earthquake", mana_cost="{X}{R}", type_line="Sorcery",
    oracle_text="Earthquake deals X damage to each creature without flying and each player.")
ROLLING = dict(name="Rolling Earthquake", mana_cost="{X}{R}", type_line="Sorcery",
    oracle_text="Rolling Earthquake deals X damage to each creature without horsemanship and each player.")
BOLT = dict(name="Lightning Bolt", mana_cost="{R}", type_line="Instant",
    oracle_text="Lightning Bolt deals 3 damage to any target.")
IGNITION = dict(name="Chandra's Ignition", mana_cost="{3}{R}{R}", type_line="Sorcery",
    oracle_text="Target creature you control deals damage equal to its power to each other creature and each opponent.")
KAZAROV = dict(name="Kazarov, Sengir Pureblood", mana_cost="{5}{B}{B}",
    type_line="Legendary Creature — Vampire", keywords=frozenset({"flying"}), power="4", toughness="4",
    oracle_text="Flying\nWhenever a creature an opponent controls is dealt damage, put a +1/+1 counter on Kazarov.\n{3}{R}: Kazarov deals 2 damage to target creature.")
KLEMENT = dict(name="Klement, Tempest Acolyte", mana_cost="{1}{R}{W}",
    type_line="Legendary Creature — Tiefling Cleric", keywords=frozenset({"double strike"}), power="2", toughness="3",
    oracle_text="Double strike\nWhenever Klement, Tempest Acolyte is dealt damage, it deals that much damage to any target.")
CTX = LensDeckContext(mana_by_turn=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12), avg_commander_turn=6.2, counter_reserve=0)
KIND = "damage_to_self_payoff"


@pytest.fixture
def smaug(make_card):
    return make_card(**SMAUG)


def test_smaug_survives_wrath(make_card, smaug):
    lens = build_lens([smaug])
    assert lens.facts_for(make_card(**WRATH)).wipe_one_sided is True
    assert "survives_wipe" in lens.kinds


def test_exile_wipe_not_one_sided(make_card, smaug):
    assert build_lens([smaug]).facts_for(make_card(**FAREWELL)).empty


def test_minus_wipe_not_one_sided(make_card, smaug):
    assert build_lens([smaug]).facts_for(make_card(**DELUGE)).empty


def test_opponent_only_wipe_is_not_commander_synergy(make_card, smaug):
    assert build_lens([smaug]).facts_for(make_card(**RUINOUS)).empty


def test_non_dragon_filter_excludes_smaug(make_card, smaug):
    f = build_lens([smaug]).facts_for(make_card(**DESOLATION))
    assert f.wipe_one_sided is False


def test_no_commander_is_empty_lens(make_card):
    lens = build_lens([])
    assert lens.kinds == ()
    assert lens.facts_for(make_card(**WRATH)).empty


def test_partner_kinds_union_resilience_reads_lead(make_card, bear, smaug):
    assert "survives_wipe" in build_lens([bear, smaug]).kinds
    assert build_lens([bear, smaug]).survives_mode("destroy") is False
    assert build_lens([smaug, bear]).survives_mode("destroy") is True


def test_partner_lead_not_indestructible_makes_no_wipe_claim(make_card, bear, smaug):
    assert build_lens([bear, smaug]).facts_for(make_card(**WRATH)).empty
    f = build_lens([smaug, bear]).facts_for(make_card(**WRATH))
    assert f.wipe_one_sided is True
    assert f.reason.startswith("Smaug the Impenetrable")


def test_face_ambiguous_commander_is_honest_undercount(make_card):
    s = make_card(**{**SMAUG, "layout": "transform", "keywords": frozenset()})
    lens = build_lens([s])
    assert "survives_wipe" not in lens.kinds
    assert lens.facts_for(make_card(**WRATH)).empty


def test_flagged_returns_names(make_card, smaug):
    lens = build_lens([smaug])
    assert lens.flagged([make_card(**WRATH), make_card(**FAREWELL)]) == {"Wrath of God"}


@pytest.mark.parametrize("obj,expected", [
    ("creatures", True),
    ("nonland permanents your opponents control", False),
    ("creatures you don't control", False),
    ("creatures without flying", False),
    ("creatures without trample", True),
    ("non-dragon creatures", False),
    ("nonwarrior creatures", True),
    ("creatures with power 4 or greater", None),
    ("tapped creatures", None),
])
def test_admits(smaug, obj, expected):
    assert admits(obj, smaug) is expected


def test_blasphemous_act_under_smaug(make_card, smaug):
    f = build_lens([smaug]).facts_for(make_card(**BLASPHEMOUS))
    assert f.payoff_treasure == 13
    assert f.payoff_kind == KIND
    assert f.wipe_one_sided is True


def test_earthquake_never_hits_flying_smaug(make_card, smaug):
    f = build_lens([smaug], CTX).facts_for(make_card(**EARTHQUAKE))
    assert f.payoff_kind is None
    assert f.payoff_treasure == 0


def test_rolling_earthquake_x_from_budget(make_card, smaug):
    rolling = make_card(**ROLLING)
    assert build_lens([smaug], CTX).facts_for(rolling).payoff_treasure == 7
    assert x_budget(rolling, CTX) == 7
    ctx2 = replace(CTX, counter_reserve=2)
    assert build_lens([smaug], ctx2).facts_for(rolling).payoff_treasure == 5


def test_x_without_context_is_zero(make_card, smaug):
    rolling = make_card(**ROLLING)
    assert build_lens([smaug]).facts_for(rolling).payoff_treasure == 0
    ctx = replace(CTX, avg_commander_turn=None)
    assert build_lens([smaug], ctx).facts_for(rolling).payoff_treasure == 0
    assert x_budget(rolling, None) == 0


def test_bolt_is_label_only(make_card, smaug):
    f = build_lens([smaug]).facts_for(make_card(**BOLT))
    assert f.payoff_kind == KIND
    assert f.payoff_treasure == 0
    assert f.wipe_one_sided is False


def test_equal_to_damage_is_label_only(make_card, smaug):
    f = build_lens([smaug]).facts_for(make_card(**IGNITION))
    assert f.payoff_kind == KIND
    assert f.payoff_treasure == 0


def test_short_legend_name_detected(smaug):
    assert "smaug" in lens_self_names(smaug)
    assert KIND in build_lens([smaug]).kinds


def test_full_name_subject_detected(make_card):
    klement = make_card(**KLEMENT)
    lens = build_lens([klement])
    assert KIND in lens.kinds
    f = lens.facts_for(make_card(**BLASPHEMOUS))
    assert f.payoff_kind == KIND
    assert f.payoff_treasure == 0


def test_other_subject_not_detected(make_card):
    assert KIND not in build_lens([make_card(**KAZAROV)]).kinds


MEREN = dict(name="Meren of Clan Nel Toth", mana_cost="{2}{B}{G}",
    type_line="Legendary Creature — Human Shaman", power="3", toughness="4",
    oracle_text="Whenever another creature you control dies, you get an experience counter.\nAt the beginning of your end step, choose target creature card in your graveyard. If that card's mana value is less than or equal to the number of experience counters you have, return it to the battlefield. Otherwise, put it into your hand.")
TOSHIRO = dict(name="Toshiro Umezawa", mana_cost="{1}{B}{B}",
    type_line="Legendary Creature — Human Samurai", keywords=frozenset({"bushido"}), power="2", toughness="2",
    oracle_text="Bushido 1 (Whenever this creature blocks or becomes blocked, it gets +1/+1 until end of turn.)\nWhenever a creature an opponent controls dies, you may cast target instant card from your graveyard. If that spell would be put into a graveyard, exile it instead.")
VISCERA = dict(name="Viscera Seer", mana_cost="{B}", type_line="Creature — Vampire Wizard",
    keywords=frozenset({"scry"}), power="1", toughness="1",
    oracle_text="Sacrifice a creature: Scry 1. (Look at the top card of your library. You may put that card on the bottom.)")
DEATH = "death_payoff"


def test_meren_wrath_is_death_payoff(make_card):
    f = build_lens([make_card(**MEREN)]).facts_for(make_card(**WRATH))
    assert f.payoff_kind == DEATH
    assert f.payoff_treasure == 0
    assert f.wipe_one_sided is False


def test_meren_sac_outlet_is_death_payoff(make_card):
    f = build_lens([make_card(**MEREN)]).facts_for(make_card(**VISCERA))
    assert f.payoff_kind == DEATH


def test_meren_farewell_not_payoff(make_card):
    assert build_lens([make_card(**MEREN)]).facts_for(make_card(**FAREWELL)).empty


def test_opponent_death_trigger_not_detected(make_card):
    assert DEATH not in build_lens([make_card(**TOSHIRO)]).kinds


def test_meren_opponent_only_wipe_not_payoff(make_card):
    assert build_lens([make_card(**MEREN)]).facts_for(make_card(**RUINOUS)).empty


def test_meren_damage_and_minus_wipes_are_payoff(make_card):
    lens = build_lens([make_card(**MEREN)])
    assert lens.facts_for(make_card(**BLASPHEMOUS)).payoff_kind == DEATH
    assert lens.facts_for(make_card(**DELUGE)).payoff_kind == DEATH


COLFENOR = dict(name="Colfenor, the Last Yew", mana_cost="{3}{W}{B}{G}", type_line="Legendary Creature — Treefolk Shaman", keywords=frozenset({"reach", "vigilance"}), power="3", toughness="7", oracle_text="Reach, vigilance\nWhenever Colfenor or another creature you control dies, return up to one other target creature card with lesser toughness from your graveyard to your hand.")


def test_named_self_death_trigger_detected(make_card):
    colfenor = make_card(**COLFENOR)
    lens = build_lens([colfenor])
    assert DEATH in lens.kinds
    assert lens.facts_for(make_card(**WRATH)).payoff_kind == DEATH


# --- Task 8 corpus-sweep false positives (oracle text verbatim from the card store) ---

INDORAPTOR = dict(name="Indoraptor, the Perfect Hybrid", mana_cost="{1}{B/G}{R}",
    type_line="Legendary Creature — Dinosaur Mutant", power="4", toughness="4",
    keywords=frozenset({"bloodthirst", "enrage", "menace"}),
    oracle_text="Bloodthirst X (This creature enters with X +1/+1 counters on it, where X is the damage dealt to your opponents this turn.)\nMenace\nEnrage — Whenever Indoraptor is dealt damage, choose an opponent at random. Indoraptor deals damage equal to its power to that player unless they sacrifice a nontoken creature of their choice.")
WRATHFUL_RAPTORS = dict(name="Wrathful Raptors", mana_cost="{4}{R}", type_line="Creature — Dinosaur",
    keywords=frozenset({"trample"}), power="5", toughness="5",
    oracle_text="Trample\nWhenever a Dinosaur you control is dealt damage, it deals that much damage to any target that isn't a Dinosaur.")
WRATHFUL_DRAGON = dict(name="Wrathful Red Dragon", mana_cost="{3}{R}{R}", type_line="Creature — Dragon",
    keywords=frozenset({"flying"}), power="5", toughness="5",
    oracle_text="Flying\nWhenever a Dragon you control is dealt damage, it deals that much damage to any target that isn't a Dragon.")
CHAIN_REACTION = dict(name="Chain Reaction", mana_cost="{2}{R}{R}", type_line="Sorcery",
    oracle_text="Chain Reaction deals X damage to each creature, where X is the number of creatures on the battlefield.")
SPITEFUL = dict(name="Spiteful Banditry", mana_cost="{X}{R}{R}", type_line="Enchantment",
    keywords=frozenset({"treasure"}),
    oracle_text="When this enchantment enters, it deals X damage to each creature.\nWhenever one or more creatures your opponents control die, you create a Treasure token. This ability triggers only once each turn.")
DRUID_PURIFICATION = dict(name="Druid of Purification", mana_cost="{3}{G}", type_line="Creature — Human Druid",
    power="2", toughness="3",
    oracle_text="When this creature enters, starting with you, each player may choose an artifact or enchantment you don't control. Destroy each permanent chosen this way.")
SEASON_GATHERING = dict(name="Season of Gathering", mana_cost="{4}{G}{G}", type_line="Sorcery",
    oracle_text="Choose up to five {P} worth of modes. You may choose the same mode more than once.\n{P} — Put a +1/+1 counter on a creature you control. It gains vigilance and trample until end of turn.\n{P}{P} — Choose artifact or enchantment. Destroy all permanents of the chosen type.\n{P}{P}{P} — Draw cards equal to the greatest power among creatures you control.")
REYHAN = dict(name="Reyhan, Last of the Abzan", mana_cost="{1}{B}{G}",
    type_line="Legendary Creature — Human Warrior", keywords=frozenset({"partner"}), power="0", toughness="0",
    oracle_text="Reyhan enters with three +1/+1 counters on it.\nWhenever a creature you control dies or is put into the command zone, if it had one or more +1/+1 counters on it, you may put that many +1/+1 counters on target creature.\nPartner (You can have two commanders if both have partner.)")
DAMNING_VERDICT = dict(name="Damning Verdict", mana_cost="{3}{W}{W}", type_line="Sorcery",
    oracle_text="Destroy all creatures with no counters on them.")


def test_any_target_that_isnt_commander_type_is_not_a_hit(make_card, smaug):
    # Wrathful Raptors cannot target Indoraptor (a Dinosaur); Wrathful Red Dragon cannot
    # target Smaug (a Dragon). The restriction trails "any target".
    assert build_lens([make_card(**INDORAPTOR)]).facts_for(make_card(**WRATHFUL_RAPTORS)).empty
    assert build_lens([smaug]).facts_for(make_card(**WRATHFUL_DRAGON)).empty


def test_any_target_still_hits_a_commander_of_another_type(make_card):
    # The same restriction does not stop Wrathful Red Dragon hitting a Dinosaur commander.
    f = build_lens([make_card(**INDORAPTOR)]).facts_for(make_card(**WRATHFUL_DRAGON))
    assert f.payoff_kind == KIND


def test_x_defined_by_where_clause_is_not_mana_x(make_card, smaug):
    # Chain Reaction's X is the creature count, not mana: no Treasure from the mana budget.
    f = build_lens([smaug], CTX).facts_for(make_card(**CHAIN_REACTION))
    assert f.payoff_kind == KIND
    assert f.payoff_treasure == 0


def test_cast_x_in_mana_cost_still_uses_budget(make_card, smaug):
    f = build_lens([smaug], CTX).facts_for(make_card(**SPITEFUL))
    assert f.payoff_treasure > 0


def test_chosen_back_reference_wipe_is_not_death_payoff(make_card):
    lens = build_lens([make_card(**MEREN)])
    assert lens.facts_for(make_card(**DRUID_PURIFICATION)).empty
    assert lens.facts_for(make_card(**SEASON_GATHERING)).empty


def test_counter_conditioned_death_trigger_ignores_no_counter_wipe(make_card):
    lens = build_lens([make_card(**REYHAN)])
    assert DEATH in lens.kinds
    assert lens.facts_for(make_card(**DAMNING_VERDICT)).empty
    # Wrath of God leaves no creature to target with Reyhan's counters (final review).
    assert lens.facts_for(make_card(**WRATH)).empty
    assert lens.facts_for(make_card(**VISCERA)).payoff_kind == DEATH
    # Meren has no counter condition: Damning Verdict still kills her deck's creatures.
    assert build_lens([make_card(**MEREN)]).facts_for(make_card(**DAMNING_VERDICT)).payoff_kind == DEATH


PESTILENCE = dict(name="Pestilence", mana_cost="{2}{B}{B}", type_line="Enchantment",
    oracle_text="At the beginning of the end step, if no creatures are on the battlefield, sacrifice this enchantment.\n{B}: This enchantment deals 1 damage to each creature and each player.")
MJOLNIR = dict(name="Mj\u00f6lnir, Hammer of Thor", mana_cost="{3}{R}", type_line="Legendary Artifact \u2014 Equipment",
    oracle_text="When Mj\u00f6lnir enters, it deals 4 damage to up to one target creature.\nDouble all damage equipped creature would deal.\nEquip worthy {1} (A creature is worthy if it's a legendary non-Villain that's red and/or white.)\n{2}{R}, Discard this card: It deals 2 damage to each creature.")
LAVABRINK = dict(name="Lavabrink Floodgates", mana_cost="{3}{R}", type_line="Artifact",
    oracle_text="{T}: Add {R}{R}.\nAt the beginning of each player's upkeep, that player may put a doom counter on this artifact or remove a doom counter from it. Then if it has three or more doom counters on it, sacrifice this artifact. When you do, it deals 6 damage to each creature.")


def test_mana_paid_activation_treasure_is_net_of_its_cost(make_card, smaug):
    # Pestilence: pay {B}, Smaug takes 1, makes 1 Treasure -- no net mana, so no Ramp credit.
    # Mjolnir: pay {2}{R} for 2 damage -- net negative. Both keep the synergy label.
    lens = build_lens([smaug], CTX)
    for spec in (PESTILENCE, MJOLNIR):
        f = lens.facts_for(make_card(**spec))
        assert f.payoff_kind == KIND
        assert f.payoff_treasure == 0
    # An ETB-triggered (unpaid) mass damage keeps its full credit. (Lavabrink's upkeep
    # trigger is label only: test_non_etb_trigger_damage_is_label_only.)
    assert lens.facts_for(make_card(**SPITEFUL)).payoff_treasure == 6


# --- Task 8 review: colour exclusions (oracle text verbatim from the card store) ---

STRAFE = dict(name="Strafe", mana_cost="{R}", type_line="Sorcery",
    oracle_text="Strafe deals 3 damage to target nonred creature.")
KAERVEKS_HEX = dict(name="Kaervek's Hex", mana_cost="{3}{B}", type_line="Sorcery",
    oracle_text="Kaervek's Hex deals 1 damage to each nonblack creature and an additional 1 damage to each green creature.")
HELLFIRE = dict(name="Hellfire", mana_cost="{2}{B}{B}{B}", type_line="Sorcery",
    oracle_text="Destroy all nonblack creatures. Hellfire deals X plus 3 damage to you, where X is the number of creatures that died this way.")


def _coloured_smaug(make_card):
    return make_card(**SMAUG, colors=("B", "R"), color_identity=("B", "R"))


def test_target_nonred_cannot_hit_red_smaug(make_card):
    assert build_lens([_coloured_smaug(make_card)]).facts_for(make_card(**STRAFE)).empty


def test_target_nonred_still_hits_a_commander_of_another_colour(make_card):
    klement = make_card(**KLEMENT, colors=("R", "W"), color_identity=("R", "W"))
    green = replace(klement, colors=("G",), color_identity=("G",))
    assert build_lens([klement]).facts_for(make_card(**STRAFE)).empty
    assert build_lens([green]).facts_for(make_card(**STRAFE)).payoff_kind == KIND


def test_mass_nonblack_misses_black_smaug(make_card):
    lens = build_lens([_coloured_smaug(make_card)])
    assert lens.facts_for(make_card(**KAERVEKS_HEX)).empty
    assert lens.facts_for(make_card(**HELLFIRE)).empty
    assert admits("each nonblack creature", _coloured_smaug(make_card)) is False


# --- Final whole-branch review (oracle text verbatim from the card store) ---

ODRIC = dict(name="Odric, Blood-Cursed", mana_cost="{1}{R}{W}",
    type_line="Legendary Creature — Vampire Soldier", power="3", toughness="3",
    colors=("R", "W"),
    keywords=frozenset({"haste", "reach", "lifelink", "indestructible", "deathtouch",
                        "double strike", "menace", "hexproof", "first strike", "trample"}),
    oracle_text="When Odric enters, create X Blood tokens, where X is the number of abilities from among flying, first strike, double strike, deathtouch, haste, hexproof, indestructible, lifelink, menace, reach, trample, and vigilance found among creatures you control. (Count each ability only once.)")
HOUR = dict(name="Hour of Devastation", mana_cost="{3}{R}{R}", type_line="Sorcery",
    oracle_text="All creatures lose indestructible until end of turn. Hour of Devastation deals 5 damage to each creature and each non-Bolas planeswalker.")
EXTERMINATUS = dict(name="Exterminatus", mana_cost="{5}{W}{B}", type_line="Sorcery",
    oracle_text="Nonland permanents your opponents control lose indestructible until end of turn.\nDestroy all nonland permanents.")
VENUS = dict(name="Venus, Torn Between Worlds", mana_cost="{4}{G}",
    type_line="Legendary Creature — Mutant Frog Turtle", power="5", toughness="5", colors=("G",),
    oracle_text="Whenever Venus is dealt damage, put that many +1/+1 counters on her. (She must survive the damage to get the counters.)\nWhenever a creature you control with a counter on it deals combat damage to a player, you may pay {U}. If you do, draw a card.")
MOCKINGBIRD = dict(name="Mockingbird, Bobbi Morse", mana_cost="{3}{W}",
    type_line="Legendary Creature — Human Hero", power="3", toughness="3", colors=("W",),
    oracle_text="Whenever Mockingbird is dealt damage, put a +1/+1 counter on her. (She must survive the damage to get the counter.)")
HERCULES = dict(name="Hercules, Olympian Hero", mana_cost="{3}{W}{W}",
    type_line="Legendary Creature — Demigod Warrior Hero", power="3", toughness="3", colors=("W",),
    oracle_text="Whenever Hercules attacks, put a +1/+1 counter on him. He gains indestructible until end of turn.\nWhenever Hercules is dealt damage for the first time each turn, put that many +1/+1 counters on him. (He must survive the damage to get the counters.)")
RED_HULK = dict(name="Red Hulk", mana_cost="{4}{R}{R}",
    type_line="Legendary Creature — Gamma Berserker Villain", power="6", toughness="7", colors=("R",),
    keywords=frozenset({"enrage", "trample", "reach"}),
    oracle_text="Reach, trample\nEnrage — Whenever Red Hulk is dealt damage, put a +1/+1 counter on him. When you do, he deals damage equal to the number of +1/+1 counters on him to any other target.")
STRONG = dict(name="Strong, the Brutish Thespian", mana_cost="{4}{G}{G}",
    type_line="Legendary Creature — Mutant Berserker", power="7", toughness="7", colors=("G",),
    keywords=frozenset({"enrage", "ward"}),
    oracle_text="Ward {2}\nEnrage — Whenever Strong is dealt damage, you get three rad counters and put three +1/+1 counters on Strong.\nYou gain life rather than lose life from radiation.")
FELDON = dict(name="Feldon, Ronom Excavator", mana_cost="{1}{R}",
    type_line="Legendary Creature — Human Artificer", power="2", toughness="2", colors=("R",),
    keywords=frozenset({"haste"}),
    oracle_text="Haste\nFeldon can't block.\nWhenever Feldon is dealt damage, exile that many cards from the top of your library. Choose one of them. Until the end of your next turn, you may play that card.")
RAPHAEL = dict(name="Raphael, Ninja Destroyer", mana_cost="{2}{R}{R}",
    type_line="Legendary Creature — Mutant Ninja Turtle", power="4", toughness="4", colors=("R",),
    keywords=frozenset({"enrage"}),
    oracle_text="Raphael must be blocked if able.\nEnrage — Whenever Raphael is dealt damage, add that much {R}. Until end of turn, you don't lose this mana as steps and phases end.")
ZALTO = dict(name="Zalto, Fire Giant Duke", mana_cost="{3}{R}{R}",
    type_line="Legendary Creature — Giant Barbarian", power="7", toughness="3", colors=("R",),
    keywords=frozenset({"trample", "venture into the dungeon"}),
    oracle_text="Trample\nWhenever Zalto is dealt damage, venture into the dungeon. (Enter the first room or advance to the next room.)")
KOZILEKS_RETURN = dict(name="Kozilek's Return", mana_cost="{2}{R}", type_line="Instant",
    keywords=frozenset({"devoid"}),
    oracle_text="Devoid (This card has no color.)\nKozilek's Return deals 2 damage to each creature.\nWhenever you cast an Eldrazi creature spell with mana value 7 or greater, you may exile this card from your graveyard. If you do, this card deals 5 damage to each creature.")


def test_mentioned_keyword_is_not_a_printed_keyword(make_card):
    # Scryfall's keywords list what Odric's text MENTIONS; Odric himself is a vanilla 3/3
    # with an ETB. He is not indestructible, so Wrath of God is not one-sided for him.
    odric = make_card(**ODRIC)
    lens = build_lens([odric])
    assert "survives_wipe" not in lens.kinds
    assert lens.survives_mode("destroy") is False
    assert build_lens([odric, make_card(**SMAUG)]).facts_for(make_card(**WRATH)).empty
    # "without trample" does not exclude Odric: he has no trample.
    assert admits("creatures without trample", odric) is True


def test_keyword_confirmed_by_bare_keyword_line(smaug):
    from mythgauntlet.semantics.commander_lens import has_keyword
    assert has_keyword(smaug, "indestructible")
    assert has_keyword(smaug, "flying")
    assert not has_keyword(smaug, "treasure")  # in Scryfall's list, not a keyword Smaug has


def test_keyword_confirmed_by_unconditional_self_grant(make_card):
    # FICTIONAL test-only cards (no legendary creature in the store grants itself
    # indestructible in a sentence): unconditional grant counts, a conditional one does not.
    from mythgauntlet.semantics.commander_lens import has_keyword
    plain = make_card(name="Fictional Bastion Golem", type_line="Legendary Creature — Golem",
        keywords=frozenset({"indestructible"}),
        oracle_text="Fictional Bastion Golem has indestructible.")
    cond = make_card(name="Fictional Bastion Golem", type_line="Legendary Creature — Golem",
        keywords=frozenset({"indestructible"}),
        oracle_text="Fictional Bastion Golem has indestructible as long as you control an artifact.")
    assert has_keyword(plain, "indestructible")
    assert not has_keyword(cond, "indestructible")


def test_wipe_that_strips_indestructible_is_not_one_sided(make_card, smaug):
    f = build_lens([smaug]).facts_for(make_card(**HOUR))
    assert f.wipe_one_sided is False
    assert "survives" not in f.reason
    # Smaug still takes the 5 (LKI: the trigger makes Treasure even if he dies).
    assert f.payoff_kind == KIND
    assert f.payoff_treasure == 5


def test_opponent_only_indestructible_loss_stays_one_sided(make_card, smaug):
    assert build_lens([smaug]).facts_for(make_card(**EXTERMINATUS)).wipe_one_sided is True


@pytest.mark.parametrize("spec", [VENUS, MOCKINGBIRD, HERCULES, RED_HULK])
def test_must_survive_payoff_is_not_a_mass_damage_payoff(make_card, spec):
    # Counters on the commander need it to survive: Blasphemous Act kills it first.
    lens = build_lens([make_card(**spec)])
    assert KIND in lens.kinds
    assert lens.facts_for(make_card(**BLASPHEMOUS)).empty
    # Targeted damage is still a choice the pilot can size: label kept.
    assert lens.facts_for(make_card(**BOLT)).payoff_kind == KIND


def test_must_survive_payoff_keeps_mass_damage_below_toughness(make_card):
    # Pestilence's 1 damage leaves 5/5 Venus standing with a counter.
    f = build_lens([make_card(**VENUS)]).facts_for(make_card(**PESTILENCE))
    assert f.payoff_kind == KIND
    assert f.payoff_treasure == 0


@pytest.mark.parametrize("spec", [KLEMENT, FELDON, RAPHAEL, ZALTO, STRONG])
def test_payoff_not_needing_survival_keeps_mass_damage(make_card, spec):
    f = build_lens([make_card(**spec)]).facts_for(make_card(**BLASPHEMOUS))
    assert f.payoff_kind == KIND


def test_indestructible_must_survive_commander_keeps_mass_damage(make_card):
    # FICTIONAL test-only card: an indestructible commander survives the damage.
    toad = make_card(name="Fictional Ironhide Toad", type_line="Legendary Creature — Frog",
        power="2", toughness="2", keywords=frozenset({"indestructible"}),
        oracle_text="Indestructible\nWhenever Fictional Ironhide Toad is dealt damage, put that many +1/+1 counters on it.")
    assert build_lens([toad]).facts_for(make_card(**BLASPHEMOUS)).payoff_kind == KIND


def test_conditional_trigger_damage_is_label_only(make_card, smaug):
    # Kozilek's Return: the cast deals 2 (credited); the graveyard trigger's 5 needs a 7+ MV
    # Eldrazi cast ("if you do") and is not credited.
    f = build_lens([smaug]).facts_for(make_card(**KOZILEKS_RETURN))
    assert f.payoff_kind == KIND
    assert f.payoff_treasure == 2


def test_non_etb_trigger_damage_is_label_only(make_card, smaug):
    # Lavabrink Floodgates' 6 waits on upkeep doom counters: label only.
    f = build_lens([smaug], CTX).facts_for(make_card(**LAVABRINK))
    assert f.payoff_kind == KIND
    assert f.payoff_treasure == 0


def test_fixed_count_treasure_trigger_credits_one(make_card):
    # FICTIONAL test-only commanders: the card store has no legendary creature whose
    # damage trigger makes a fixed number of Treasures.
    fixed = make_card(name="Fictional Hoard Drake", type_line="Legendary Creature — Dragon",
        power="4", toughness="4",
        oracle_text="Whenever Fictional Hoard Drake is dealt damage, create a Treasure token.")
    scaled = make_card(name="Fictional Hoard Drake", type_line="Legendary Creature — Dragon",
        power="4", toughness="4",
        oracle_text="Whenever Fictional Hoard Drake is dealt damage, create a number of Treasure tokens equal to the damage dealt.")
    assert build_lens([fixed]).facts_for(make_card(**BLASPHEMOUS)).payoff_treasure == 1
    assert build_lens([scaled]).facts_for(make_card(**BLASPHEMOUS)).payoff_treasure == 13


# --- Legendary-creature hand-check (final review): death payoffs that need the commander alive ---

THANOS = dict(name="Thanos, Death's Consort", mana_cost="{2}{B}{B}",
    type_line="Legendary Creature — Eternal Villain", power="3", toughness="3", colors=("B",),
    keywords=frozenset({"lifelink"}),
    oracle_text="Lifelink\nWhenever another creature dies, put a +1/+1 counter on Thanos.")
KRESH = dict(name="Kresh the Bloodbraided", mana_cost="{2}{B}{R}{G}",
    type_line="Legendary Creature — Human Warrior", power="3", toughness="3", colors=("B", "G", "R"),
    oracle_text="Whenever another creature dies, you may put X +1/+1 counters on Kresh, where X is that creature's power.")
GIMLI = dict(name="Gimli, Mournful Avenger", mana_cost="{1}{R}{G}",
    type_line="Legendary Creature — Dwarf Warrior", power="3", toughness="2", colors=("G", "R"),
    keywords=frozenset({"fight"}),
    oracle_text="Gimli has indestructible as long as two or more creatures died under your control this turn.\nWhenever another creature you control dies, put a +1/+1 counter on Gimli. When this ability resolves for the third time this turn, Gimli fights up to one target creature you don't control.")
SYR_VONDAM = dict(name="Syr Vondam, Sunstar Exemplar", mana_cost="{W}{B}",
    type_line="Legendary Creature — Human Knight", power="2", toughness="2", colors=("B", "W"),
    keywords=frozenset({"menace", "vigilance"}),
    oracle_text="Vigilance, menace\nWhenever another creature you control dies or is put into exile, put a +1/+1 counter on Syr Vondam and you gain 1 life.\nWhen Syr Vondam dies or is put into exile while its power is 4 or greater, destroy up to one target nonland permanent.")
LILIANA = dict(name="Liliana, Heretical Healer // Liliana, Defiant Necromancer", mana_cost="{1}{B}{B}",
    type_line="Legendary Creature — Human Cleric", power="2", toughness="3", colors=("B",),
    layout="transform",
    oracle_text="Lifelink\nWhenever another nontoken creature you control dies, exile Liliana, Heretical Healer, then return her to the battlefield transformed under her owner's control. If you do, create a 2/2 black Zombie creature token.")
ZAHUR = dict(name="Zahur, Glory's Past", mana_cost="{W}{B}",
    type_line="Legendary Creature — Zombie Cat Warrior", power="3", toughness="2", colors=("B", "W"),
    keywords=frozenset({"max speed", "surveil", "start your engines!"}),
    oracle_text="Start your engines! (If you have no speed, it starts at 1. It increases once on each of your turns when an opponent loses life. Max speed is 4.)\nSacrifice another creature: Surveil 1. Activate only once each turn.\nMax speed — Whenever a nontoken creature you control dies, create a tapped 2/2 black Zombie creature token.")
FANTASY_QUEEN = dict(name="The Underworld Fantasy Queen", mana_cost="{2}{B}",
    type_line="Legendary Creature — God", power="3", toughness="3", colors=("B",),
    oracle_text="As The Underworld Fantasy Queen enters, it becomes spring.\nAt the beginning of your upkeep, the next season arrives.\nSpring — Whenever Her Majesty enters or attacks, you may sacrifice another creature. If you do, draw a card.\nSummer — Whenever a creature an opponent controls dies, put a +1/+1 counter on Her Majesty.\nFall — Whenever another creature dies, target opponent loses 1 life and you gain 1 life.\nWinter — Her Majesty can't attack or block.")
PYROCLASM = dict(name="Pyroclasm", mana_cost="{1}{R}", type_line="Sorcery",
    oracle_text="Pyroclasm deals 2 damage to each creature.")


UGLUK = dict(name="Uglúk of the White Hand", mana_cost="{2}{B}{R}",
    type_line="Legendary Creature — Orc Soldier", power="3", toughness="3", colors=("B", "R"),
    oracle_text="Whenever another creature you control dies, put a +1/+1 counter on Uglúk. If that creature was a Goblin or Orc, put two +1/+1 counters on Uglúk instead.")
BHAAL = dict(name="Bhaal, Lord of Murder", mana_cost="{2}{B}{R}{G}",
    type_line="Legendary Creature — God", power="4", toughness="4", colors=("B", "G", "R"),
    keywords=frozenset({"goad"}),
    oracle_text="As long as your life total is less than or equal to half your starting life total, Bhaal has indestructible.\nWhenever another nontoken creature you control dies, put a +1/+1 counter on target creature and goad it.")
SLURRK = dict(name="Slurrk, All-Ingesting", mana_cost="{5}{G}",
    type_line="Legendary Creature — Ooze", power="0", toughness="0", colors=("G",),
    keywords=frozenset({"partner"}),
    oracle_text="Slurrk enters with five +1/+1 counters on it.\nWhenever Slurrk or another creature you control dies, if it had a +1/+1 counter on it, put a +1/+1 counter on each creature you control that has a +1/+1 counter on it.\nPartner (You can have two commanders if both have partner.)")


CASS = dict(name="Cass, Hand of Vengeance", mana_cost="{2}{R}{W}",
    type_line="Legendary Creature — Human Ranger", power="4", toughness="3", colors=("R", "W"),
    keywords=frozenset({"vigilance"}),
    oracle_text="Vigilance\nWhenever Cass or another creature you control dies, if it was enchanted or equipped, return any number of Aura cards that were attached to it from your graveyard to the battlefield attached to target creature, then attach any number of Equipment that were attached to it to that creature.")


# Counters on a TARGET creature or on each creature you control need a creature left
# standing too: after Wrath of God there is none (Bhaal, Slurrk, Reyhan); so does Cass's
# re-attach "to target creature".
@pytest.mark.parametrize("spec", [THANOS, KRESH, GIMLI, LILIANA, UGLUK, BHAAL, SLURRK, REYHAN,
                                  CASS])
def test_must_survive_death_payoff_is_not_paid_by_a_wipe_that_kills_it(make_card, spec):
    # Counters on itself (or exiling itself to transform) need the commander on the
    # battlefield when the trigger resolves; Wrath of God kills it alongside the others.
    lens = build_lens([make_card(**spec)])
    assert DEATH in lens.kinds
    assert lens.facts_for(make_card(**WRATH)).empty
    # A sacrifice outlet keeps the commander alive: still a payoff.
    assert lens.facts_for(make_card(**VISCERA)).payoff_kind == DEATH


def test_must_survive_death_payoff_keeps_a_wipe_it_survives(make_card):
    # Pyroclasm's 2 damage leaves 3/3 Thanos standing to take the counters.
    f = build_lens([make_card(**THANOS)]).facts_for(make_card(**PYROCLASM))
    assert f.payoff_kind == DEATH


def test_death_payoff_with_value_off_the_commander_keeps_the_wipe(make_card):
    # Syr Vondam's "and you gain 1 life" pays off even when she dies too; Meren's experience
    # counters are on the player.
    assert build_lens([make_card(**SYR_VONDAM)]).facts_for(make_card(**WRATH)).payoff_kind == DEATH
    assert build_lens([make_card(**MEREN)]).facts_for(make_card(**WRATH)).payoff_kind == DEATH


@pytest.mark.parametrize("spec", [ZAHUR, FANTASY_QUEEN])
def test_state_gated_death_trigger_is_not_a_death_payoff(make_card, spec):
    # "Max speed —" and a season ("Fall —") gate the trigger on a state the deck may not be
    # in: honest under-count, no kind.
    assert DEATH not in build_lens([make_card(**spec)]).kinds
