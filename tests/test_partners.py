"""The command zone can hold TWO cards, and its colour identity is the union.

`build_commander_profile` and `compute_stats` used to read the lead card alone. That is not
an approximation — a partner pair is a different deck. Tymna the Weaver (BW) beside
Thrasios, Triton Hero (GU) is BGUW, and `deck_quality.assess_colors` filters a deck's mana
sources by the identity it is handed, so half an identity discards real sources.

Measured over corpus/decks before the fix (33 of 499 decks, 6.6%, have 2+ commanders):

    Sam, Loyal Attendant  + Frodo         solo GW -> "short 15 BLACK"   deck holds 32 B
    Esior, Wardwing       + Ardenn        solo U  -> "short 15 WHITE"   deck holds 19 W
    Flaming Fist          + Wilson        solo W  -> "short 15 GREEN"   deck holds 21 G

Every one flipped from ok=False to ok=True once the union was used, so this was a pure
false alarm shown to the user about a deck that was fine.

Offline: no network, no data/ directory.
"""

from __future__ import annotations

import pytest

import deck_builder
import deck_quality
from commander_analysis import build_commander_profile, command_zone_identity


def _card(name, ci, oracle="", type_line="Legendary Creature — Human", mana="{1}{W}"):
    return {"name": name, "color_identity": list(ci), "oracle_text": oracle,
            "type_line": type_line, "mana_cost": mana, "cmc": 2, "keywords": []}


def _source(name, color):
    """A basic-style land producing one colour."""
    return {"name": name, "type_line": f"Basic Land — {name}", "mana_cost": "",
            "cmc": 0, "oracle_text": "", "produced_mana": [color],
            "color_identity": [color]}


def _spell(name, mana, ci):
    return {"name": name, "type_line": "Creature — Human", "mana_cost": mana,
            "cmc": 2, "oracle_text": "", "color_identity": list(ci)}


# ── identity ─────────────────────────────────────────────────────────────────────

def test_identity_is_the_union_of_the_zone():
    tymna = _card("Tymna the Weaver", "BW")
    thrasios = _card("Thrasios, Triton Hero", "GU")
    assert command_zone_identity(tymna, [thrasios]) == ["B", "G", "U", "W"]


def test_identity_without_partners_is_unchanged():
    tymna = _card("Tymna the Weaver", "BW")
    assert command_zone_identity(tymna, None) == ["B", "W"]
    assert command_zone_identity(tymna, []) == ["B", "W"]


def test_identity_tolerates_a_missing_key():
    assert command_zone_identity({"name": "X"}, [{"name": "Y"}]) == []


def test_profile_unions_the_identity():
    p = build_commander_profile(_card("Esior", "U"), [_card("Ardenn", "W")])
    assert p.color_identity == ["U", "W"]
    assert p.color_id_str == "UW"


# ── themes ───────────────────────────────────────────────────────────────────────

def test_profile_unions_themes_with_the_lead_first():
    """A pair's plan comes from BOTH halves, but the lead stays first so the theme split
    still weights the commander the deck is named for."""
    lead = _card("Lead", "R", oracle="Other Goblin creatures you control get +1/+1.")
    partner = _card("Partner", "W",
                    oracle="Whenever you gain life, draw a card.")
    p = build_commander_profile(lead, [partner])
    assert p.themes[0] == "tribal_goblins"
    assert "lifegain" in p.themes


def test_a_theme_on_both_halves_is_not_duplicated():
    lead = _card("Lead", "R", oracle="Other Goblin creatures you control get +1/+1.")
    partner = _card("Partner", "R", oracle="Goblin creatures you control get +1/+0.")
    p = build_commander_profile(lead, [partner])
    assert p.themes.count("tribal_goblins") == 1


def test_a_themeless_lead_can_be_given_a_plan_by_its_partner():
    """Tymna and Falthis detect nothing on their own; the other half carries the deck."""
    lead = _card("Falthis", "B", oracle="Commanders you control have menace and deathtouch.")
    partner = _card("Partner", "W",
                    oracle="Whenever you cast an enchantment spell, draw a card.")
    assert build_commander_profile(lead).themes == []
    assert build_commander_profile(lead, [partner]).themes == ["enchantress"]


# ── the false alarm ──────────────────────────────────────────────────────────────

def _partner_deck():
    """A two-colour deck whose SECOND colour comes entirely from the partner's half."""
    deck = [_source("Plains", "W") for _ in range(18)]
    deck += [_source("Forest", "G") for _ in range(18)]
    deck += [_spell(f"White {i}", "{W}{W}", "W") for i in range(6)]
    deck += [_spell(f"Green {i}", "{G}{G}", "G") for i in range(6)]
    return deck


def test_half_an_identity_reports_a_false_shortfall():
    """Pins the DEFECT, so the fix below cannot silently regress."""
    solo = _card("Flaming Fist", "W")
    verdict = deck_quality.assess_colors(_partner_deck(), solo)
    assert not verdict.ok
    assert "G" in verdict.short          # 18 Forests in the deck, reported as missing


def test_the_command_zone_identity_clears_it():
    solo = _card("Flaming Fist", "W")
    partner = _card("Wilson, Refined Grizzly", "G")
    both = dict(solo, color_identity=command_zone_identity(solo, [partner]))
    verdict = deck_quality.assess_colors(_partner_deck(), both)
    assert verdict.ok
    assert verdict.short == {}
    assert verdict.sources.get("G", 0) >= 18


# ── compute_stats wiring ─────────────────────────────────────────────────────────

def test_compute_stats_accepts_the_zone_and_fixes_the_quality_block():
    solo = _card("Flaming Fist", "W")
    partner = _card("Wilson, Refined Grizzly", "G")
    deck = _partner_deck()
    without = deck_builder.compute_stats(solo, deck)
    with_zone = deck_builder.compute_stats(solo, deck, partners=[partner])
    assert without["quality"]["colors"]["ok"] is False
    assert with_zone["quality"]["colors"]["ok"] is True


def test_compute_stats_does_not_mutate_the_caller_s_commander():
    """The commander dict is shared with the render and export paths; widening its
    identity in place would silently change what those consider on-colour."""
    solo = _card("Flaming Fist", "W")
    deck_builder.compute_stats(solo, _partner_deck(),
                               partners=[_card("Wilson", "G")])
    assert solo["color_identity"] == ["W"]


@pytest.mark.parametrize("partners", [None, []])
def test_compute_stats_without_partners_is_unchanged(partners):
    solo = _card("Flaming Fist", "W")
    deck = _partner_deck()
    assert deck_builder.compute_stats(solo, deck, partners=partners) == \
           deck_builder.compute_stats(solo, deck)
