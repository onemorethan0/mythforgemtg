"""The greedy mana pilot (2026-11-08): play the land that fixes the hand's colours, and keep the
colours for a held instant answer open from the first cast of the turn."""
from __future__ import annotations

from mythgauntlet.agents.greedy import GreedyAgent, _best_land, _keeps_answer_up
from mythgauntlet.sim.game import (
    MAIN,
    CastSpell,
    Decision,
    GameState,
    Pass,
    PlayLand,
    pay_keeping,
)
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import DuelConfig, _Player, cast_cost, make_game_card


def _gc(make_card, name, cost, type_line, text="", **kw):
    return make_game_card(make_card(name, mana_cost=cost, type_line=type_line,
                                    oracle_text=text, **kw), None)


def _land(make_card, name, color, tapped=False):
    text = f"{{T}}: Add {{{color}}}." + ("\nThis land enters tapped." if tapped else "")
    return make_game_card(make_card(name, type_line="Land", oracle_text=text,
                                    produced_mana=(color,)), None)


def _counter(make_card):
    return _gc(make_card, "Counterspell", "{U}{U}", "Instant", "Counter target spell.",
               color_identity=("U",))


def _player(hand, sources):
    p = _Player(name="a", library=[], life=40)
    p.hand.extend(hand)
    p.sources.extend(_Source(frozenset({c}), ready=True) for c in sources)
    return p


def test_the_land_that_fixes_the_hand_is_played(make_card):
    island = _land(make_card, "Island", "U")
    mountain = _land(make_card, "Mountain", "R")
    me = _player([mountain, island, _counter(make_card)], sources=["U"])
    assert _best_land(me, [mountain, island]) is island        # Counterspell needs a second U


def test_an_untapped_land_wins_a_tie(make_card):
    tapped = _land(make_card, "Tapped Island", "U", tapped=True)
    island = _land(make_card, "Island", "U")
    me = _player([tapped, island], sources=[])
    assert _best_land(me, [tapped, island]) is island


def test_the_answer_s_colours_stay_open(make_card):
    bear = _gc(make_card, "Bear", "{1}{U}", "Creature - Bear", color_identity=("U",))
    cost = cast_cost(_player([], []), bear)
    # U, U, R: the Bear takes a U and the R -> one U left, Counterspell not castable
    assert not _keeps_answer_up(_player([bear, _counter(make_card)], ["U", "U", "R"]), cost, bear)
    # U, U, U, R: Bear paid with U + R, both remaining Islands kept for Counterspell
    assert _keeps_answer_up(_player([bear, _counter(make_card)], ["U", "U", "U", "R"]), cost, bear)
    assert _keeps_answer_up(_player([bear], ["U"]), cost, bear)       # nothing held


def test_the_joint_payment_taps_the_mountain_not_the_islands(make_card):
    bear = _gc(make_card, "Bear", "{1}{U}", "Creature - Bear", color_identity=("U",))
    me = _player([bear, _counter(make_card)], ["U", "U", "U", "R"])
    pay = pay_keeping(me.sources, cast_cost(me, bear), cast_cost(me, me.hand[1]))
    assert sorted(pay) == [0, 3] or sorted(pay) == [1, 3] or sorted(pay) == [2, 3]
    left = [s for i, s in enumerate(me.sources) if i not in pay]
    assert all("U" in s.colors for s in left)


def test_the_greedy_main_phase_holds_counter_mana_from_the_first_cast(make_card):
    bear = _gc(make_card, "Bear", "{1}{U}", "Creature - Bear", color_identity=("U",))
    me = _player([bear, _counter(make_card)], sources=["U", "U", "R"])
    opp = _player([], sources=[])
    state = GameState(players={"a": me, "b": opp}, order=["a", "b"], cfg=DuelConfig(max_turns=30),
                      phase=MAIN, land_played=True)
    state.pending = Decision("a", MAIN)
    action = GreedyAgent().decide(state)
    assert isinstance(action, Pass)          # casting the Bear would tap out the counter's UU
    me.sources.append(_Source(frozenset({"U"}), ready=True))
    assert isinstance(GreedyAgent().decide(state), CastSpell)
    assert not isinstance(GreedyAgent().decide(state), PlayLand)
