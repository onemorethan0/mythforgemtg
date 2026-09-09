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
