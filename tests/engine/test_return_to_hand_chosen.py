"""return_to_hand's chosen-target picker (docs/PLAN_FIDELITY.md Phase C, 2026-09-09).

Self and mass were the only executed shapes before this; a chosen target was declined
entirely (2,686 of 3,324 stored effects) because picking one could fabricate. This unlocks
ONE direction: "opponent" + type:creature (bounce their biggest threat, reusing
_instant_target's own metric). Everything else stays declined, including "controller: you"
-- shipped once (protect/re-trigger the permanent worth the most), then PULLED after a
live re-measurement: a random 30-card sample of "controller: you", no explicit zone found
ZERO genuine battlefield bounces -- every one turned out to be graveyard-recursion text
("return target creature card from your graveyard to your hand/battlefield") with the zone
field simply omitted by the compiler, not stated on the effect at all. This engine has no
graveyard zone, so those correctly stay declined; there was no reliable signal in the
compiled CCM to separate the two shapes, so picking would have executed the WRONG effect,
not just under-counted. The surviving "opponent" direction's own version of this risk
measured far lower (~5%, concentrated in unusual delegated-choice/multi-step cards) and its
flagship real-card verification (Into the Flood Maw) is unambiguously correct, so it stays.
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


# --- controller: "you" -- DECLINED (pulled after live measurement, see module docstring) --


def test_chosen_you_stays_declined_even_with_a_clearly_better_pick_available():
    """This USED to bounce the highest-impact permanent -- reverted because "controller:
    you" with no explicit zone turned out to be overwhelmingly graveyard-recursion text
    with the zone field simply omitted, not a battlefield protect/re-trigger. Regression
    pin: even an unambiguous-looking "better" candidate must not be picked."""
    me = _Player(name="a", library=[])
    weak = _perm("Weak", impact=1.0)
    strong = _perm("Strong", impact=9.0)
    me.battlefield = [weak, strong]
    eff = _eff("return_to_hand", target={"type": "creature", "controller": "you", "count": 1})
    _apply_resolved(eff, me, _Player(name="b", library=[]), None)
    assert weak in me.battlefield
    assert strong in me.battlefield
    assert not me.hand


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
