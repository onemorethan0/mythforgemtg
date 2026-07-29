"""Closed-form mana-base math (offline, no card data)."""

from mythgauntlet.ratings import manabase
from mythgauntlet.ratings.manabase import (
    cards_seen,
    hypergeom_at_least,
    sources_needed,
)


def test_hypergeom_matches_known_values():
    # Degenerate cases first: they anchor the formula.
    assert hypergeom_at_least(99, 0, 7, 1) == 0.0        # no sources -> impossible
    assert hypergeom_at_least(99, 99, 7, 1) == 1.0       # all sources -> certain
    assert hypergeom_at_least(99, 40, 7, 0) == 1.0       # needing none -> certain
    assert hypergeom_at_least(99, 5, 7, 6) == 0.0        # can't draw more than exist

    # P(at least one of 1 success in 1 draw from 2) = 1/2, exactly.
    assert hypergeom_at_least(2, 1, 1, 1) == 0.5
    # Monotone in sources: more sources never hurts.
    probs = [hypergeom_at_least(99, k, 10, 2) for k in range(5, 45, 5)]
    assert probs == sorted(probs)


def test_cards_seen_play_vs_draw():
    assert cards_seen(1) == 7                 # opening hand, on the play
    assert cards_seen(3) == 9                 # +1 per turn after the first
    assert cards_seen(3, on_play=False) == 10  # on the draw, one more


def test_sources_needed_is_the_conservative_floor():
    """This module does NOT reproduce Karsten's table, and that is intentional.

    His published numbers assume a mulligan strategy; a one-shot hypergeometric has no
    such escape valve and therefore always demands MORE. Single-pip nearly agrees (13 vs
    14); multi-pip diverges, which is exactly where mulliganing rescues a colour-screwed
    hand. Locking the direction here so nobody later "fixes" this to match the table and
    silently makes the bound unsound.
    """
    assert sources_needed(60, 1, 2, on_play=False) == 13   # Karsten: 14
    assert sources_needed(60, 2, 2, on_play=False) > 18    # Karsten: 18
    assert sources_needed(60, 3, 3, on_play=False) > 21    # Karsten: 21

    # More pips or an earlier turn can only raise the requirement.
    assert sources_needed(99, 2, 3) > sources_needed(99, 1, 3)
    assert sources_needed(99, 2, 2) > sources_needed(99, 2, 4)

    # The returned count actually clears the target it claims to.
    for pips, turn in ((1, 2), (2, 3), (3, 5)):
        n = sources_needed(99, pips, turn)
        assert hypergeom_at_least(99, n, cards_seen(turn), pips) >= manabase.TARGET_PROBABILITY


def test_analyze_finds_the_underweighted_color(make_card):
    """A Golgari deck heavy on green and thin on black should indict BLACK, not green."""
    forest = make_card("Forest", type_line="Basic Land — Forest")
    swamp = make_card("Swamp", type_line="Basic Land — Swamp")
    object.__setattr__(forest, "produced_mana", ("G",))
    object.__setattr__(swamp, "produced_mana", ("B",))
    bomb = make_card("Lolth, Spider Queen", mana_cost="{3}{B}{B}",
                     type_line="Legendary Planeswalker — Lolth")
    dork = make_card("Llanowar Elves", mana_cost="{G}", type_line="Creature — Elf Druid")

    report = manabase.analyze([(forest, 38), (swamp, 14), (bomb, 1), (dork, 1)])
    assert report.sources["G"] == 38 and report.sources["B"] == 14

    worst = report.worst[0]
    assert worst.color == "B", "the thin colour should surface first"
    assert worst.pips == 2 and worst.shortfall > 0
    assert 0.0 < worst.probability < 0.9

    # Single green pip is comfortably supported.
    green = next(r for r in report.requirements if r.color == "G" and r.pips == 1)
    assert green.met and green.probability > 0.95

    # Consistency is the MEAN probability, so one bad colour can't read as total failure.
    assert 0.0 < report.consistency < 1.0


def test_analyze_ignores_hybrid_and_colorless(make_card):
    """Hybrid pips don't bind a single colour; colourless costs create no demand."""
    rock = make_card("Sol Ring", mana_cost="{1}", type_line="Artifact")
    hybrid = make_card("Boros Charm", mana_cost="{R/W}{R/W}", type_line="Instant")
    report = manabase.analyze([(rock, 1), (hybrid, 1)])
    assert report.requirements == []
    assert report.consistency == 1.0
