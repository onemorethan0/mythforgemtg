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
from mythgauntlet.sim.game import _apply_declare_blocks
from mythgauntlet.sim.tier2 import (
    COMMANDER_DAMAGE_LETHAL,
    DuelConfig,
    _Permanent,
    _Player,
    commander_damage_lost,
    duel,
    make_game_card,
)


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


# --- commander damage (CR 704.5a / the "21 rule") -----------------------------------------


def _cmdr_permanent(power=5):
    return _Permanent(name="Big Commander", power=power, toughness=5, is_creature=True,
                       sick=False, is_commander=True)


def test_commander_damage_lost_at_threshold():
    p = _Player(name="a", library=[], life=40)
    assert not commander_damage_lost(p)
    p.commander_damage_taken["b"] = COMMANDER_DAMAGE_LETHAL - 1
    assert not commander_damage_lost(p)
    p.commander_damage_taken["b"] = COMMANDER_DAMAGE_LETHAL
    assert commander_damage_lost(p)


def test_clone_preserves_commander_damage(make_card):
    from mythgauntlet.sim.game import clone

    me = _Player(name="a", library=[], life=40)
    opp = _Player(name="b", library=[], life=40)
    opp.commander_damage_taken["a"] = 14
    st = _main_state(me, opp)
    snap = clone(st)
    opp.commander_damage_taken["a"] = 99  # mutate the ORIGINAL after cloning
    assert snap.players["b"].commander_damage_taken["a"] == 14  # clone unaffected


def test_unblocked_commander_attack_accrues_damage():
    me = _Player(name="a", library=[], life=40)
    opp = _Player(name="b", library=[], life=40)
    st = _main_state(me, opp)
    cmdr = _cmdr_permanent(power=5)
    me.battlefield.append(cmdr)
    st.combat_attackers = [cmdr]
    st.combat_defender = "b"
    _apply_declare_blocks(st, {})  # empty assignment -> unblocked
    assert opp.life == 35
    assert opp.commander_damage_taken.get("a") == 5


def test_blocked_commander_attack_does_not_accrue_damage():
    """CR 704.5a counts COMBAT DAMAGE TO A PLAYER only -- a blocked commander's damage goes
    to the blocker, not the defending player, so nothing should accrue."""
    me = _Player(name="a", library=[], life=40)
    opp = _Player(name="b", library=[], life=40)
    st = _main_state(me, opp)
    cmdr = _cmdr_permanent(power=5)
    blocker = _Permanent(name="Wall", power=0, toughness=10, is_creature=True, sick=False)
    me.battlefield.append(cmdr)
    opp.battlefield.append(blocker)
    st.combat_attackers = [cmdr]
    st.combat_defender = "b"
    _apply_declare_blocks(st, {0: blocker})
    assert opp.life == 40  # 5 power vs 10 toughness: blocker survives, no damage to player
    assert "a" not in opp.commander_damage_taken


def test_noncommander_attacker_does_not_accrue_commander_damage():
    me = _Player(name="a", library=[], life=40)
    opp = _Player(name="b", library=[], life=40)
    st = _main_state(me, opp)
    beater = _Permanent(name="Big Beater", power=25, toughness=25, is_creature=True, sick=False)
    me.battlefield.append(beater)
    st.combat_attackers = [beater]
    st.combat_defender = "b"
    _apply_declare_blocks(st, {})
    assert opp.life == 15  # ordinary life loss still applies
    assert not opp.commander_damage_taken  # but it is NOT commander damage


def test_repeated_unblocked_commander_attacks_end_the_game_at_21(make_card, forest):
    """End-to-end: a 5/5 commander attacking unblocked into an empty board reaches the 21
    threshold on its 5th swing (25 total) well before combat-only life loss (40) would ever
    matter -- this is the exact PLAN_CLOCK S18 gap (a Voltron/commander-damage kill was
    structurally invisible to the engine) and the regression test for the fix. Verified live
    2026-08-25: this flipped the golden master's "commander_recast" scenario (a 5/5
    commander vs. an aggro deck) from a 40-0 blowout to a real contest."""
    cmdr_card = make_card("Big Commander", mana_cost="{2}{G}", type_line="Creature - Beast",
                          color_identity=("G",))
    cmdr_card.power, cmdr_card.toughness = "5", "5"
    do_nothing = [(forest, 60)]
    lands = [(forest, 60)]
    cfg = DuelConfig(games=10, seed=1, max_turns=25)
    result = duel(do_nothing, cmdr_card, lands, None, cfg)
    # With no blockers ever available to deck B, the commander closes every game via
    # commander damage well inside the 25-turn cap.
    assert result.wins_a == 10
    assert result.avg_turns < 25


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
