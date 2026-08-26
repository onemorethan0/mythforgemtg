"""sim/clock.apply_nut_kills — teaches RunStats.kill_turn to see a non-combat win
(PLAN_CLOCK.md Phase 1a). Offline, synthetic (invariant #5): hand-built RunStats objects
so each test isolates one detector without running a full simulation.
"""

from __future__ import annotations

from mythgauntlet.sim.clock import apply_nut_kills
from mythgauntlet.sim.tier0 import RunStats


def _granter(make_card):
    return make_card(
        "Inspiration Muse", mana_cost="{2}{U}{R}", type_line="Legendary Creature",
        oracle_text="Instant and sorcery spells you cast have storm.",
    )


def _cantrips(make_card, n=14):
    return [(make_card(
        f"Cantrip {i}", mana_cost="{U}", type_line="Instant", oracle_text="Draw a card.",
    ), 1) for i in range(n)]


def _storm_deck(make_card):
    # Matches test_storm.py's own proven-to-go-off fixture: a granter alone has nothing to
    # copy INTO damage -- it needs a per-cast burn payoff (Guttersnipe class) plus a
    # scaling finisher to actually threaten lethal.
    return [
        (_granter(make_card), 1),
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


def _overrun_deck(make_card):
    finisher = make_card(
        "Team Charge", mana_cost="{2}{G}{G}", type_line="Sorcery",
        oracle_text="Creatures you control get +3/+3 and gain trample until end of turn.",
    )
    return [(finisher, 1)]


def test_lowers_kill_turn_when_go_off_is_earlier(make_card):
    # A generous nut-draw mana curve (test_storm.py's own fixture curve) lets the storm
    # granter's copy multiplier close well before combat could.
    run = RunStats(mana_available_by_turn=[1, 2, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21],
                    kill_turn=9)
    cards = _storm_deck(make_card)
    apply_nut_kills([run], cards, turns=12)
    assert run.kill_turn is not None
    assert run.kill_turn < 9


def test_never_raises_kill_turn(make_card):
    # min() over the candidates: a combat kill earlier than any detector must survive.
    run = RunStats(mana_available_by_turn=[1, 2, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21],
                    kill_turn=2)
    cards = _storm_deck(make_card)
    apply_nut_kills([run], cards, turns=12)
    assert run.kill_turn == 2


def test_gives_a_kill_turn_to_a_run_with_no_combat_kill(make_card):
    run = RunStats(mana_available_by_turn=[1, 2, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21],
                    kill_turn=None)
    cards = _storm_deck(make_card)
    apply_nut_kills([run], cards, turns=12)
    assert run.kill_turn is not None


def test_overrun_alpha_strike_lowers_kill_turn(make_card):
    # +3/+3 on a 10-wide board of 1-power tokens: 10 + 10*3 = 40, exactly lethal (sim/overrun's
    # own _LETHAL) -- the board only gets that wide from turn 4 on.
    run = RunStats(
        board_power_by_turn=[0, 2, 4, 10, 10, 10],
        board_creatures_by_turn=[0, 2, 4, 10, 10, 10],
        kill_turn=9,
    )
    apply_nut_kills([run], _overrun_deck(make_card), turns=6)
    assert run.kill_turn is not None
    assert run.kill_turn < 9


def test_no_detector_fires_leaves_kill_turn_untouched(make_card):
    """A vanilla creature with no storm granter and no finisher: neither detector fires,
    so a combat kill_turn (or lack of one) is left exactly as the sim reported it."""
    vanilla = make_card("Grizzly Bears", mana_cost="{1}{G}", type_line="Creature")
    run_with_kill = RunStats(mana_available_by_turn=[1, 2, 3], kill_turn=6)
    run_no_kill = RunStats(mana_available_by_turn=[1, 2, 3], kill_turn=None)
    apply_nut_kills([run_with_kill, run_no_kill], [(vanilla, 40)], turns=8)
    assert run_with_kill.kill_turn == 6
    assert run_no_kill.kill_turn is None


def test_mutates_every_run_in_the_list_independently(make_card):
    fast = RunStats(mana_available_by_turn=[5, 10, 15, 20, 25, 30], kill_turn=None)
    slow = RunStats(mana_available_by_turn=[1, 1, 1, 1, 1, 1], kill_turn=None)
    cards = _storm_deck(make_card)
    apply_nut_kills([fast, slow], cards, turns=6)
    # Not asserting exact turns (that's estimate_go_off's own contract) -- just that a
    # richer mana curve cannot come out WORSE than a starved one for the same deck.
    if fast.kill_turn is not None and slow.kill_turn is not None:
        assert fast.kill_turn <= slow.kill_turn
