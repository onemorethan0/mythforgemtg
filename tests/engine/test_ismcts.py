"""ISMCTSAgent behaviour (agents/ismcts.py): determinism, forced moves, and the headline
Phase-7 capability -- deliberately holding mana up for a counter where the greedy agent taps out.
Offline/synthetic (invariant #5)."""

from __future__ import annotations

from mythgauntlet.agents.greedy import GreedyAgent
from mythgauntlet.agents.ismcts import ISMCTSAgent
from mythgauntlet.sim.game import (
    MAIN,
    CastSpell,
    GameState,
    Pass,
    advance,
    clone,
    determinize,
)
from mythgauntlet.sim.rng import SeededRng
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import DuelConfig, _Player, duel, make_game_card


def _gc(make_card, **kw):
    return make_game_card(make_card(**kw), None)


def _island(make_card):
    return make_card("Island", type_line="Basic Land - Island",
                     produced_mana=("U",), color_identity=("U",))


def _usrc(n, ready=True):
    return [_Source(frozenset("U"), ready=ready) for _ in range(n)]


# --- determinism + forced moves ----------------------------------------------------------


def test_mcts_duel_is_deterministic(make_card):
    forest = make_card("Forest", type_line="Basic Land - Forest",
                       produced_mana=("G",), color_identity=("G",))
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature - Beast",
                     color_identity=("G",))
    bear.power, bear.toughness = "3", "2"
    aggro, lands = [(forest, 24), (bear, 36)], [(forest, 60)]
    cfg = DuelConfig(games=6, seed=7, max_turns=18, agent_a="mcts",
                     mcts_iterations=16, rollout_depth=12)
    assert duel(aggro, None, lands, None, cfg) == duel(aggro, None, lands, None, cfg)


def test_determinize_preserves_public_and_hides_opponent(make_card):
    isl = _island(make_card)
    me = _Player(name="a", library=[_gc(make_card, name="A1", type_line="Basic Land"),
                                    _gc(make_card, name="A2", type_line="Basic Land")],
                 hand=[make_game_card(isl, None)], sources=_usrc(2), life=37)
    opp = _Player(name="b", library=[_gc(make_card, name="B1", type_line="Basic Land"),
                                     _gc(make_card, name="B2", type_line="Basic Land")],
                  hand=[make_game_card(isl, None)], sources=_usrc(3), life=22)
    st = GameState(players={"a": me, "b": opp}, order=["a", "b"], cfg=DuelConfig(),
                   active="a", phase=MAIN)
    d = determinize(st, "a", SeededRng(1))
    assert d.players["a"].life == 37 and d.players["b"].life == 22  # public totals kept
    assert len(d.players["a"].hand) == 1  # observer hand size preserved
    assert len(d.players["b"].hand) == 1 and len(d.players["b"].library) == 2  # opp sizes kept
    assert d.players is not st.players  # a real clone


def test_single_legal_action_skips_search(make_card):
    me = _Player(name="a", library=[], hand=[], sources=[], life=40)
    opp = _Player(name="b", library=[], life=40)
    st = GameState(players={"a": me, "b": opp}, order=["a", "b"], cfg=DuelConfig(),
                   active="a", phase=MAIN)
    advance(st)  # -> MAIN with only Pass legal (empty hand, no land, no commander)
    action = ISMCTSAgent(iterations=50, rng=SeededRng(0)).decide(st)
    assert isinstance(action, Pass)


# --- the headline: hold mana for a counter where greedy taps out -------------------------


def _mana_holding_state(make_card) -> GameState:
    """A's turn, 3 Islands up. Hand = {a 3-mana Drake, a Counterspell}. B's deck is stuffed with
    game-ending 12/12s it will cast next turn. Casting the Drake taps out (no counter left);
    passing holds the counter, which the engine auto-fires at B's bomb."""
    drake = make_card("Storm Drake", mana_cost="{2}{U}", type_line="Creature - Drake",
                      color_identity=("U",))
    drake.power, drake.toughness = "3", "3"
    counter = make_card("Counterspell", mana_cost="{U}{U}", type_line="Instant",
                        color_identity=("U",), oracle_text="Counter target spell.")
    bomb = make_card("Colossus", mana_cost="{2}", type_line="Creature - Giant")
    bomb.power, bomb.toughness = "12", "12"
    isl = _island(make_card)

    a = _Player(name="a", hand=[make_game_card(drake, None), make_game_card(counter, None)],
                library=[make_game_card(isl, None) for _ in range(20)],
                sources=_usrc(3), life=40)
    b = _Player(name="b", hand=[],
                library=([make_game_card(bomb, None) for _ in range(16)]
                         + [make_game_card(isl, None) for _ in range(4)]),
                sources=_usrc(2), life=40)
    st = GameState(players={"a": a, "b": b}, order=["a", "b"], cfg=DuelConfig(max_turns=20),
                   turn=3, pos=0, active="a", phase=MAIN, land_played=True)
    advance(st)  # -> pending MAIN(a)
    return st


def test_greedy_taps_out_but_ismcts_holds_mana(make_card):
    greedy_choice = GreedyAgent().decide(_mana_holding_state(make_card))
    assert isinstance(greedy_choice, CastSpell)  # greedy jams the Drake, tapping out

    agent = ISMCTSAgent(iterations=160, rng=SeededRng(42), rollout_depth=16)
    mcts_choice = agent.decide(clone(_mana_holding_state(make_card)))
    assert isinstance(mcts_choice, Pass)  # search holds mana up for the counter
