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


def test_fetchlands_count_as_colour_sources(make_card, forest):
    """A fetchland taps for nothing, but it is still a source for what it finds.

    Scryfall gives every fetchland `produced_mana == []` — correctly, they tap for no
    mana — so counting only `produced_mana` scored all of them as ZERO colour sources.
    That fed the one number the Bracket 1 vs 2 gate reads, and the common cases are the
    BUDGET fetches casual decks actually run.
    """
    island = make_card("Island", type_line="Basic Land — Island", produced_mana=("U",))
    # Typed fetch: real oracle text says "a Forest or Island CARD" — not "land card".
    misty = make_card(
        "Misty Rainforest", type_line="Land", produced_mana=(),
        oracle_text=("{T}, Pay 1 life, Sacrifice this land: Search your library for a "
                     "Forest or Island card, put it onto the battlefield, then shuffle."),
    )
    # Generic fetch: can only find a basic, so it counts only for the deck's basics.
    wilds = make_card(
        "Evolving Wilds", type_line="Land", produced_mana=(),
        oracle_text=("{T}, Sacrifice this land: Search your library for a basic land card, "
                     "put it onto the battlefield tapped, then shuffle."),
    )
    counts = manabase.count_sources([(forest, 10), (island, 10), (misty, 4), (wilds, 4)])
    assert counts["G"] == 18   # 10 Forest + 4 Misty + 4 Wilds
    assert counts["U"] == 18
    assert counts["W"] == 0    # nothing produces or finds white


def test_generic_fetch_only_counts_colours_the_deck_has_basics_in(make_card):
    """An Evolving Wilds in a deck with no basic Swamp is not a black source."""
    island = make_card("Island", type_line="Basic Land — Island", produced_mana=("U",))
    tower = make_card("Command Tower", type_line="Land", produced_mana=("W", "U", "B", "R", "G"))
    wilds = make_card(
        "Evolving Wilds", type_line="Land", produced_mana=(),
        oracle_text=("{T}, Sacrifice this land: Search your library for a basic land card, "
                     "put it onto the battlefield tapped, then shuffle."),
    )
    counts = manabase.count_sources([(island, 10), (tower, 1), (wilds, 4)])
    assert counts["U"] == 15   # 10 Island + Tower + 4 Wilds (it can find an Island)
    assert counts["B"] == 1    # Tower only — no basic Swamp for Wilds to find


def test_non_fetch_lands_are_not_credited(make_card):
    """Graveyard-hate/other non-search effects don't count, and a NON-LAND permanent that
    fetches a land is never itself credited as a mana source (fetched_colors only credits
    LAND permanents — see test_land_tutor_to_hand_counts_as_a_source below for the
    land-to-hand case, which a land permanent DOES get credited for)."""
    bog = make_card("Bojuka Bog", type_line="Land", produced_mana=("B",),
                    oracle_text="When Bojuka Bog enters, exile target player's graveyard.")
    scout = make_card("Expedition Map", type_line="Artifact", produced_mana=(),
                      oracle_text="{2}, {T}, Sacrifice: Search your library for a land card, "
                                  "put it into your hand, then shuffle.")
    counts = manabase.count_sources([(bog, 1), (scout, 1)])
    assert counts["B"] == 1                       # Bog's own mana, nothing extra
    assert sum(counts.values()) == 1              # Map is an artifact, not a land, itself


def test_land_tutor_to_hand_counts_as_a_source(make_card):
    """A land permanent that searches for a land and puts it into HAND (Edge of Autumn's
    class) is still real colour fixing -- just a turn later than a battlefield fetch -- and
    must be credited the same way, not treated as a dead search."""
    forest = make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",))
    edge = make_card(
        "Edge of Autumn", type_line="Land", produced_mana=(),
        oracle_text=("When Edge of Autumn enters, if you control three or more other "
                     "permanents, sacrifice it.\nWhen you sacrifice Edge of Autumn or it "
                     "dies, search your library for a basic land card, reveal it, put it "
                     "into your hand, then shuffle."),
    )
    counts = manabase.count_sources([(forest, 10), (edge, 1)])
    assert counts["G"] == 11   # 10 Forest + Edge of Autumn (finds the only basic in the deck)
