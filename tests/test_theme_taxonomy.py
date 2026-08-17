"""The theme taxonomy spans THREE structures that must stay in lock-step.

`commander_analysis.THEME_PATTERNS` detects a theme from the COMMANDER's oracle text,
`commander_analysis.THEME_SYNERGY_QUERIES` fills its slots from Scryfall, and
`theme_match.THEME_RULES` reproduces that query locally for strict/collection mode. A theme
present in one and missing from another is silent: the slot either never fills or fills
from the wrong pool.

Also pins the three themes added 2026-08-14 to close measured holes — see
`test_deck_themes.py` for the base-rate machinery that keeps them from firing on noise.

Offline: patterns and rules are plain text scans.
"""

from __future__ import annotations

import pytest

import deck_themes
import theme_match
from commander_analysis import THEME_LABELS, THEME_PATTERNS, THEME_SYNERGY_QUERIES

NEW_THEMES = ("face_down", "sagas", "impulse")


def test_all_four_structures_agree():
    """The lock-step invariant. A theme in one structure and not the others is silent."""
    patterns = set(THEME_PATTERNS)
    queries = set(THEME_SYNERGY_QUERIES)
    local = set(theme_match.THEMES)
    rules = set(theme_match.THEME_RULES)
    assert patterns == queries, f"PATTERNS vs QUERIES differ: {patterns ^ queries}"
    assert local == queries, f"theme_match.THEMES vs QUERIES differ: {local ^ queries}"
    assert local <= rules, f"THEMES with no THEME_RULES entry: {local - rules}"


def test_every_theme_has_a_display_label():
    missing = set(THEME_SYNERGY_QUERIES) - set(THEME_LABELS)
    assert not missing, f"themes with no UI label: {sorted(missing)}"


def test_base_rate_covers_the_new_themes():
    """Adding a theme without regenerating BASE_RATE leaves it judged on MIN_STRONG alone.

    Regenerate with `python scripts/theme_base_rates.py`.
    """
    for theme in NEW_THEMES:
        assert theme in deck_themes.BASE_RATE, f"{theme} missing from BASE_RATE"


@pytest.mark.parametrize("theme", NEW_THEMES)
def test_new_themes_are_precise_not_catch_alls(theme):
    """All three sit near 1% of the card pool.

    That matters: `voltron_combat` at 19.35% is what made an absolute count meaningless.
    A new theme landing in that range would need the same scrutiny.
    """
    assert deck_themes.BASE_RATE[theme] < 0.02


# ── the reproducer ──────────────────────────────────────────────────────────────

def test_kadena_detects_face_down():
    """THE REPRODUCER. Kadena's entire text is about face-down creatures and the taxonomy
    had no entry for the mechanic, so she detected ZERO themes and her ~20 theme slots
    fell through to generic goodstuff."""
    kadena = ("The first face-down creature spell you cast each turn costs {3} less to "
              "cast. Whenever a face-down creature you control enters, draw a card.")
    hits = [t for t, pats in THEME_PATTERNS.items()
            if any(p in kadena.lower() for p in pats)]
    assert "face_down" in hits


@pytest.mark.parametrize("theme,card,expected_strong", [
    ("face_down", {"name": "Stratus Dancer", "type_line": "Creature — Djinn Monk",
                   "oracle_text": "Flying\nMegamorph {1}{U}"}, True),
    ("face_down", {"name": "Den Protector", "type_line": "Creature — Human Rogue",
                   "oracle_text": "Megamorph {1}{G}"}, True),
    ("face_down", {"name": "Plain Bear", "type_line": "Creature — Bear",
                   "oracle_text": "Trample"}, False),
    ("sagas", {"name": "The Eldest Reborn", "type_line": "Enchantment — Saga",
               "oracle_text": "(As this Saga enters and after your draw step, add a lore "
                              "counter.)"}, True),
    ("impulse", {"name": "Jeska's Will", "type_line": "Sorcery",
                 "oracle_text": "Exile the top three cards of your library. You may play "
                                "them this turn."}, True),
    ("impulse", {"name": "Divination", "type_line": "Sorcery",
                 "oracle_text": "Draw two cards."}, False),
])
def test_local_rules_score_the_right_cards(theme, card, expected_strong):
    """theme_match must reproduce the Scryfall query, or strict mode fills the slot from
    a different pool than a normal build would."""
    got = theme_match.theme_score(card, theme) == theme_match.STRONG
    assert got is expected_strong


def test_impulse_does_not_swallow_plain_card_draw():
    """`impulse` is playing cards you do not own yet — deliberately NOT "you may play",
    which would match every land-drop effect in Magic."""
    assert "you may play" not in THEME_PATTERNS["impulse"]
    ramp = {"name": "Explore", "type_line": "Sorcery",
            "oracle_text": "You may play an additional land this turn. Draw a card."}
    assert theme_match.theme_score(ramp, "impulse") == theme_match.NO_MATCH
