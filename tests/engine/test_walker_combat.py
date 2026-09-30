"""Attacking planeswalkers (sim/game.py): plan, damage to loyalty, blocks, clone.

Before this, nothing could attack a planeswalker, so once walkers became functional
(test_planeswalker_loyalty) they were immortal and over-valued.
"""

from __future__ import annotations

from mythgauntlet.agents.greedy import GreedyAgent, greedy_block_assignment
from mythgauntlet.sim.game import (
    Decision,
    GameState,
    _apply_declare_attackers,
    _apply_declare_blocks,
    clone,
    legal_actions,
    walker_attack_plan,
)
from mythgauntlet.sim.tier2 import DuelConfig, _Permanent, _Player


def _atk(power, name="Atk", **kw):
    return _Permanent(name=name, power=power, toughness=power, is_creature=True, sick=False, **kw)


def _walker(loyalty, name="PW"):
    return _Permanent(name=name, power=0, toughness=0, is_creature=False, sick=False,
                      loyalty=loyalty, is_planeswalker=True)


def _state(me, opp):
    return GameState(players={"a": me, "b": opp}, order=["a", "b"], cfg=DuelConfig(),
                     active="a", phase="combat_attack")


def _players(my_life=40, opp_life=40):
    return _Player(name="a", library=[], life=my_life), _Player(name="b", library=[], life=opp_life)


# --- the plan -----------------------------------------------------------------------

def test_plan_is_empty_without_a_walker_or_without_attackers():
    me, opp = _players()
    assert walker_attack_plan([_atk(5)], opp) == ()
    opp.battlefield.append(_walker(4))
    assert walker_attack_plan([], opp) == ()


def test_plan_sends_the_fewest_strongest_attackers_that_kill_and_leaves_the_rest():
    _, opp = _players()
    opp.battlefield.append(_walker(5))
    big, mid, small = _atk(6, "big"), _atk(3, "mid"), _atk(1, "small")
    plan = walker_attack_plan([small, big, mid], opp)
    assert [(a.name, x.name) for a, x in plan] == [("big", "PW")]  # 6 >= 5, one attacker


def test_plan_ignores_a_walker_it_cannot_kill():
    """Chip damage on a walker that ticks back up spends power that would have hit the player."""
    _, opp = _players()
    opp.battlefield.append(_walker(9))
    assert walker_attack_plan([_atk(4), _atk(3)], opp) == ()


def test_plan_never_spares_the_player_when_the_attack_is_lethal():
    _, opp = _players(opp_life=7)
    opp.battlefield.append(_walker(2))
    assert walker_attack_plan([_atk(4), _atk(4)], opp) == ()  # 8 >= 7 life: go face


def test_plan_takes_cheapest_kill_first_and_never_reuses_an_attacker():
    _, opp = _players()
    cheap, dear = _walker(2, "cheap"), _walker(6, "dear")
    opp.battlefield.extend([dear, cheap])
    a, b, c = _atk(4, "a"), _atk(3, "b"), _atk(2, "c")
    plan = walker_attack_plan([a, b, c], opp)
    used = [x.name for x, _ in plan]
    assert len(used) == len(set(used))  # no attacker assigned twice
    assert ("a", "cheap") in [(x.name, w.name) for x, w in plan]  # cheapest kill, strongest body


# --- damage -------------------------------------------------------------------------

def test_unblocked_attacker_removes_loyalty_not_life_and_no_commander_damage():
    me, opp = _players()
    w = _walker(5)
    opp.battlefield.append(w)
    cmdr = _atk(3, "Cmdr", is_commander=True)
    me.battlefield.append(cmdr)
    st = _state(me, opp)
    _apply_declare_attackers(st, (cmdr,), ((cmdr, w),))
    assert st.combat_walkers == {0: w}
    _apply_declare_blocks(st, {})
    assert w.loyalty == 2 and w in opp.battlefield
    assert opp.life == 40  # the player took nothing
    assert "a" not in opp.commander_damage_taken  # not damage to a PLAYER (CR 704.5a)
    assert st.combat_walkers == {}


def test_lethal_damage_removes_the_walker():
    me, opp = _players()
    w = _walker(3)
    opp.battlefield.append(w)
    a = _atk(4)
    me.battlefield.append(a)
    st = _state(me, opp)
    _apply_declare_attackers(st, (a,), ((a, w),))
    _apply_declare_blocks(st, {})
    assert w not in opp.battlefield and opp.life == 40


def test_a_blocked_walker_attacker_deals_nothing_to_the_walker():
    me, opp = _players()
    w = _walker(3)
    wall = _Permanent(name="Wall", power=0, toughness=9, is_creature=True, sick=False)
    opp.battlefield.extend([w, wall])
    a = _atk(4)
    me.battlefield.append(a)
    st = _state(me, opp)
    _apply_declare_attackers(st, (a,), ((a, w),))
    _apply_declare_blocks(st, {0: wall})
    assert w.loyalty == 3 and opp.life == 40


def test_attackers_not_assigned_to_a_walker_still_hit_the_player():
    me, opp = _players()
    w = _walker(3)
    opp.battlefield.append(w)
    a, b = _atk(4, "a"), _atk(5, "b")
    me.battlefield.extend([a, b])
    st = _state(me, opp)
    _apply_declare_attackers(st, (a, b), ((a, w),))
    _apply_declare_blocks(st, {})
    assert opp.life == 35 and w not in opp.battlefield  # b (5) hit the player, a killed the walker


def test_a_second_attacker_on_a_dead_walker_does_nothing_and_does_not_crash():
    me, opp = _players()
    w = _walker(2)
    opp.battlefield.append(w)
    a, b = _atk(3, "a"), _atk(3, "b")
    me.battlefield.extend([a, b])
    st = _state(me, opp)
    _apply_declare_attackers(st, (a, b), ((a, w), (b, w)))
    _apply_declare_blocks(st, {})
    assert w not in opp.battlefield and opp.life == 40


def test_only_a_planeswalker_is_a_legal_target():
    me, opp = _players()
    rock = _Permanent(name="Rock", power=0, toughness=0, is_creature=False, sick=False)
    opp.battlefield.append(rock)
    a = _atk(4)
    me.battlefield.append(a)
    st = _state(me, opp)
    _apply_declare_attackers(st, (a,), ((a, rock),))
    assert st.combat_walkers == {}
    _apply_declare_blocks(st, {})
    assert opp.life == 36


# --- search + blocking --------------------------------------------------------------

def test_clone_remaps_the_walker_onto_the_defenders_cloned_battlefield():
    me, opp = _players()
    w = _walker(5)
    opp.battlefield.append(w)
    a = _atk(6)
    me.battlefield.append(a)
    st = _state(me, opp)
    _apply_declare_attackers(st, (a,), ((a, w),))
    snap = clone(st)
    (walker_clone,) = snap.combat_walkers.values()
    assert walker_clone is snap.players["b"].battlefield[0] and walker_clone is not w
    _apply_declare_blocks(snap, {})
    assert w.loyalty == 5  # the original is untouched


def test_blocker_ai_does_not_chump_to_protect_life_from_walker_attackers():
    _, opp = _players(opp_life=3)
    chump = _Permanent(name="Chump", power=1, toughness=1, is_creature=True, sick=False)
    opp.battlefield.append(chump)
    big = _atk(9)
    assert greedy_block_assignment([big], opp)  # aimed at the player: lethal -> chump
    assert greedy_block_assignment([big], opp, {0: _walker(20)}) == {}  # walker survives: no


def test_legal_actions_offer_the_walker_split_as_an_extra_candidate():
    me, opp = _players()
    opp.battlefield.append(_walker(4))
    me.battlefield.append(_atk(5))
    st = _state(me, opp)
    st.pending = Decision("a", "combat_attack")
    acts = legal_actions(st)
    assert any(getattr(x, "walkers", ()) for x in acts)
    assert sum(1 for x in acts if not getattr(x, "walkers", ())) >= 2  # the old candidates remain


def test_greedy_agent_declares_the_split_and_no_split_without_a_walker():
    me, opp = _players()
    me.battlefield.append(_atk(5))
    st = _state(me, opp)
    st.pending = Decision("a", "combat_attack")
    assert GreedyAgent().decide(st).walkers == ()
    opp.battlefield.append(_walker(4))
    assert [(x.name, w.name) for x, w in GreedyAgent().decide(st).walkers] == [("Atk", "PW")]


def test_blockers_protect_a_walker_that_would_die_with_the_cheapest_body():
    _, opp = _players()
    w = _walker(4)
    token = _Permanent(name="Token", power=1, toughness=1, is_creature=True, sick=False)
    bear = _Permanent(name="Bear", power=2, toughness=2, is_creature=True, sick=False)
    opp.battlefield.extend([w, bear, token])
    big = _atk(6)
    assign = greedy_block_assignment([big], opp, {0: w})
    assert assign == {0: token}  # chump with the cheapest body, keep the bear


def test_a_walker_that_survives_the_hit_is_not_protected_with_a_chump():
    _, opp = _players()
    w = _walker(9)
    opp.battlefield.extend([w, _Permanent(name="T", power=1, toughness=1, is_creature=True,
                                          sick=False)])
    assert greedy_block_assignment([_atk(3)], opp, {0: w}) == {}
