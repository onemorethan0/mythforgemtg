"""Resilience honours the commander lens: an indestructible commander survives the injected
destroy wipe (offline, synthetic cards; oracle texts verbatim from the card store)."""

from mythgauntlet.model.deck import Deck, resolve
from mythgauntlet.ratings.analysis import analyze_deck
from mythgauntlet.sim.tier0 import SimConfig, simulate

SMAUG = dict(name="Smaug the Impenetrable", mana_cost="{5}{B}{R}",
    type_line="Legendary Creature — Dragon", power="8", toughness="7",
    color_identity=("B", "R"),
    keywords=frozenset({"flying", "indestructible", "haste", "treasure"}),
    oracle_text="Flying, indestructible, haste\nWhenever Smaug is dealt noncombat damage, create that many Treasure tokens.")

WIPE_TURN = 5


def _mountain(make_card):
    return make_card("Mountain", type_line="Basic Land — Mountain", produced_mana=("R",),
                     color_identity=("R",))


def _swamp(make_card):
    return make_card("Swamp", type_line="Basic Land — Swamp", produced_mana=("B",),
                     color_identity=("B",))


def _smaug_deck(make_card, sol_ring_like):
    """Smaug is the ONLY creature: lands + colourless rocks so it can land before the wipe."""
    smaug = make_card(**SMAUG)
    cards = [(_mountain(make_card), 30), (_swamp(make_card), 30), (sol_ring_like, 39)]
    return smaug, cards


def test_indestructible_commander_keeps_board_after_wipe(make_card, sol_ring_like):
    smaug, cards = _smaug_deck(make_card, sol_ring_like)
    cfg = SimConfig(runs=200, seed=7, turns=8)
    survived = simulate(cards, smaug, cfg, board_wipe_turn=WIPE_TURN, commander_survives_wipe=True)
    wiped = simulate(cards, smaug, cfg, board_wipe_turn=WIPE_TURN, commander_survives_wipe=False)
    early = [i for i, r in enumerate(survived) if r.commander_turn is not None
             and r.commander_turn < WIPE_TURN]
    assert early, "fixture must land Smaug before the wipe in some runs"
    for i in early:
        assert survived[i].board_power_by_turn[WIPE_TURN - 1] >= 8
        assert survived[i].board_creatures_by_turn[WIPE_TURN - 1] == 1
        # Smaug was the only creature: the plain wipe leaves no 8-power board that turn
        assert wiped[i].board_power_by_turn[WIPE_TURN - 1] < 8


def test_flag_off_is_byte_identical(make_card, sol_ring_like):
    smaug, cards = _smaug_deck(make_card, sol_ring_like)
    cfg = SimConfig(runs=100, seed=3, turns=8)
    assert simulate(cards, smaug, cfg, board_wipe_turn=WIPE_TURN) == simulate(
        cards, smaug, cfg, board_wipe_turn=WIPE_TURN, commander_survives_wipe=False)


def test_survival_flag_never_touches_clean_runs(make_card, sol_ring_like):
    smaug, cards = _smaug_deck(make_card, sol_ring_like)
    cfg = SimConfig(runs=60, seed=11, turns=8)
    assert simulate(cards, smaug, cfg) == simulate(cards, smaug, cfg,
                                                   commander_survives_wipe=True)


def test_surviving_dork_commander_keeps_its_own_mana(make_card, forest):
    """An indestructible mana-creature commander keeps its OWN mana source through the wipe;
    without survival the source dies with it."""
    dork = make_card("Indestructible Dork", mana_cost="{G}",
                     type_line="Legendary Creature — Elf Druid", power="1", toughness="1",
                     color_identity=("G",), produced_mana=("G",),
                     keywords=frozenset({"indestructible"}),
                     oracle_text="Indestructible\n{T}: Add {G}.")
    cards = [(forest, 99)]
    cfg = SimConfig(runs=40, seed=5, turns=8)
    kept = simulate(cards, dork, cfg, board_wipe_turn=WIPE_TURN, commander_survives_wipe=True)
    lost = simulate(cards, dork, cfg, board_wipe_turn=WIPE_TURN)
    for k, l in zip(kept, lost, strict=True):
        assert k.commander_turn is not None and k.commander_turn < WIPE_TURN
        # survival: the dork stays, so no recast is needed and its mana is never lost
        assert k.sources_by_turn[WIPE_TURN - 1] == l.sources_by_turn[WIPE_TURN - 1] + 1
        assert k.board_creatures_by_turn[WIPE_TURN - 1] == 1
        assert l.board_creatures_by_turn[WIPE_TURN - 1] == 0


def _resolved(make_card, commander, lands):
    from mythgauntlet.data.scryfall import CardDb

    db = CardDb([commander, *lands])
    body = "\n".join(f"{n} {land.name}" for land, n in zip(lands, (50, 49), strict=False))
    deck = Deck.parse_text(f"Commander:\n1 {commander.name}\n\nDeck:\n{body}\n")
    return resolve(deck, db)


def test_analysis_carries_lens(make_card, empty_store):
    small_cfg = SimConfig(runs=30, seed=1, turns=8)
    lands = [_mountain(make_card), _swamp(make_card)]
    smaug = make_card(**SMAUG)
    a = analyze_deck(_resolved(make_card, smaug, lands), small_cfg, empty_store)
    assert a.lens is not None and "survives_wipe" in a.lens.kinds

    vanilla = make_card("Vanilla Legend", mana_cost="{2}{R}",
                        type_line="Legendary Creature — Human", power="3", toughness="3",
                        color_identity=("R",))
    b = analyze_deck(_resolved(make_card, vanilla, lands), small_cfg, empty_store)
    assert b.lens is not None and b.lens.kinds == ()


def test_counter_reserve_is_cheapest_counterspell(make_card, forest):
    from mythgauntlet.ratings.analysis import _counter_reserve

    cs = make_card("Counterspell", mana_cost="{U}{U}", type_line="Instant",
                   oracle_text="Counter target spell.", color_identity=("U",))
    cancel = make_card("Cancel", mana_cost="{1}{U}{U}", type_line="Instant",
                       oracle_text="Counter target spell.", color_identity=("U",))
    assert _counter_reserve([(forest, 30), (cancel, 1), (cs, 1)]) == 2
    assert _counter_reserve([(forest, 30)]) == 0
