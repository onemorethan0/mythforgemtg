"""Toughness-matters commander rules in tier-2 duels ("Test vs another deck").

tier0 (analyze, advisor, mentor) learned these on 2026-10-23 via sim/combat_rules.py; duels
still summed printed power, so a Doran, the Siege Tower wall could never even attack (power 0)
and a defender with power attacked against CR 702.3b. Each expectation below is a CR outcome.
"""
from __future__ import annotations

from types import SimpleNamespace

from mythgauntlet.agents.greedy import greedy_block_assignment
from mythgauntlet.model.card import Card
from mythgauntlet.sim.game import (
    GameState, _apply_declare_attackers, _apply_declare_blocks, _eligible_attackers,
    refresh_combat_rules,
)
from mythgauntlet.sim.tier2 import DuelConfig, _Permanent, _Player, expire_until_end_of_turn

ORACLE = {
    "Doran, the Siege Tower":
        "Each creature assigns combat damage equal to its toughness rather than its power.",
    "Felothar the Steadfast":
        "Each creature you control assigns combat damage equal to its toughness rather than its "
        "power.\nCreatures you control can attack as though they didn't have defender.",
    "Baldin, Century Herdmaster":
        "During your turn, each creature assigns combat damage equal to its toughness rather "
        "than its power.",
    "Doran, Besieged by Time":
        "Each creature spell you cast with toughness greater than its power costs {1} less to "
        "cast.\nWhenever a creature you control attacks or blocks, it gets +X/+X until end of "
        "turn, where X is the difference between its power and toughness.",
}


def _cmd(name):
    card = Card(name=name, type_line="Legendary Creature", oracle_text=ORACLE[name],
                power="0", toughness="5")
    return _Permanent(name=name, power=0, toughness=5, is_creature=True, sick=True,
                      is_commander=True, source=SimpleNamespace(card=card))


def _c(name, p, t, *kw):
    return _Permanent(name=name, power=p, toughness=t, is_creature=True, sick=False,
                      keywords=frozenset(kw))


def _state(mine, theirs, active="a", life=40):
    me = _Player(name="a", library=[], life=life)
    opp = _Player(name="b", library=[], life=life)
    me.battlefield.extend(mine)
    opp.battlefield.extend(theirs)
    st = GameState(players={"a": me, "b": opp}, order=["a", "b"], cfg=DuelConfig(), active=active)
    refresh_combat_rules(st)
    return st, me, opp


def _attack(st, attackers, blocks=None):
    _apply_declare_attackers(st, tuple(attackers))
    _apply_declare_blocks(st, blocks or {})


def test_siege_tower_wall_attacks_and_hits_for_toughness():
    wall = _c("Wall", 0, 4)
    st, me, opp = _state([_cmd("Doran, the Siege Tower"), wall], [])
    assert wall in _eligible_attackers(me)          # power 0, but it deals 4
    _attack(st, [wall])
    assert opp.life == 36


def test_siege_tower_applies_to_the_opponents_blockers_too():
    # "Each creature": the opponent's 1/5 blocker deals 5 and survives a 3/3.
    bear, blocker = _c("Bear", 3, 3), _c("Big Butt", 1, 5)
    st, me, opp = _state([_cmd("Doran, the Siege Tower"), bear], [blocker])
    _attack(st, [bear], {0: blocker})
    assert bear not in me.battlefield and blocker in opp.battlefield


def test_felothar_only_changes_its_controllers_creatures():
    bear, blocker = _c("Bear", 3, 3), _c("Big Butt", 1, 5)
    st, me, opp = _state([_cmd("Felothar the Steadfast"), bear], [blocker])
    _attack(st, [bear], {0: blocker})
    assert bear in me.battlefield                   # the blocker deals its power, 1


def test_baldin_only_on_its_controllers_turn():
    wall = _c("Wall", 0, 4)
    st, me, opp = _state([_c("Raider", 3, 3)], [_cmd("Baldin, Century Herdmaster"), wall])
    raider = me.battlefield[0]
    _attack(st, [raider], {0: wall})                # opponent's turn: wall deals 0
    assert raider in me.battlefield


def test_doran_besieged_pumps_attackers_until_end_of_turn():
    wall, brute = _c("Wall", 0, 4), _c("Brute", 4, 3)
    st, me, opp = _state([_cmd("Doran, Besieged by Time"), wall, brute], [])
    assert wall in _eligible_attackers(me)          # it attacks as a 4/8
    _attack(st, [wall, brute])
    assert opp.life == 40 - 4 - 5                   # X = |p - t|: the 4/3 hits for 5
    expire_until_end_of_turn([me, opp])
    assert (wall.power, wall.toughness, brute.power, brute.toughness) == (0, 4, 4, 3)


def test_doran_besieged_pumps_its_blockers():
    raider, wall = _c("Raider", 3, 3), _c("Wall", 1, 4)
    st, me, opp = _state([raider], [_cmd("Doran, Besieged by Time"), wall])
    _attack(st, [raider], {0: wall})                # the 1/4 blocks as a 4/7
    assert raider not in me.battlefield and wall in opp.battlefield


def test_defender_never_attacks_without_permission():
    gate = _c("Gate Guard", 3, 3, "defender")
    st, me, opp = _state([gate], [])
    assert gate not in _eligible_attackers(me)      # CR 702.3b
    st, me, opp = _state([_cmd("Felothar the Steadfast"), _c("Gate Guard", 0, 6, "defender")], [])
    assert me.battlefield[1] in _eligible_attackers(me)


def test_no_rule_while_the_commander_is_not_on_the_battlefield():
    wall = _c("Wall", 0, 4)
    st, me, opp = _state([wall], [])
    assert wall not in _eligible_attackers(me)


def test_greedy_blocker_sees_toughness_damage():
    # Under the Siege Tower the defender must not "win the trade" with a 3/1 against a 1/6
    # attacker: it deals 1 and takes 6.
    attacker, blk = _c("Big Butt", 1, 6), _c("Glass", 3, 1)
    st, me, opp = _state([_cmd("Doran, the Siege Tower"), attacker], [blk])
    _apply_declare_attackers(st, (attacker,))
    assert greedy_block_assignment(st.combat_attackers, opp).get(0) is not blk
