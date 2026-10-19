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
