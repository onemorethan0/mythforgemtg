"""Phase B6 combat keywords: first strike, double strike, menace (docs/PLAN_FIDELITY.md B6).

Cases written as a rules table by Claude (each expectation is a CR outcome), boilerplate drafted
by qwen3:14b via scripts/offload.py and reviewed (the draft put `import pytest` above the
`__future__` import -- a SyntaxError -- and imported pytest unused).
"""

from __future__ import annotations

from mythgauntlet.agents.greedy import greedy_block_assignment
from mythgauntlet.sim.game import GameState, _apply_declare_blocks
from mythgauntlet.sim.tier2 import DuelConfig, _Permanent, _Player


def _setup(attackers, blockers, life=40):
    me = _Player(name="a", library=[], life=life)
    opp = _Player(name="b", library=[], life=life)
    st = GameState(players={"a": me, "b": opp}, order=["a", "b"], cfg=DuelConfig(), active="a")
    for a in attackers:
        me.battlefield.append(a)
    for b in blockers:
        opp.battlefield.append(b)
    st.combat_attackers = list(attackers)
    st.combat_defender = "b"
    return st, me, opp


def _c(name, p, t, *kw, commander=False):
    return _Permanent(name=name, power=p, toughness=t, is_creature=True, sick=False,
                      is_commander=commander, keywords=frozenset(kw))


def test_first_strike_attacker_kills_blocker_first():
    """First strike attacker deals damage before the blocker."""
    A = _c("A", 2, 2, "first strike")
    B = _c("B", 2, 2)
    st, me, opp = _setup([A], [B])
    assignment = {0: B}
    _apply_declare_blocks(st, assignment)
    assert B not in opp.battlefield
    assert A in me.battlefield
    assert opp.life == 40


def test_first_strike_blocker_kills_attacker_first():
    """First strike blocker deals damage before the attacker."""
    A = _c("A", 2, 2)
    B = _c("B", 2, 2, "first strike")
    st, me, opp = _setup([A], [B])
    assignment = {0: B}
    _apply_declare_blocks(st, assignment)
    assert A not in me.battlefield
    assert B in opp.battlefield
    assert opp.life == 40


def test_both_first_strike_trade():
    """Both first strike attackers and blockers deal damage simultaneously."""
    A = _c("A", 2, 2, "first strike")
    B = _c("B", 2, 2, "first strike")
    st, me, opp = _setup([A], [B])
    assignment = {0: B}
    _apply_declare_blocks(st, assignment)
    assert A not in me.battlefield
    assert B not in opp.battlefield
    assert opp.life == 40


def test_surviving_blocker_strikes_back_in_regular_step():
    """Surviving blocker deals damage in the regular combat step."""
    A = _c("A", 1, 1, "first strike")
    B = _c("B", 2, 3)
    st, me, opp = _setup([A], [B])
    assignment = {0: B}
    _apply_declare_blocks(st, assignment)
    assert A not in me.battlefield
    assert B in opp.battlefield
    assert opp.life == 40


def test_double_strike_damage_accumulates_across_steps():
    """Double strike damage is applied in both first strike and regular steps."""
    A = _c("A", 2, 2, "double strike")
    B = _c("B", 3, 3)
    st, me, opp = _setup([A], [B])
    assignment = {0: B}
    _apply_declare_blocks(st, assignment)
    assert A not in me.battlefield
    assert B not in opp.battlefield
    assert opp.life == 40


def test_unblocked_double_strike_hits_twice():
    """Unblocked double strike deals damage twice."""
    A = _c("A", 3, 3, "double strike")
    st, me, opp = _setup([A], [])
    assignment = {}
    _apply_declare_blocks(st, assignment)
    assert opp.life == 34


def test_unblocked_double_strike_commander_damage_counts_twice():
    """Unblocked double strike commander deals damage twice."""
    A = _c("A", 3, 3, "double strike", commander=True)
    st, me, opp = _setup([A], [])
    assignment = {}
    _apply_declare_blocks(st, assignment)
    assert opp.commander_damage_taken.get("a") == 6
    assert opp.life == 34


def test_double_strike_trample_sends_regular_damage_through_after_blocker_dies():
    """Double strike trample deals damage through after blocker dies."""
    A = _c("A", 4, 4, "double strike", "trample")
    B = _c("B", 2, 2)
    st, me, opp = _setup([A], [B])
    assignment = {0: B}
    _apply_declare_blocks(st, assignment)
    assert B not in opp.battlefield
    assert opp.life == 34


def test_double_strike_without_trample_deals_nothing_after_blocker_dies():
    """Double strike without trample deals no damage after blocker dies."""
    A = _c("A", 4, 4, "double strike")
    B = _c("B", 2, 2)
    st, me, opp = _setup([A], [B])
    assignment = {0: B}
    _apply_declare_blocks(st, assignment)
    assert B not in opp.battlefield
    assert opp.life == 40


def test_first_strike_deathtouch_kills_before_taking_damage():
    """First strike deathtouch kills blocker before taking damage."""
    A = _c("A", 1, 1, "first strike", "deathtouch")
    B = _c("B", 5, 5)
    st, me, opp = _setup([A], [B])
    assignment = {0: B}
    _apply_declare_blocks(st, assignment)
    assert B not in opp.battlefield
    assert A in me.battlefield
    assert opp.life == 40


def test_menace_attacker_blocked_by_two_takes_combined_damage():
    """Menace attacker blocked by two takes combined damage."""
    A = _c("A", 3, 3, "menace")
    B1 = _c("B1", 2, 2)
    B2 = _c("B2", 2, 2)
    st, me, opp = _setup([A], [B1, B2])
    assignment = {0: (B1, B2)}
    _apply_declare_blocks(st, assignment)
    assert A not in me.battlefield
    assert (B1 not in opp.battlefield) ^ (B2 not in opp.battlefield)


def test_menace_trample_assigns_lethal_to_each_blocker_then_tramples():
    """Menace trample assigns lethal to each blocker then tramples."""
    A = _c("A", 5, 5, "menace", "trample")
    B1 = _c("B1", 1, 2)
    B2 = _c("B2", 1, 1)
    st, me, opp = _setup([A], [B1, B2])
    assignment = {0: (B1, B2)}
    _apply_declare_blocks(st, assignment)
    assert B1 not in opp.battlefield
    assert B2 not in opp.battlefield
    assert A in me.battlefield
    assert opp.life == 38


def test_greedy_never_single_blocks_a_menace_attacker():
    """Greedy never single blocks a menace attacker."""
    A = _c("A", 3, 3, "menace")
    B = _c("B", 5, 5)
    st, _, opp = _setup([A], [B])
    assignment = greedy_block_assignment([A], opp)
    assert 0 not in assignment or not isinstance(assignment[0], _Permanent)


def test_greedy_double_blocks_menace_when_the_pair_wins():
    """Greedy double blocks menace when the pair wins."""
    A = _c("A", 3, 3, "menace")
    B1 = _c("B1", 2, 4)
    B2 = _c("B2", 2, 4)
    st, _, opp = _setup([A], [B1, B2])
    assignment = greedy_block_assignment([A], opp)
    assert 0 in assignment and isinstance(assignment[0], tuple) and B1 in assignment[0] and B2 in assignment[0]


def test_greedy_does_not_double_block_when_the_pair_cannot_kill():
    """Greedy does not double block when the pair cannot kill."""
    A = _c("A", 3, 3, "menace")
    B1 = _c("B1", 1, 1)
    B2 = _c("B2", 1, 1)
    st, _, opp = _setup([A], [B1, B2])
    assignment = greedy_block_assignment([A], opp)
    assert 0 not in assignment


def test_greedy_does_not_block_a_double_striker_it_cannot_survive():
    """A 3/3 looks like it beats a 2/2 by power alone, but double strike deals 2 in each step
    and kills it -- the defender's trade check must resolve strike order, not compare power."""
    A = _c("A", 2, 2, "double strike")
    B = _c("B", 3, 3)
    st, _, opp = _setup([A], [B])
    assert 0 not in greedy_block_assignment([A], opp)


def test_greedy_first_striker_blocks_and_wins():
    """A 2/2 first-strike blocker kills a 2/2 attacker before it can strike back."""
    A = _c("A", 2, 2)
    B = _c("B", 2, 2, "first strike")
    st, _, opp = _setup([A], [B])
    assert greedy_block_assignment([A], opp).get(0) is B


def test_no_keywords_still_resolves_on_the_single_pass_path():
    """Plain combat must not change: the legacy single simultaneous pass still runs."""
    A = _c("A", 3, 3)
    B = _c("B", 2, 2)
    st, me, opp = _setup([A], [B])
    _apply_declare_blocks(st, {0: B})
    assert B not in opp.battlefield and A in me.battlefield and opp.life == 40


def test_goldfish_counts_a_double_striker_twice(make_card):
    """tier0's goldfish clock: an unblocked double striker deals its power twice (CR 702.4b),
    matching the tier-2 combat above. A printed keyword only (Card.keywords)."""
    import dataclasses
    from mythgauntlet.semantics.model import EffectVector
    from mythgauntlet.sim.tier0 import SimCard
    plain = dataclasses.replace(make_card("Plain Knight"), power="3", toughness="3")
    ds = dataclasses.replace(plain, name="Double Knight", keywords=frozenset({"double strike"}))
    assert SimCard(plain, EffectVector()).attack_power == 3
    assert SimCard(ds, EffectVector()).attack_power == 6
