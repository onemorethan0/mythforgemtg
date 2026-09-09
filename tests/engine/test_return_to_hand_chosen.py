"""return_to_hand's chosen-target picker (docs/PLAN_FIDELITY.md Phase C, 2026-09-09).

Self and mass were the only executed shapes before this; a chosen target was declined
entirely (2,686 of 3,324 stored effects) because picking one could fabricate in either
direction. This unlocks the two UNAMBIGUOUS controller directions only -- "you" (protect/
re-trigger the permanent whose card is worth the most) and "opponent" + type:creature
(bounce their biggest threat, reusing _instant_target's own metric) -- and keeps declining
everything genuinely ambiguous (any/absent controller, a non-battlefield zone or type).
"""

from __future__ import annotations

from types import SimpleNamespace

from mythgauntlet.semantics.interpreter import ResolvedEffect
from mythgauntlet.sim.tier2 import _apply_resolved, _Permanent, _Player


def _gc(name: str, impact: float = 1.0):
    return SimpleNamespace(name=name, profile=SimpleNamespace(impact=impact))


def _perm(name: str, power: int = 1, toughness: int = 1, impact: float | None = None,
          is_token: bool = False) -> _Permanent:
    return _Permanent(
        name=name, power=power, toughness=toughness, is_creature=True, sick=False,
        source=None if is_token else _gc(name, impact if impact is not None else 1.0),
    )


def _eff(op: str, **params) -> ResolvedEffect:
    return ResolvedEffect(op=op, params=params)


# --- controller: "you" -- bounce the one worth the most to protect/re-trigger --------------


def test_chosen_you_bounces_the_highest_impact_permanent_i_control():
    me = _Player(name="a", library=[])
    weak = _perm("Weak", impact=1.0)
    strong = _perm("Strong", impact=9.0)
    me.battlefield = [weak, strong]
    eff = _eff("return_to_hand", target={"type": "creature", "controller": "you", "count": 1})
    _apply_resolved(eff, me, _Player(name="b", library=[]), None)
    assert strong not in me.battlefield
    assert weak in me.battlefield
    assert any(gc.name == "Strong" for gc in me.hand)


def test_chosen_you_excludes_the_permanent_whose_ability_is_resolving():
    """A bounce ability's own target is conventionally 'ANOTHER target permanent you
    control' -- the resolving permanent itself must never be a candidate."""
    me = _Player(name="a", library=[])
    resolving = _perm("Resolving Source", impact=99.0)  # highest impact, but excluded
    other = _perm("Other", impact=1.0)
    me.battlefield = [resolving, other]
    eff = _eff("return_to_hand", target={"type": "creature", "controller": "you", "count": 1})
    _apply_resolved(eff, me, _Player(name="b", library=[]), resolving)
    assert other not in me.battlefield
    assert resolving in me.battlefield


def test_chosen_you_a_token_is_never_picked_it_has_no_card_to_recast():
    me = _Player(name="a", library=[])
    token = _perm("Token", impact=None, is_token=True)
    real = _perm("Real Card", impact=0.1)  # low impact, but still the only real candidate
    me.battlefield = [token, real]
    eff = _eff("return_to_hand", target={"type": "creature", "controller": "you", "count": 1})
    _apply_resolved(eff, me, _Player(name="b", library=[]), None)
    assert real not in me.battlefield
    assert token in me.battlefield


# --- controller: "opponent" + type creature -- bounce their biggest threat -----------------


def test_chosen_opponent_bounces_their_biggest_power_creature():
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    small = _perm("Small", power=1)
    big = _perm("Big", power=7)
    opp.battlefield = [small, big]
    eff = _eff("return_to_hand", target={"type": "creature", "controller": "opponent", "count": 1})
    _apply_resolved(eff, me, opp, None)
    assert big not in opp.battlefield
    assert small in opp.battlefield
    assert any(gc.name == "Big" for gc in opp.hand)


def test_chosen_opponent_reaches_across_the_whole_pod_not_just_the_primary_seat():
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    third = _Player(name="c", library=[])
    opp.battlefield = [_perm("Opp Small", power=1)]
    third.battlefield = [_perm("Third Big", power=8)]
    eff = _eff("return_to_hand", target={"type": "creature", "controller": "opponent", "count": 1})
    _apply_resolved(eff, me, opp, None, others=(third,))
    assert not third.battlefield
    assert any(gc.name == "Third Big" for gc in third.hand)


# --- still declined: ambiguous controller, non-battlefield zone/type -----------------------


def test_chosen_any_controller_stays_declined():
    """The caster could legally hit either side -- guessing which one the card wants would
    fabricate (measured: 53% of the chosen population is any/absent)."""
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    mine = _perm("Mine", impact=9.0)
    theirs = _perm("Theirs", power=9)
    me.battlefield = [mine]
    opp.battlefield = [theirs]
    eff = _eff("return_to_hand", target={"type": "creature", "controller": "any", "count": 1})
    _apply_resolved(eff, me, opp, None)
    assert mine in me.battlefield
    assert theirs in opp.battlefield


def test_chosen_absent_controller_stays_declined():
    me = _Player(name="a", library=[])
    mine = _perm("Mine", impact=9.0)
    me.battlefield = [mine]
    eff = _eff("return_to_hand", target={"type": "creature", "count": 1})
    _apply_resolved(eff, me, _Player(name="b", library=[]), None)
    assert mine in me.battlefield


def test_chosen_graveyard_zone_stays_declined_no_graveyard_zone_exists():
    me = _Player(name="a", library=[])
    mine = _perm("Mine", impact=9.0)
    me.battlefield = [mine]
    eff = _eff("return_to_hand",
               target={"type": "creature", "controller": "you", "zone": "graveyard", "count": 1})
    _apply_resolved(eff, me, _Player(name="b", library=[]), None)
    assert mine in me.battlefield  # nothing to pick from a zone this engine doesn't model


def test_chosen_opponent_non_creature_type_stays_declined():
    """Scoped to creatures only for the opponent direction -- 'biggest by power' is not a
    meaningful ranking for an artifact/land/enchantment (power is always 0)."""
    opp = _Player(name="b", library=[])
    artifact = _Permanent(name="Their Artifact", power=0, toughness=0, is_creature=False,
                          is_artifact=True, sick=False, source=_gc("Their Artifact"))
    opp.battlefield = [artifact]
    eff = _eff("return_to_hand", target={"type": "artifact", "controller": "opponent", "count": 1})
    _apply_resolved(eff, _Player(name="a", library=[]), opp, None)
    assert artifact in opp.battlefield
