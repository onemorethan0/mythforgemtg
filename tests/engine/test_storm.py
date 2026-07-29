"""Storm / spellslinger go-off estimator (sim/storm.py) — the commander-as-engine ceiling.

The load-bearing property (docs/SIMULATION.md): with a storm-granter the copy multiplier turns a
mana-limited spell chain into a lethal one, and the SAME deck WITHOUT the granter stays mana-limited
and falls short. A fair deck never goes off, and the estimate is deterministic.
"""

from __future__ import annotations

from mythgauntlet.sim.storm import estimate_go_off

_TURNS = 12
# a generous nut-draw mana curve (~ramp deck): plenty of mana once the engine is deployed.
_MANA = [1, 2, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21]


def _granter(make_card):
    return make_card(
        "Inspiration Muse", mana_cost="{2}{U}{R}", type_line="Legendary Creature",
        oracle_text="Instant and sorcery spells you cast have storm.",
    )


def _cantrips(make_card, n=14):
    # {U} cantrips with NO mana refund -> without the storm multiplier the chain is mana-limited.
    return [(make_card(
        f"Cantrip {i}", mana_cost="{U}", type_line="Instant", oracle_text="Draw a card.",
    ), 1) for i in range(n)]


def _burn_payoff_deck(make_card, *, with_granter: bool):
    """A per-cast burn payoff (Guttersnipe class) + cheap cantrips + a scaling finisher. The only
    difference between the two variants is the storm-granter (the copy multiplier)."""
    cards = [
        (make_card(
            "Cast-Burn Imp", type_line="Creature",
            oracle_text="Whenever you cast an instant or sorcery spell, it deals 2 damage "
                        "to any target.",
        ), 1),
        *_cantrips(make_card),
        (make_card(
            "Big Burn", mana_cost="{X}{R}", type_line="Sorcery",
            oracle_text="Big Burn deals X damage to any target.",
        ), 1),
    ]
    if with_granter:
        cards.insert(0, (_granter(make_card), 1))
    return cards


def test_full_storm_engine_goes_off(make_card):
    report = estimate_go_off(_burn_payoff_deck(make_card, with_granter=True), _MANA, _TURNS)
    assert report.goes_off
    assert report.earliest_turn is not None and 1 <= report.earliest_turn <= _TURNS
    assert report.storm_engine
    assert report.peak_damage >= 40


def test_same_deck_without_storm_granter_does_not_go_off(make_card):
    # identical spell base, no granter -> triggers = 1, no multiplier, the chain stays mana-limited
    report = estimate_go_off(_burn_payoff_deck(make_card, with_granter=False), _MANA, _TURNS)
    assert not report.goes_off
    assert report.earliest_turn is None
    assert not report.storm_engine


def test_treasure_magecraft_engine_fires(make_card):
    # the other real go-off path: a magecraft-treasure engine (Storm-Kiln class) refunds each cast,
    # sustaining a long burn chain even before the storm copies pile on.
    cards = [
        (_granter(make_card), 1),
        (make_card(
            "Cast-Burn Imp", type_line="Creature",
            oracle_text="Whenever you cast an instant or sorcery spell, it deals 2 damage "
                        "to any target.",
        ), 1),
        (make_card(
            "Treasure Sage", type_line="Creature",
            oracle_text="Magecraft -- whenever you cast or copy an instant or sorcery spell, "
                        "create a Treasure token.",
        ), 1),
        *_cantrips(make_card),
        (make_card(
            "Big Burn", mana_cost="{X}{R}", type_line="Sorcery",
            oracle_text="Big Burn deals X damage to any target.",
        ), 1),
    ]
    report = estimate_go_off(cards, _MANA, _TURNS)
    assert report.goes_off
    assert report.storm_engine


def test_fair_deck_never_goes_off(make_card):
    cards = [
        (make_card(f"Bear {i}", mana_cost="{1}{G}", oracle_text=""), 1) for i in range(20)
    ] + [
        (make_card(f"Bolt {i}", mana_cost="{R}", type_line="Instant",
                   oracle_text="Bolt deals 3 damage to any target."), 1) for i in range(6)
    ]
    report = estimate_go_off(cards, _MANA, _TURNS)
    assert not report.goes_off
    assert report.peak_damage < 40


def test_lone_storm_card_without_density_does_not_fire(make_card):
    # a single spell with a copy payoff and nothing to chain must not be read as an engine
    cards = [
        (make_card("Lonely Storm", mana_cost="{2}{R}", type_line="Sorcery",
                   oracle_text="Lonely Storm deals X damage to any target."), 1),
        (make_card("Bear", mana_cost="{1}{G}", oracle_text=""), 1),
    ]
    report = estimate_go_off(cards, _MANA, _TURNS)
    assert not report.goes_off


def test_deterministic(make_card):
    cards = _burn_payoff_deck(make_card, with_granter=True)
    a = estimate_go_off(cards, _MANA, _TURNS)
    b = estimate_go_off(cards, _MANA, _TURNS)
    assert a == b


def test_engine_needs_mana_no_turn_1_kill(make_card):
    # with a starved mana curve the engine cannot deploy turn 1 -- the go-off is gated to a later
    # turn, never turn 1 (the calibration bug this guards against).
    starved = [1, 1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 18]
    report = estimate_go_off(_burn_payoff_deck(make_card, with_granter=True), starved, _TURNS)
    if report.goes_off:
        assert report.earliest_turn is not None and report.earliest_turn >= 3
