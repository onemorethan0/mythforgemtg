"""Conditions that ARE a payment must not be assumed satisfied.

Both resolvers otherwise assume every free-text condition holds — a convention inherited
from the flattening and defensible for a board state the engine cannot evaluate ("if a
creature died this turn"). It is not defensible when the condition IS the cost: assuming
"if you pay {E}{E}" hands over the payoff and skips the price.

This is the third appearance of the class CLAUDE.md already names — *an effect read
without its COST* (`profile._activated_from` made 1,488 abilities free repeatable
outlets; `ramp_sources` counted gross instead of net mana) — so the tests here are
written against the SHAPES that recur, not just the strings that happened to be in the
store on the day it was found.

Measured live in a 40-game tier-2 duel between two corpus decks: the rule declines 294
effects that were previously granted free, dominated by energy costs — the engine has no
energy pool at all, so every `{E}` payoff was firing for nothing.
"""

from __future__ import annotations

import pytest

from mythgauntlet.semantics.interpreter import (
    DefaultResolver,
    condition_names_an_unpaid_cost,
)
from mythgauntlet.sim.tier2 import _EngineResolver, _Player


COST_BEARING = [
    "if you pay {1}",
    "if you pay {E}",
    "if you pay {E}{E}{E}",
    "unless you pay {2}",
    "you may pay {E}{E}",
    "if you discard a card",
    "if you sacrifice a creature",
    "if you exile Dragon's Approach and four other cards named Dragon's Approach",
    "if you do",
    "if this spell was kicked",
    "if its kicker cost was paid",
    "if you reveal a Mountain card from your hand",
    "if you tap an untapped creature you control",
]

# Board/state conditions the engine genuinely cannot evaluate. These stay ASSUMED TRUE on
# purpose: ~81% of assumed-true conditions are this shape, and flipping them would deflate
# every rating in the corpus and invalidate the bracket calibration. That is a sweep, not
# a bug fix -- so the narrow scope is pinned here, not just described in a comment.
BOARD_ONLY = [
    "if a creature died this turn",
    "when that creature dies this turn",
    "if you control a Swamp",
    "blocking",
    "equal to the creature's toughness",
    "if an opponent lost life this turn",
    "only once each turn",
]


@pytest.mark.parametrize("condition", COST_BEARING)
def test_a_payment_condition_is_not_assumed_satisfied(condition):
    assert condition_names_an_unpaid_cost(condition) is True


@pytest.mark.parametrize("condition", BOARD_ONLY)
def test_a_board_condition_stays_assumed_true(condition):
    assert condition_names_an_unpaid_cost(condition) is False


def test_both_resolvers_apply_the_same_rule():
    """One predicate, two call sites — the drift this repo keeps re-learning about.

    `DefaultResolver` and `_EngineResolver` are separate implementations of the same
    protocol; when they disagreed about `otherwise` once already, Approach of the Second
    Sun was credited as an outright win on every cast.
    """
    default = DefaultResolver()
    engine = _EngineResolver(_Player(name="P", library=[]))
    for condition in COST_BEARING:
        assert default.condition_holds(condition, {}) is False, condition
        assert engine.condition_holds(condition, {}) is False, condition
    for condition in BOARD_ONLY:
        assert default.condition_holds(condition, {}) is True, condition
        assert engine.condition_holds(condition, {}) is True, condition


def test_otherwise_still_declines():
    """The pre-existing narrow exception must survive this second one."""
    assert DefaultResolver().condition_holds("otherwise", {}) is False
    assert _EngineResolver(_Player(name="P", library=[])).condition_holds("Otherwise", {}) is False


def test_an_absent_condition_is_not_treated_as_a_cost():
    for empty in ("", "   ", None):
        assert condition_names_an_unpaid_cost(empty or "") is False


def test_paying_words_about_an_OPPONENT_do_not_gate_our_effect():
    """"unless you pay" is our cost; a cost the OPPONENT pays is not ours to decline.

    Ward-style text ("unless that player pays {2}") gates THEIR action, not our effect --
    declining our effect there would under-count a real card for the wrong reason.
    """
    assert condition_names_an_unpaid_cost("unless that player pays {2}") is False
    assert condition_names_an_unpaid_cost("unless its controller pays {3}") is False
