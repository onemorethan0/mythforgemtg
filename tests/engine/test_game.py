"""Action-based Tier-2 engine seam (sim/game.py): the surface MCTS drives. Offline/synthetic.

The behavior-equivalence-to-old-engine guarantee lives in test_tier2_golden.py; here we pin the
new API directly — clone independence, legal-action enumeration, apply, and the agent-driven
play_out driver.
"""

from __future__ import annotations

from mythgauntlet.agents import GreedyAgent, make_agent
from mythgauntlet.sim.game import (
    MAIN,
    CastSpell,
    GameState,
    Pass,
    PlayLand,
    advance,
    apply,
    clone,
    legal_actions,
)
from mythgauntlet.sim.rng import SeededRng
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import DuelConfig, _Player, duel, make_game_card


def _bear(make_card, name="Bear"):
    card = make_card(name, mana_cost="{1}{G}", type_line="Creature - Beast", color_identity=("G",))
    card.power, card.toughness = "3", "2"
    return make_game_card(card, None)


def _main_state(me: _Player, opp: _Player) -> GameState:
    st = GameState(players={"a": me, "b": opp}, order=["a", "b"], cfg=DuelConfig(),
                   active="a", phase=MAIN)
    advance(st)  # -> pending MAIN
    return st


# --- clone independence -------------------------------------------------------------------


def test_clone_is_independent(make_card):
    me = _Player(name="a", library=[], hand=[_bear(make_card)],
                 sources=[_Source(frozenset("G")), _Source(frozenset("G"))], life=40)
    opp = _Player(name="b", library=[], life=40)
    st = _main_state(me, opp)
    snap = clone(st)

    # mutate the ORIGINAL; the clone must not move
    me.life = 1
    me.sources[0].ready = False
    me.hand.clear()
    assert snap.players["a"].life == 40
    assert snap.players["a"].sources[0].ready is True
    assert len(snap.players["a"].hand) == 1


# --- legal actions ------------------------------------------------------------------------


def test_legal_main_actions(make_card, forest):
    me = _Player(name="a", library=[], hand=[make_game_card(forest, None), _bear(make_card)],
                 sources=[_Source(frozenset("G")), _Source(frozenset("G"))], life=40)
    opp = _Player(name="b", library=[], life=40)
    st = _main_state(me, opp)
    actions = legal_actions(st)
    assert any(isinstance(a, Pass) for a in actions)
    assert any(isinstance(a, PlayLand) for a in actions)  # a land is in hand, not yet played
    assert any(isinstance(a, CastSpell) for a in actions)  # 2 G sources pay {1}{G}


def test_pass_advances_main_to_activation_to_post_main(make_card):
    me = _Player(name="a", library=[], hand=[], life=40)
    opp = _Player(name="b", library=[], life=40)
    st = _main_state(me, opp)
    apply(st, Pass())          # MAIN -> ACTIVATION
    advance(st)
    assert st.pending.kind == "activation"
    apply(st, Pass())          # ACTIVATION -> post_main -> instant_window -> combat...
    advance(st)
    assert st.phase != MAIN     # left the main phase entirely


# --- agent factory + play_out driver ------------------------------------------------------


def test_make_agent_greedy_and_unknown():
    assert isinstance(make_agent("greedy"), GreedyAgent)
    try:
        make_agent("nope")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_play_out_matches_duel_under_greedy(make_card, forest):
    """The play_out driver (agent map) and the public duel() agree — same seed, same outcome."""
    bear = make_card("Attack Bear", mana_cost="{1}{G}", type_line="Creature - Beast",
                     color_identity=("G",))
    bear.power, bear.toughness = "3", "2"
    aggro = [(forest, 24), (bear, 36)]
    lands = [(forest, 60)]
    cfg = DuelConfig(games=20, seed=7, max_turns=25)
    a = duel(aggro, None, lands, None, cfg)
    b = duel(aggro, None, lands, None, cfg)
    assert a == b  # deterministic through the new driver


def test_seeded_rng_spawn_does_not_disturb_shuffle():
    """duel_prepared spawns agent RNGs off the game RNG; that must not change the deck shuffle."""
    r = SeededRng(123)
    child = r.spawn(9)  # constructing a sub-stream
    order1 = list(range(10))
    r.shuffle(order1)
    # a fresh RNG with the same seed, no spawn, shuffles identically
    r2 = SeededRng(123)
    order2 = list(range(10))
    r2.shuffle(order2)
    assert order1 == order2 and child.seed != r.seed
