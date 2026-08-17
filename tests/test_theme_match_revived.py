"""The five theme_match rules that matched almost nothing, and the guard against a repeat.

`THEME_SYNERGY_QUERIES` leads several themes with an `otag:` oracle tag. An oracle tag has
no local equivalent, so `theme_match` — which reproduces those queries for strict/collection
mode — was left holding only the query's LITERAL fallback, and those literals match almost
no printed card. Measured over the 34,846-card store before the fix:

    landfall        1 card      "whenever a land enters the battlefield under your control"
    chaos          22           needs "each player" AND "random"
    aristocrats    34           "whenever a creature you control dies"
    etb            37           "when this enters"
    draw_matters   50           "whenever you draw a card"

Consequences: strict mode could not fill those theme packages at all (they fell through to
goodstuff), and `deck_themes` could never detect those archetypes in a deck.

Written from the card text, not the implementation: every fixture carries VERBATIM oracle
text, because a rule tested against text retyped from memory tests a card that doesn't
exist. Offline.
"""

from __future__ import annotations

import pytest

import deck_themes
import theme_match
from theme_match import NO_MATCH, STRONG, theme_score


def _c(name, type_line, oracle):
    return {"name": name, "type_line": type_line, "oracle_text": oracle}


# ── landfall ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("card", [
    _c("Lotus Cobra", "Creature — Snake",
       "Landfall — Whenever a land you control enters, create a Treasure token."),
    _c("Tatyova, Benthic Druid", "Legendary Creature — Merfolk Druid",
       "Whenever a land you control enters, you gain 1 life and draw a card."),
    _c("Avenger of Zendikar", "Creature — Elemental",
       "Landfall — Whenever a land you control enters, put a +1/+1 counter on each Plant "
       "creature you control."),
])
def test_landfall_matches_real_landfall_cards(card):
    """The rule scored ONE card in the whole store; every one of these was NO_MATCH."""
    assert theme_score(card, "landfall") == STRONG


def test_landfall_still_accepts_the_pre_2024_wording():
    old = _c("Old Templating", "Creature — Elemental",
             "Whenever a land enters the battlefield under your control, draw a card.")
    assert theme_score(old, "landfall") == STRONG


def test_landfall_does_not_match_a_plain_creature():
    assert theme_score(_c("Grizzly Bears", "Creature — Bear", "Trample"), "landfall") == NO_MATCH


# ── aristocrats ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("card", [
    _c("Blood Artist", "Creature — Vampire",
       "Whenever this creature or another creature dies, target player loses 1 life and "
       "you gain 1 life."),
    _c("Zulaport Cutthroat", "Creature — Human Rogue",
       "Whenever this creature or another creature you control dies, each opponent loses "
       "1 life and you gain 1 life."),
])
def test_aristocrats_matches_the_death_payoff(card):
    assert theme_score(card, "aristocrats") == STRONG


def test_aristocrats_matches_the_sacrifice_outlet():
    """`otag:sacrifice-outlet` was the query's FIRST alternative — the outlet is half the
    archetype, and the literal fallback covered none of it."""
    assert theme_score(
        _c("Viscera Seer", "Creature — Vampire Wizard", "Sacrifice a creature: Scry 1."),
        "aristocrats") == STRONG


def test_aristocrats_does_not_match_plain_removal():
    """"Sacrifice a creature" needs the COLON to read as an activated cost rather than a
    one-shot spell that happens to say the words."""
    assert theme_score(
        _c("Murder", "Instant", "Destroy target creature."), "aristocrats") == NO_MATCH


# ── etb: payoffs only ────────────────────────────────────────────────────────────

def test_etb_matches_a_payoff():
    assert theme_score(
        _c("Payoff", "Artifact", "Whenever a creature you control enters, draw a card."),
        "etb") == STRONG


def test_etb_matches_repeatable_blink():
    assert theme_score(
        _c("Restoration Angel", "Creature — Angel",
           "Flash\nFlying\nWhen this creature enters, exile it, then return that card to "
           "the battlefield under its owner's control."),
        "etb") == STRONG


def test_etb_does_NOT_match_a_card_that_merely_has_an_enters_trigger():
    """THE LOAD-BEARING CASE. Mulldrifter's real wording is "When this creature enters",
    which the old literal missed — but widening to match it would be WORSE than the bug.
    Most creatures in Magic have an enters trigger, so the theme would fire on a random
    pile the way voltron_combat (19.35% of all cards) does. `etb` means the cards that
    CARE about entering."""
    assert theme_score(
        _c("Mulldrifter", "Creature — Elemental",
           "Flying\nWhen this creature enters, draw two cards.\nEvoke {2}{U}"),
        "etb") == NO_MATCH


# ── draw_matters / chaos ─────────────────────────────────────────────────────────

def test_draw_matters_matches_the_group_slug_half():
    """Nekusar is the canonical draw-matters commander; its wording is "a PLAYER draws"."""
    assert theme_score(
        _c("Nekusar, the Mindrazer", "Legendary Creature — Zombie Wizard",
           "Whenever a player draws a card, Nekusar, the Mindrazer deals 1 damage to that "
           "player."),
        "draw_matters") == STRONG


@pytest.mark.parametrize("card", [
    _c("Krark's Thumb", "Legendary Artifact",
       "If you would flip a coin, instead flip two coins and ignore one."),
    _c("Grenzo, Havoc Raiser", "Legendary Creature — Goblin Rogue",
       "Whenever a creature you control deals combat damage to a player, you may goad "
       "target creature."),
])
def test_chaos_matches_coins_and_goad(card):
    """`chaos` is the one theme whose SCRYFALL QUERY is broken too — it has no otag: to
    fall back on, only `(o:"each player" o:"random")`, which misses coin flips, voting and
    goad entirely."""
    assert theme_score(card, "chaos") == STRONG


# ── the guard ────────────────────────────────────────────────────────────────────

REVIVED = ("landfall", "aristocrats", "etb", "chaos", "draw_matters")


@pytest.mark.parametrize("theme", REVIVED)
def test_revived_rules_are_not_dead_again(theme):
    """A rule matching a handful of cards in all of Magic is dead, whatever it looks like.

    BASE_RATE is measured over the whole store, so it is the cheap standing check — this
    is what would have caught the original bug.
    """
    cards = deck_themes.BASE_RATE[theme] * 34846
    assert cards > 100, f"{theme} matches only ~{cards:.0f} cards — the rule is dead again"


@pytest.mark.parametrize("theme", REVIVED)
def test_revived_rules_did_not_become_noise(theme):
    """The opposite failure: voltron_combat scores STRONG on 19.35% of every card in Magic
    and fires on randomly drawn piles. A revived rule must not join it."""
    assert deck_themes.BASE_RATE[theme] < 0.02


def test_no_theme_rule_is_dead():
    """Sweep: any theme with NO weak tier whose STRONG rule matches almost nothing is
    unfillable in strict mode and undetectable by deck_themes."""
    dead = []
    for theme in theme_match.THEMES:
        rule = theme_match.THEME_RULES.get(theme, {})
        has_weak = bool(rule.get("weak_subtype") or rule.get("weak_type_contains"))
        if has_weak:
            continue                      # a weak tier keeps the theme fillable
        if deck_themes.BASE_RATE.get(theme, 0.0) * 34846 < 60:
            dead.append(theme)
    assert not dead, f"themes with no weak tier and a near-dead STRONG rule: {dead}"
