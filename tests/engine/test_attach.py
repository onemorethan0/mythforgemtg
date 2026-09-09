"""attach (docs/PLAN_FIDELITY.md Phase C, 2026-09-09) -- Equip-class activated abilities.

Never dispatched before this: the target-picking half of the op was easy (a chosen
creature "you control" -- unlike return_to_hand, no graveyard-zone ambiguity is possible
here, since equipment can't attach to a card in a graveyard), but the equipped creature's
actual bonus lived only in a paired static ability's free-text `note`, with no structured
field anywhere. `semantics.compiler.parse_attach_grant` deterministically reads the FIXED,
unconditional subset of that note (a plain P/T delta and/or a closed set of boolean
keyword grants) onto the attach effect itself as `grant_power`/`grant_toughness`/
`grant_keywords`; this tests the simulator side that applies it.
"""

from __future__ import annotations

from types import SimpleNamespace

from mythgauntlet.semantics.interpreter import ResolvedEffect
from mythgauntlet.sim.tier2 import _apply_resolved, _bounce, _kill, _Permanent, _Player


def _gc(name: str, impact: float = 1.0):
    return SimpleNamespace(name=name, profile=SimpleNamespace(impact=impact))


def _creature(name: str, power: int = 1, toughness: int = 1, keywords=()) -> _Permanent:
    return _Permanent(name=name, power=power, toughness=toughness, is_creature=True,
                      sick=False, keywords=frozenset(keywords), source=_gc(name))


def _equipment(name: str = "Equipment") -> _Permanent:
    return _Permanent(name=name, power=0, toughness=0, is_creature=False, is_artifact=True,
                      sick=False, source=_gc(name))


def _eff(**params) -> ResolvedEffect:
    return ResolvedEffect(op="attach", params=params)


# --- the core grant --------------------------------------------------------------------


def test_attach_grants_power_toughness_and_keywords():
    me = _Player(name="a", library=[])
    equip = _equipment()
    beast = _creature("Beast", power=2, toughness=2)
    me.battlefield = [equip, beast]
    eff = _eff(target={"type": "creature", "controller": "you", "count": 1},
               grant_power=2, grant_toughness=1, grant_keywords=["vigilance"])
    _apply_resolved(eff, me, _Player(name="b", library=[]), equip)
    assert beast.power == 4 and beast.toughness == 3
    assert beast.has_keyword("vigilance")
    assert equip.attached_to is beast
    assert equip.attach_grant == (2, 1, frozenset({"vigilance"}))


def test_attach_accepts_a_single_string_keyword_not_just_a_list():
    me = _Player(name="a", library=[])
    equip = _equipment()
    beast = _creature("Beast")
    me.battlefield = [equip, beast]
    eff = _eff(target={"type": "creature", "controller": "you", "count": 1},
               grant_keywords="flying")
    _apply_resolved(eff, me, _Player(name="b", library=[]), equip)
    assert beast.has_keyword("flying")


def test_attach_with_no_grant_fields_moves_nothing_observable():
    """A static note the compiler couldn't reduce to a fixed grant (scaling, a granted
    type, free-text ability) carries no grant_* fields -- an honest omission."""
    me = _Player(name="a", library=[])
    equip = _equipment()
    beast = _creature("Beast", power=2, toughness=2)
    me.battlefield = [equip, beast]
    eff = _eff(target={"type": "creature", "controller": "you", "count": 1})
    _apply_resolved(eff, me, _Player(name="b", library=[]), equip)
    assert beast.power == 2 and beast.toughness == 2
    assert equip.attached_to is None


# --- picking WHICH creature -------------------------------------------------------------


def test_prefers_a_creature_that_does_not_already_have_the_granted_keyword():
    me = _Player(name="a", library=[])
    equip = _equipment()
    already_flies = _creature("Already Flies", power=5, toughness=5, keywords=("flying",))
    grounded = _creature("Grounded", power=1, toughness=1)
    me.battlefield = [equip, already_flies, grounded]
    eff = _eff(target={"type": "creature", "controller": "you", "count": 1},
               grant_keywords=["flying"])
    _apply_resolved(eff, me, _Player(name="b", library=[]), equip)
    assert grounded.has_keyword("flying")
    assert equip.attached_to is grounded


def test_among_equally_eligible_creatures_prefers_the_highest_power():
    me = _Player(name="a", library=[])
    equip = _equipment()
    small = _creature("Small", power=1, toughness=1)
    big = _creature("Big", power=6, toughness=6)
    me.battlefield = [equip, small, big]
    eff = _eff(target={"type": "creature", "controller": "you", "count": 1},
               grant_power=1, grant_toughness=1)
    _apply_resolved(eff, me, _Player(name="b", library=[]), equip)
    assert equip.attached_to is big
    assert big.power == 7


def test_no_creature_to_equip_declines_cleanly():
    me = _Player(name="a", library=[])
    equip = _equipment()
    me.battlefield = [equip]
    eff = _eff(target={"type": "creature", "controller": "you", "count": 1}, grant_power=2)
    _apply_resolved(eff, me, _Player(name="b", library=[]), equip)
    assert equip.attached_to is None


def test_opponent_controlled_target_stays_declined():
    """Scoped to controller:'you' -- the dominant real shape; a target on someone else's
    board is a different (rarer) case not attempted here."""
    me = _Player(name="a", library=[])
    equip = _equipment()
    beast = _creature("Beast")
    me.battlefield = [equip, beast]
    eff = _eff(target={"type": "creature", "controller": "opponent", "count": 1}, grant_power=2)
    _apply_resolved(eff, me, _Player(name="b", library=[]), equip)
    assert equip.attached_to is None
    assert beast.power == 1


# --- detaching: the equipment leaves ----------------------------------------------------


def test_equipment_destroyed_reverses_its_grant():
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    equip = _equipment()
    beast = _creature("Beast", power=2, toughness=2)
    me.battlefield = [equip, beast]
    _apply_resolved(_eff(target={"type": "creature", "controller": "you", "count": 1},
                         grant_power=3, grant_toughness=3, grant_keywords=["trample"]),
                    me, opp, equip)
    assert beast.power == 5 and beast.has_keyword("trample")
    _kill(me, equip, opp)
    assert beast.power == 2 and beast.toughness == 2
    assert not beast.has_keyword("trample")


def test_equipment_bounced_reverses_its_grant_too():
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    equip = _equipment()
    beast = _creature("Beast", power=2, toughness=2)
    me.battlefield = [equip, beast]
    _apply_resolved(_eff(target={"type": "creature", "controller": "you", "count": 1},
                         grant_power=2), me, opp, equip)
    assert beast.power == 4
    _bounce(me, equip)
    assert beast.power == 2


def test_a_printed_keyword_survives_its_equipment_leaving():
    """granted_keywords is a SEPARATE set from printed keywords -- removing the grant
    must never delete a keyword the creature actually has printed."""
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    equip = _equipment()
    flyer = _creature("Flyer", keywords=("flying",))
    me.battlefield = [equip, flyer]
    _apply_resolved(_eff(target={"type": "creature", "controller": "you", "count": 1},
                         grant_keywords=["flying"]), me, opp, equip)
    _kill(me, equip, opp)  # destroy the equipment
    assert flyer.has_keyword("flying")  # still true -- it was always printed


# --- detaching: the equipped CREATURE leaves ---------------------------------------------


def test_creature_dying_resets_the_equipments_attachment_state():
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    equip = _equipment()
    beast = _creature("Beast", power=2, toughness=2)
    me.battlefield = [equip, beast]
    _apply_resolved(_eff(target={"type": "creature", "controller": "you", "count": 1},
                         grant_power=3), me, opp, equip)
    _kill(me, beast, opp)
    assert equip.attached_to is None
    assert equip.attach_grant is None
    assert equip in me.battlefield  # the equipment itself survives its creature's death


def test_undying_creature_does_not_carry_a_stale_equipment_bonus_back():
    """The returning permanent is the SAME Python object (Undying) -- without reversing
    the equipment's contribution first, a stale +N/+N would silently survive onto the new
    object, which CR 400.7 forbids."""
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    equip = _equipment()
    beast = _creature("Beast", power=2, toughness=2)
    beast.keywords = frozenset({"undying"})
    me.battlefield = [equip, beast]
    _apply_resolved(_eff(target={"type": "creature", "controller": "you", "count": 1},
                         grant_power=5, grant_toughness=5, grant_keywords=["flying"]),
                    me, opp, equip)
    assert beast.power == 7
    _kill(me, beast, opp)
    assert beast in me.battlefield          # returned via undying
    assert beast.power == 3 and beast.toughness == 3   # 2/2 base + the undying counter only
    assert not beast.has_keyword("flying")  # the equipment's grant did NOT carry over
    assert equip.attached_to is None        # and the equipment is cleanly unattached


# --- re-equipping ------------------------------------------------------------------------


def test_reequipping_the_same_target_does_not_double_the_grant():
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    equip = _equipment()
    only = _creature("Only", power=2, toughness=2)
    me.battlefield = [equip, only]
    grant_eff = _eff(target={"type": "creature", "controller": "you", "count": 1}, grant_power=2)
    _apply_resolved(grant_eff, me, opp, equip)
    assert only.power == 4
    _apply_resolved(grant_eff, me, opp, equip)  # equip activated again, same only option
    assert only.power == 4  # unwound then reapplied, NOT stacked to 6
    assert equip.attached_to is only


def test_moving_equipment_to_a_new_target_removes_the_old_bonus():
    me = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    equip = _equipment()
    first = _creature("First", power=5, toughness=5)
    me.battlefield = [equip, first]
    grant_eff = _eff(target={"type": "creature", "controller": "you", "count": 1}, grant_power=2)
    _apply_resolved(grant_eff, me, opp, equip)
    assert first.power == 7
    second = _creature("Second", power=9, toughness=9)  # now the higher-power pick
    me.battlefield.append(second)
    _apply_resolved(grant_eff, me, opp, equip)
    assert first.power == 5    # unwound
    assert second.power == 11  # newly granted
    assert equip.attached_to is second
