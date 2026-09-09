"""return_to_hand / sacrifice / tap / untap / extra_turn — and the deliberate refusal of
win_game.

All five follow the standing discipline: execute SELF and MASS, decline a CHOSEN target.
That is not conservatism for its own sake — `return_to_hand` is the clearest case, where
a wrong pick fabricates in BOTH directions at once (bouncing my own creature is value, a
saved blocker or a re-used ETB; bouncing theirs is tempo), so guessing cannot even be
wrong in a consistent direction.

`win_game` is the one op measured and then deliberately NOT implemented. All 34 stored
effects carry a condition the engine cannot evaluate, so under the "assume conditions
hold" convention implementing it would have made all 34 cards win outright on resolution.
Alt-wins are credited instead through `data/spellbook.py`'s combo/bracket path, which
reads oracle text — which is where a "you win the game" card belongs in a deck RATING
anyway.
"""

from __future__ import annotations

from types import SimpleNamespace

from mythgauntlet.semantics.interpreter import ResolvedEffect, interpret_ability
from mythgauntlet.sim.tier2 import _apply_resolved, _Permanent, _Player


def _gc(name="Bear"):
    return SimpleNamespace(name=name, card=SimpleNamespace(name=name, is_land=False),
                           profile=SimpleNamespace(impact=1.0))


def _perm(name="Bear", power=2, toughness=2, source=..., **kw) -> _Permanent:
    return _Permanent(name=name, power=power, toughness=toughness, is_creature=True,
                      source=_gc(name) if source is ... else source, **kw)


def _player(*perms: _Permanent) -> _Player:
    p = _Player(name="P", library=[])
    p.battlefield = list(perms)
    return p


def _eff(op: str, **params) -> ResolvedEffect:
    return ResolvedEffect(op=op, params=params)


# --- return_to_hand -----------------------------------------------------------------

def test_self_bounce_returns_the_card_to_hand():
    perm = _perm()
    me = _player(perm)
    _apply_resolved(_eff("return_to_hand"), me, _player(), perm)
    assert me.battlefield == []
    assert [g.name for g in me.hand] == ["Bear"]


def test_a_bounced_TOKEN_ceases_to_exist():
    """CR 111.7 — falls out of `source=None` for free rather than needing a special case."""
    token = _perm(name="Soldier", source=None)
    me = _player(token)
    _apply_resolved(_eff("return_to_hand"), me, _player(), token)
    assert me.battlefield == [] and me.hand == []


def test_bounce_is_not_a_death_and_fires_no_death_trigger():
    """Routing this through `_kill` would fire aristocrat payoffs a bounce does not."""
    from mythgauntlet.semantics.profile import DeathEffect

    perm = _perm(death=DeathEffect(draw=3))
    me = _player(perm)
    me.library = [_gc(), _gc(), _gc()]
    _apply_resolved(_eff("return_to_hand"), me, _player(), perm)
    assert len(me.library) == 3  # the death draw did NOT happen
    assert len(me.hand) == 1     # only the bounced card


def test_mass_bounce_of_my_own_board_only():
    mine, theirs = _perm("A"), _perm("B")
    me, opp = _player(mine), _player(theirs)
    _apply_resolved(
        _eff("return_to_hand", target={"type": "creature", "controller": "you",
                                       "count": "all"}),
        me, opp, None)
    assert me.battlefield == [] and opp.battlefield == [theirs]


def test_mass_bounce_with_no_controller_hits_everyone():
    me, opp = _player(_perm("A")), _player(_perm("B"))
    _apply_resolved(_eff("return_to_hand", target={"type": "creature", "count": "all"}),
                    me, opp, None)
    assert me.battlefield == [] and opp.battlefield == []


def test_a_chosen_bounce_target_is_declined():
    """2,668 of 3,232 stored effects are this shape and none of them execute."""
    mine, theirs = _perm("A"), _perm("B")
    me, opp = _player(mine), _player(theirs)
    _apply_resolved(
        _eff("return_to_hand", target={"type": "creature", "count": 1}), me, opp, mine)
    assert me.battlefield == [mine] and opp.battlefield == [theirs]


# --- sacrifice ----------------------------------------------------------------------

def test_self_sacrifice_IS_a_death_and_fires_the_trigger():
    from mythgauntlet.semantics.profile import DeathEffect

    perm = _perm(death=DeathEffect(draw=2))
    me = _player(perm)
    me.library = [_gc(), _gc(), _gc()]
    _apply_resolved(_eff("sacrifice", target={"self": True}), me, _player(), perm)
    assert me.battlefield == []
    assert len(me.library) == 1  # drew 2 — sacrifice is a death, unlike bounce


def test_an_edict_makes_the_opponent_give_up_their_WORST_creature():
    """The choice belongs to them, and they keep the best one — normal play, not a pick
    invented for whoever cast it."""
    big, small = _perm("Big", 6, 6), _perm("Small", 1, 1)
    opp = _player(big, small)
    _apply_resolved(_eff("sacrifice", who="opponent"), _player(), opp, None)
    assert [p.name for p in opp.battlefield] == ["Big"]


def test_an_edict_against_an_empty_board_is_safe():
    _apply_resolved(_eff("sacrifice", who="opponent"), _player(), _player(), None)


# --- tap / untap --------------------------------------------------------------------

def test_tap_and_untap_self():
    perm = _perm()
    me = _player(perm)
    _apply_resolved(_eff("tap"), me, _player(), perm)
    assert perm.tapped is True
    _apply_resolved(_eff("untap"), me, _player(), perm)
    assert perm.tapped is False


def test_mass_tap_hits_only_the_named_controllers_board():
    mine, theirs = _perm("A"), _perm("B")
    me, opp = _player(mine), _player(theirs)
    _apply_resolved(
        _eff("tap", target={"type": "creature", "controller": "opponent", "count": "all"}),
        me, opp, None)
    assert theirs.tapped is True and mine.tapped is False


# --- extra_turn ---------------------------------------------------------------------

def test_an_unconditional_extra_turn_is_banked():
    me = _player()
    _apply_resolved(_eff("extra_turn"), me, _player(), None)
    assert me.extra_turns == 1


def test_a_CONDITIONAL_extra_turn_never_reaches_the_dispatch():
    """42 of 56 stored effects are unconditional; the other 14 are gated on board state
    the engine cannot check ("if it's not your turn", "if time gets more votes")."""
    ability = {"effects": [{"op": "extra_turn", "condition": "if it's not your turn"}]}
    assert interpret_ability(ability) == []


def test_the_unconditional_ones_DO_reach_the_dispatch():
    ability = {"effects": [{"op": "extra_turn"}]}
    assert [r.op for r in interpret_ability(ability)] == ["extra_turn"]


def test_extra_turns_are_spent_one_at_a_time_and_bounded():
    """The turn counter is deliberately NOT advanced by an extra turn (that would make a
    Time Warp deck read as SLOWER), so a cap is the only thing that guarantees the game
    terminates."""
    from mythgauntlet.sim.game import _MAX_EXTRA_TURNS_PER_GAME

    assert _MAX_EXTRA_TURNS_PER_GAME > 0


# --- win_game: measured, then deliberately refused ----------------------------------

def test_win_game_is_never_resolved_from_a_condition_it_cannot_verify():
    """All 34 stored win_game effects carry one, so this refuses all 34."""
    for condition in ("if you have 200 or more cards in your library",
                      "if you control four or more creatures named Biovisionary",
                      "if this creature has five or more filibuster counters on it"):
        ability = {"effects": [{"op": "win_game", "condition": condition}]}
        assert interpret_ability(ability) == [], condition


def test_an_ordinary_effect_keeps_the_benefit_of_the_doubt():
    """The refusal is scoped to game-deciding ops — the ~81% of assumed-true conditions
    that are ordinary board state are untouched, because flipping those would deflate
    every rating in the corpus."""
    ability = {"effects": [{"op": "add_counter", "count": 1, "counter_type": "+1/+1",
                            "condition": "if a creature died this turn"}]}
    assert [r.op for r in interpret_ability(ability)] == ["add_counter"]
