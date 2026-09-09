"""The turn-scoped effect layer, and `pump` on top of it (sim/tier2.py, sim/game.py).

`pump` was the single largest inert op in the compiled store (3,925 cards / 4,295
effects, found by `mythgauntlet sim-health`). Dispatching it required a cleanup step
first, because **92.1% of stored pumps are "until end of turn"** and this engine had no
notion of an effect ending: executing them without expiry would have made every combat
trick permanent and compounding — a turn-3 Giant Growth still +3/+3 on turn 12, which is
strictly worse than the honest no-op it replaced.

So the tests that matter here are the EXPIRY ones. A pump that applies is easy; a pump
that goes away on schedule is the whole reason the feature is safe to ship.
"""

from __future__ import annotations

from mythgauntlet.sim.tier2 import (
    ResolvedEffect,
    _apply_resolved,
    _Permanent,
    _Player,
    _is_until_end_of_turn,
    expire_until_end_of_turn,
)


def _perm(power: int = 2, toughness: int = 2) -> _Permanent:
    return _Permanent(name="Bear", power=power, toughness=toughness, is_creature=True)


def _player(*perms: _Permanent) -> _Player:
    p = _Player(name="P", library=[])
    p.battlefield = list(perms)
    return p


def _pump(**params) -> ResolvedEffect:
    return ResolvedEffect(op="pump", params=params)


# --- duration classification -------------------------------------------------------

def test_every_real_spelling_of_until_end_of_turn_is_recognised():
    """Six spellings appear in the live store; missing one makes a pump permanent."""
    for spelling in (
        "until end of turn", "until_end_of_turn", "this turn", "this_turn",
        "end_of_turn", "until your next turn", "UNTIL END OF TURN",
    ):
        assert _is_until_end_of_turn(spelling), spelling


def test_a_permanent_duration_is_not_treated_as_temporary():
    for spelling in ("permanent", "indefinite", "", None,
                     "as long as this artifact remains tapped"):
        assert not _is_until_end_of_turn(spelling), spelling


# --- the expiry layer --------------------------------------------------------------

def test_a_temporary_pump_is_applied_then_expires():
    perm = _perm(2, 2)
    me = _player(perm)
    _apply_resolved(_pump(power=3, toughness=3, duration="until end of turn"),
                    me, _player(), perm)
    assert (perm.power, perm.toughness) == (5, 5)

    expire_until_end_of_turn([me])
    assert (perm.power, perm.toughness) == (2, 2)
    assert (perm.temp_power, perm.temp_toughness) == (0, 0)


def test_a_pump_with_no_duration_survives_the_cleanup_step():
    """A static/permanent buff must NOT be swept — expiry is opt-in, not blanket."""
    perm = _perm(2, 2)
    me = _player(perm)
    _apply_resolved(_pump(power=1, toughness=1), me, _player(), perm)
    expire_until_end_of_turn([me])
    assert (perm.power, perm.toughness) == (3, 3)


def test_expiry_does_not_undo_a_counter_placed_the_same_turn():
    """add_counter's P/T is permanent; only the pump's delta comes back off."""
    perm = _perm(1, 1)
    me = _player(perm)
    _apply_resolved(ResolvedEffect(op="add_counter", params={"count": 2}), me, _player(), perm)
    _apply_resolved(_pump(power=4, toughness=4, duration="until_end_of_turn"),
                    me, _player(), perm)
    assert (perm.power, perm.toughness) == (7, 7)
    expire_until_end_of_turn([me])
    assert (perm.power, perm.toughness) == (3, 3)  # 1/1 + two counters, pump gone
    assert perm.counters == 2


def test_stacked_temporary_pumps_all_come_off_together():
    perm = _perm(2, 2)
    me = _player(perm)
    for amount in (1, 2, 3):
        _apply_resolved(_pump(power=amount, toughness=0, duration="until end of turn"),
                        me, _player(), perm)
    assert perm.power == 8
    expire_until_end_of_turn([me])
    assert perm.power == 2


def test_expiry_runs_for_every_player_not_just_the_active_one():
    """An opponent's combat trick must not survive into their own turn."""
    mine, theirs = _perm(2, 2), _perm(3, 3)
    me, opp = _player(mine), _player(theirs)
    for perm, player in ((mine, me), (theirs, opp)):
        _apply_resolved(_pump(power=2, toughness=2, duration="until end of turn"),
                        player, _player(), perm)
    expire_until_end_of_turn([me, opp])
    assert (mine.power, theirs.power) == (2, 3)


def test_expiry_is_idempotent():
    """_do_end_step can be reached more than once across a long game."""
    perm = _perm(2, 2)
    me = _player(perm)
    _apply_resolved(_pump(power=3, toughness=3, duration="until end of turn"),
                    me, _player(), perm)
    expire_until_end_of_turn([me])
    expire_until_end_of_turn([me])
    assert (perm.power, perm.toughness) == (2, 2)


# --- what pump deliberately DECLINES ------------------------------------------------

def test_a_chosen_target_is_declined_rather_than_guessed():
    """`target.count: 1` is Giant Growth — a real choice this engine cannot make."""
    perm = _perm(2, 2)
    me = _player(perm)
    _apply_resolved(
        _pump(power=3, toughness=3, duration="until end of turn",
              target={"type": "creature", "count": 1}),
        me, _player(), perm)
    assert (perm.power, perm.toughness) == (2, 2)


def test_mass_pump_is_declined_because_overrun_already_credits_it():
    """Overrun's shape is unambiguous, but sim/overrun.py scores it on the Ceiling axis.

    Executing it here too would put one card on two independently-calibrated axes. That
    is a calibration decision needing a corpus sweep, not a bug fix — pinned so a future
    session has to change this test deliberately rather than by accident.
    """
    perm = _perm(2, 2)
    me = _player(perm)
    _apply_resolved(
        _pump(power=3, toughness=3, duration="until_end_of_turn",
              target={"type": "creature", "controller": "you", "count": "all"}),
        me, _player(), perm)
    assert (perm.power, perm.toughness) == (2, 2)


def test_a_variable_amount_is_declined_rather_than_defaulted_to_one():
    """An unresolved X must not silently become +1/+1 — that fabricates a magnitude."""
    perm = _perm(2, 2)
    me = _player(perm)
    _apply_resolved(_pump(power="x", toughness="x", duration="until end of turn"),
                    me, _player(), perm)
    assert (perm.power, perm.toughness) == (2, 2)


def test_pump_with_no_permanent_to_apply_to_is_a_no_op():
    """A spell_effect resolving with no `just_cast` must not raise."""
    me = _player()
    _apply_resolved(_pump(power=3, toughness=3, duration="until end of turn"),
                    me, _player(), None)  # must not raise
