"""Flying/reach block legality (CR 702.9b), docs/PLAN_FIDELITY.md Phase B3.

`greedy_block_assignment` used to draw blockers for every attacker from the whole untapped
board -- a flying attacker was blockable by anything. These pin the fix as a pure function of
`_Permanent`/`_Player`, no full game state needed, on both of the function's two passes
(winning-trade and chump-block).
"""

from __future__ import annotations

from mythgauntlet.agents.greedy import greedy_block_assignment
from mythgauntlet.sim.tier2 import _Permanent, _Player


def _perm(name, power, toughness, keywords=()):
    return _Permanent(name=name, power=power, toughness=toughness, is_creature=True,
                       sick=False, keywords=frozenset(keywords))


def test_flying_attacker_cannot_be_blocked_by_a_grounded_creature():
    """Winning-trade pass: a grounded creature that would otherwise win the trade is filtered
    out entirely -- the attacker goes unblocked rather than being blocked illegally."""
    defender = _Player(name="b", library=[], life=40)
    atk = _perm("Drake", power=2, toughness=2, keywords=("flying",))
    blocker = _perm("Grounded Giant", power=5, toughness=5)  # would win the trade, if legal
    defender.battlefield.append(blocker)
    assert greedy_block_assignment([atk], defender) == {}


def test_flying_attacker_can_be_blocked_by_flying_or_reach():
    defender = _Player(name="b", library=[], life=40)
    atk = _perm("Drake", power=2, toughness=2, keywords=("flying",))
    reach_blocker = _perm("Spider", power=5, toughness=5, keywords=("reach",))
    defender.battlefield.append(reach_blocker)
    assert greedy_block_assignment([atk], defender) == {0: reach_blocker}


def test_flying_attacker_stays_unblocked_by_a_grounded_creature_even_when_lethal():
    """Chump-block pass: the filter must apply there too, or a defender facing lethal from a
    flier would illegally chump with a grounded creature that can't legally block it."""
    defender = _Player(name="b", library=[], life=5)
    atk = _perm("Huge Drake", power=10, toughness=1, keywords=("flying",))
    grounded = _perm("Grounded Chump", power=1, toughness=1)  # no winning trade either
    defender.battlefield.append(grounded)
    assert greedy_block_assignment([atk], defender) == {}


def test_non_flying_attacker_can_still_be_blocked_by_a_flier():
    """Flying restricts who can block IT; it doesn't stop a flier from blocking ground attackers."""
    defender = _Player(name="b", library=[], life=40)
    atk = _perm("Ground Beater", power=2, toughness=2)
    flier = _perm("Watchful Griffin", power=5, toughness=5, keywords=("flying",))
    defender.battlefield.append(flier)
    assert greedy_block_assignment([atk], defender) == {0: flier}


# --- deathtouch changes what counts as a "winning trade" (Phase B4) ------------------------


def test_a_small_deathtouch_blocker_is_a_winning_trade_against_a_much_bigger_attacker():
    """A plain power/toughness comparison would never pick this blocker -- 1 power can't
    threaten a 10-toughness attacker by the numbers alone. Deathtouch makes it lethal, and
    the blocker's own 10 toughness comfortably survives the attacker's 8 power, so this is a
    genuine winning trade the old `b.power >= atk.toughness` check missed entirely."""
    defender = _Player(name="b", library=[], life=40)
    atk = _perm("Huge Beater", power=8, toughness=10)
    small_dt = _perm("Deadly Mouse", power=1, toughness=10, keywords=("deathtouch",))
    defender.battlefield.append(small_dt)
    assert greedy_block_assignment([atk], defender) == {0: small_dt}


def test_deathtouch_does_not_manufacture_a_trade_that_kills_the_blocker_too():
    """Deathtouch only changes whether the BLOCKER kills the attacker -- if the attacker also
    kills the blocker, this is a mutual trade, not a "winning" one, and the winning-trade pass
    must still decline it (it may still be picked by the later chump pass)."""
    defender = _Player(name="b", library=[], life=40)
    atk = _perm("Huge Beater", power=8, toughness=10)
    doomed_dt = _perm("Doomed Mouse", power=1, toughness=8, keywords=("deathtouch",))
    defender.battlefield.append(doomed_dt)
    assert greedy_block_assignment([atk], defender) == {}
