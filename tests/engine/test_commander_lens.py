"""Commander lens: how the commander changes what a card does (offline, synthetic cards)."""

import pytest

from mythgauntlet.semantics.commander_lens import build_lens, admits

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
