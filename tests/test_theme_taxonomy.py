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

import commander_analysis
import deck_themes
import theme_match
from commander_analysis import THEME_LABELS, THEME_PATTERNS, THEME_SYNERGY_QUERIES
from deck_builder import ROLE_QUERIES

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


# ── query precedence ─────────────────────────────────────────────────────────────

def _has_top_level_or(query: str) -> bool:
    """True when an ` OR ` sits at paren depth 0."""
    depth = 0
    for i, ch in enumerate(query):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and query[i:i + 4] == " OR ":
            return True
    return False


@pytest.mark.parametrize("name,query", sorted(THEME_SYNERGY_QUERIES.items()))
def test_theme_query_has_no_top_level_or(name, query):
    """A top-level OR silently un-filters the first branch.

    DeckBuilder appends `id<=WUBRG`, `legal:commander` and `-type:land` to every one of
    these, and Scryfall's OR binds LOOSER than the implicit AND. So
    `otag:sacrifice-outlet OR o:"..." id<=BG legal:commander` parses as
    `otag:sacrifice-outlet` OR `(everything else AND the filters)` — the first branch keeps
    no colour filter, no legality filter, not even `-type:land`.

    Measured: a Shelob (BG) build drafted Professional Face-Breaker ({2}{R}) out of the
    aristocrats query, which then demanded 14 red sources the deck could never have and
    reported the manabase as broken. `tokens` and `counters` had the same shape.
    """
    assert not _has_top_level_or(query), (
        f"{name}: wrap the whole query in parentheses, or the appended colour/legality "
        f"filters apply to the last branch only — {query}"
    )


@pytest.mark.parametrize("name,query", sorted(ROLE_QUERIES.items()))
def test_role_query_has_no_top_level_or(name, query):
    """Same hazard, same fix, for the functional-role queries."""
    assert not _has_top_level_or(query), f"{name}: needs wrapping parentheses — {query}"


# ── a card's own NAME is not a payoff ───────────────────────────────────────────

_SELF_NAME_CASES = [
    # (card name, oracle text, tribe that must NOT be detected)
    ("The Unknown Wizard", "When this creature enters, draw a card.", "tribal_wizards"),
    ("Winter Soldier, Icy Assassin",
     "Vigilance, menace\nWinter Soldier gets +2/+0 for each Equipment attached to it.",
     "tribal_soldiers"),
    ("Green Goblin, Revenant",
     "Flying, deathtouch\nWhenever Green Goblin attacks, discard a card.", "tribal_goblins"),
    ("Skanos, Dragon Vassal",
     "Whenever Skanos, Dragon Vassal attacks, another target attacking creature gets +1/+1.",
     "tribal_dragons"),
    ("Questing Beast",
     "Vigilance, deathtouch, haste\nQuesting Beast can't be blocked by creatures with power 2 "
     "or less.", "tribal_beasts"),
    # Substring matches inside an ordinary word, not even a tribe reference:
    ("Michelangelo, Game Master", "When Michelangelo enters, create a Turtle token.",
     "tribal_angels"),
    ("Desdemona, Freedom's Edge", "Whenever Desdemona attacks, you gain 1 life.",
     "tribal_demons"),
]


@pytest.mark.parametrize("name,oracle,tribe", _SELF_NAME_CASES,
                         ids=[c[0] for c in _SELF_NAME_CASES])
def test_a_cards_own_name_is_not_a_tribal_payoff(name, oracle, tribe):
    """Magic prints a card's name in its own rules text — that is not a payoff.

    Measured over `data/cards_slim.json`: **39 legendary-creature tribal detections fired on
    the name alone**, and every one inspected was wrong. Worse, `THEME_PATTERNS` matches by
    SUBSTRING, so "Michelangelo" registered as Angel tribal and "Desdemona" as Demon tribal.
    Each false tribal spends a commander's ~20 theme slots on a tribe with no payoff, which is
    the same defect `_detect_themes` already refuses the TYPE LINE to prevent.
    """
    detected = commander_analysis._detect_themes({"name": name, "oracle_text": oracle})
    assert tribe not in detected, f"{name!r} read as {tribe} off its own name: {detected}"


def test_real_tribal_payoffs_still_detect():
    """The name strip must not cost a genuine payoff — the guard that makes the fix safe."""
    keep = [
        ("Slinza, the Spiked Stampede",
         "Beast spells you cast cost {2} less to cast.\nEach other Beast creature you control "
         "enters with an additional +1/+1 counter on it.", "tribal_beasts"),
        ("Sliver Overlord",
         "{3}: Search your library for a Sliver card.\n{2}: Gain control of target Sliver.",
         "tribal_slivers"),
        ("Goblin Chieftain",
         "Other Goblin creatures you control get +1/+1 and have haste.", "tribal_goblins"),
    ]
    for name, oracle, tribe in keep:
        detected = commander_analysis._detect_themes({"name": name, "oracle_text": oracle})
        assert tribe in detected, f"{name!r} lost {tribe}: {detected}"


# ── no pattern may quietly stop matching anything ───────────────────────────────

# Patterns that match ZERO of the ~34k cards in `data/cards_slim.json`. They are harmless on
# their own — a dead pattern simply never fires — but the CLASS is not harmless: Magic
# re-templates its wording, Scryfall rewrites old cards to the modern Oracle text, and a
# theme whose patterns all die becomes silently undetectable. That already happened to five
# `theme_match` rules, and `enchantress` was carrying "enchantment enters the battlefield",
# which matched **zero** cards while the modern phrasing matched 63.
#
# This is a RATCHET, not a wish-list: a newly-dead pattern fails the test, and so does fixing
# one without removing it here. Regenerate by running the sweep in the test below.
KNOWN_DEAD_PATTERNS = {
    ("tribal_humans", "nonhuman"),
    ("reanimator", "reanimate"),                 # a card NAME, never rules text
    ("reanimator", "from a graveyard to the battlefield"),
    ("enchantress", "whenever an enchantment enters"),
    ("lifegain", "each life you gain"),
    ("lifegain", "whenever you gain 1 or more life"),
    ("etb", "exile them, then return"),
    ("etb", "exile that card, then return"),
    ("etb", "flicker"),                          # flavour word, never printed in rules text
    ("energy", "gain {e}"),                      # energy is "you GET {E}", not "gain"
    ("theft", "under your control until end of turn"),
}


def _card_pool():
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data" / "cards_slim.json"
    if not p.exists():
        pytest.skip("needs data/cards_slim.json (absent in CI)")
    return [(c.get("oracle_text") or "").lower()
            for c in json.loads(p.read_text(encoding="utf-8"))["cards"]]


def test_no_theme_has_all_of_its_patterns_dead():
    """The failure that actually breaks the app: a theme nothing can trigger.

    A commander with that theme detects nothing, its ~20 theme slots fall through to generic
    goodstuff, and NOTHING reports a problem — the same silent shape as the five dead
    `theme_match` rules.
    """
    texts = _card_pool()
    fully_dead = [
        theme for theme, pats in THEME_PATTERNS.items()
        if not any(any(p in t for t in texts) for p in pats)
    ]
    assert not fully_dead, f"themes with no live pattern at all: {fully_dead}"


def test_the_dead_pattern_set_has_not_grown():
    """Ratchet. A pattern that stops matching anything is a re-templating warning."""
    texts = _card_pool()
    dead = {(theme, p) for theme, pats in THEME_PATTERNS.items() for p in pats
            if not any(p in t for t in texts)}
    new = dead - KNOWN_DEAD_PATTERNS
    fixed = KNOWN_DEAD_PATTERNS - dead
    assert not new, (
        f"pattern(s) newly match nothing — Magic probably re-templated the wording: {sorted(new)}")
    assert not fixed, (
        f"these are alive again; remove them from KNOWN_DEAD_PATTERNS: {sorted(fixed)}")


# ── the LEAD theme decides 70% of the theme package ─────────────────────────────

def test_a_broad_theme_never_leads_over_a_specific_one():
    """`_theme_slot_split` gives the FIRST detected theme 70% of the ~20-card package.

    Returning themes in `THEME_PATTERNS` order made that lead depend on where a theme happens
    to sit in a dict literal. Widening `etb` to the modern "creature you control enters"
    templating gave **Kadena, Slinking Sorcerer** a second theme, and because `etb` is declared
    earlier it took the lead from `face_down` — the mechanic the whole card is about. Measured
    on `builder_bench`: on-theme cards 21 -> 8, synergy 40.5 -> 24.5.
    """
    kadena = {"name": "Kadena, Slinking Sorcerer",
              "oracle_text": "The first face-down creature spell you cast each turn costs {3} "
                             "less to cast.\nWhenever a face-down creature you control enters, "
                             "draw a card."}
    detected = commander_analysis._detect_themes(kadena)
    assert "face_down" in detected and "etb" in detected, detected
    assert detected[0] == "face_down", (
        f"the generic theme took the lead from the specific one: {detected}")


def test_every_broad_theme_is_a_real_theme():
    """A typo in `BROAD_THEMES` would silently demote nothing."""
    unknown = commander_analysis.BROAD_THEMES - set(THEME_PATTERNS)
    assert not unknown, f"BROAD_THEMES names themes that do not exist: {sorted(unknown)}"


def test_detect_themes_is_deterministic():
    """Two calls must agree — the sort has to be total, not dependent on set iteration."""
    card = {"name": "X", "oracle_text": "Whenever a creature you control enters, create a "
                                        "1/1 token. Put a +1/+1 counter on it."}
    assert commander_analysis._detect_themes(card) == commander_analysis._detect_themes(card)
