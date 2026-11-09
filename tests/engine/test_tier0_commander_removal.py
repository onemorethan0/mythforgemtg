"""B36: the goldfish with the commander answered N times (`simulate(commander_removals=N)`)."""
from __future__ import annotations

from mythgauntlet.sim.tier0 import SimConfig, simulate


def _creature(make_card, name, power, cost="{1}{G}"):
    c = make_card(name, mana_cost=cost, type_line="Creature - Beast", color_identity=("G",))
    c.power, c.toughness = str(power), str(power)
    return c


def _commander(make_card, power=9):
    c = make_card("Big Boss", mana_cost="{2}{G}", type_line="Legendary Creature - Beast",
                  color_identity=("G",))
    c.power, c.toughness = str(power), str(power)
    return c


def _key(runs):
    return [(r.kill_turn, r.commander_turn, tuple(r.mana_available_by_turn)) for r in runs]


CFG = SimConfig(turns=12, runs=60, seed=5)


def test_zero_removals_is_byte_identical(make_card, forest):
    deck = [(forest, 38), (_creature(make_card, "Bear", 2), 61)]
    cmd = _commander(make_card)
    assert _key(simulate(deck, cmd, CFG)) == _key(simulate(deck, cmd, CFG, commander_removals=0))


def test_a_deck_without_a_commander_shows_no_change(make_card, forest):
    """The spec's acceptance pin: nothing to remove, nothing changes."""
    deck = [(forest, 38), (_creature(make_card, "Bear", 3), 62)]
    assert _key(simulate(deck, None, CFG)) == _key(simulate(deck, None, CFG, commander_removals=2))


def test_removing_a_commander_that_carries_the_deck_slows_the_kill(make_card, forest):
    deck = [(forest, 40), (_creature(make_card, "Squirrel", 1, "{G}"), 59)]
    cmd = _commander(make_card, power=12)
    clean = simulate(deck, cmd, CFG)
    hit = simulate(deck, cmd, CFG, commander_removals=2)

    def mean_kill(runs):
        turns = [r.kill_turn if r.kill_turn is not None else CFG.turns + 1 for r in runs]
        return sum(turns) / len(turns)

    assert mean_kill(hit) > mean_kill(clean) + 1.0
    # still cast first on the same turn: removal happens after it lands
    assert [r.commander_turn for r in hit] == [r.commander_turn for r in clean]
