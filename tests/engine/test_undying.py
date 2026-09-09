"""Undying (CR 702.92c), docs/PLAN_FIDELITY.md Phase C (found while investigating `reanimate`,
which turned out to have no dispatch anywhere in the simulator -- Undying/Persist creatures are
the one slice of that population reachable through the EXISTING death-effect hook in `_kill`,
via `Card.keywords` rather than the CCM's own inconsistent `reanimate` op). Persist (the -1/-1
mirror) stays declined: `.counters` doesn't distinguish counter types.
"""

from __future__ import annotations

from mythgauntlet.sim.tier2 import DeathEffect, _kill, _Permanent, _Player


def _undying(name="Undying Beast", power=2, toughness=2, counters=0, **kw) -> _Permanent:
    return _Permanent(name=name, power=power, toughness=toughness, is_creature=True,
                      sick=False, counters=counters, keywords=frozenset({"undying"}), **kw)


def test_undying_returns_with_a_plus_one_plus_one_counter():
    owner = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    beast = _undying()
    owner.battlefield.append(beast)
    _kill(owner, beast, opp)
    assert beast in owner.battlefield
    assert beast.counters == 1
    assert beast.power == 3 and beast.toughness == 3  # 2/2 base + the counter


def test_undying_does_not_return_a_creature_that_already_had_a_counter():
    """CR 702.92c: only fires if it had NO +1/+1 counters on it when it died."""
    owner = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    beast = _undying(counters=1, power=3, toughness=3)
    owner.battlefield.append(beast)
    _kill(owner, beast, opp)
    assert beast not in owner.battlefield


def test_a_creature_without_undying_stays_dead():
    owner = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    plain = _Permanent(name="Plain Beast", power=2, toughness=2, is_creature=True, sick=False)
    owner.battlefield.append(plain)
    _kill(owner, plain, opp)
    assert plain not in owner.battlefield


def test_returning_creature_is_summoning_sick_and_untapped():
    """CR 400.7: a permanent returning to the battlefield is a NEW object."""
    owner = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    beast = _undying()
    beast.sick = False
    beast.tapped = True
    owner.battlefield.append(beast)
    _kill(owner, beast, opp)
    assert beast.sick is True
    assert beast.tapped is False


def test_returning_creature_sheds_its_until_end_of_turn_buff():
    """The new object carries none of the old one's temporary effects -- a Giant-Growthed
    undying creature that dies in combat comes back at its printed stats plus the counter,
    not with the stale +3/+3 baked in."""
    owner = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    beast = _undying(power=5, toughness=5)  # 2/2 base + a live +3/+3 until end of turn
    beast.temp_power = 3
    beast.temp_toughness = 3
    owner.battlefield.append(beast)
    _kill(owner, beast, opp)
    assert beast.power == 3 and beast.toughness == 3  # 2/2 base + the undying counter only
    assert beast.temp_power == 0 and beast.temp_toughness == 0


def test_undying_commander_returns_directly_not_to_the_command_zone():
    owner = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    beast = _undying(name="Commander Beast", is_commander=True)
    owner.battlefield.append(beast)
    _kill(owner, beast, opp)
    assert beast in owner.battlefield
    assert owner.commander_in_zone is False


def test_undying_survives_a_mass_wipe_and_fires_once_per_creature():
    """Mirrors _wipe_table's own snapshot-then-kill loop -- an undying creature returns
    once, with a counter that then blocks it from re-triggering, matching real play."""
    owner = _Player(name="a", library=[])
    opp = _Player(name="b", library=[])
    beast = _undying()
    plain = _Permanent(name="Plain", power=1, toughness=1, is_creature=True, sick=False)
    owner.battlefield = [beast, plain]
    for creature in list(owner.creatures()):
        _kill(owner, creature, opp)
    assert owner.creatures() == [beast]  # only the undying one is back
    assert beast.counters == 1


def test_undying_composes_with_an_existing_death_effect():
    """A card can have both a real death payoff (drain/draw/tokens) and undying -- the
    counter/return must not suppress the other death-trigger mutation, or vice versa."""
    owner = _Player(name="a", library=[], life=40)
    opp = _Player(name="b", library=[], life=40)
    beast = _undying()
    beast.death = DeathEffect(drain=3)
    owner.battlefield.append(beast)
    _kill(owner, beast, opp)
    assert opp.life == 37          # the death-drain still fired
    assert beast in owner.battlefield  # AND it came back via undying
    assert beast.counters == 1
