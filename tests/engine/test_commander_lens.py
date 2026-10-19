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
    assert lens.facts_for(make_card(**WRATH)).payoff_kind == DEATH
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
    # A triggered (unpaid) mass damage keeps its full credit.
    assert lens.facts_for(make_card(**LAVABRINK)).payoff_treasure == 6
