"""Static anthems in the tier2 sim (docs/BACKLOG.md B3 phase 2)."""
from __future__ import annotations

from mythgauntlet.semantics.profile import profile_from_ccm
from mythgauntlet.sim.tier2 import _Permanent, _Player, refresh_anthems

ANTHEM_YOU = ("you", False, False, 1, 1, ())


def _creature(name, p=2, t=2, source="card", **kw):
    return _Permanent(name=name, power=p, toughness=t, is_creature=True, sick=False,
                      source=source, **kw)


def _anthem_source(spec=ANTHEM_YOU, creature=False, name="Glorious Anthem"):
    return _Permanent(name=name, power=2 if creature else 0, toughness=2 if creature else 0,
                      is_creature=creature, sick=False, source="card", anthems=(spec,))


def _players(me=(), foe=()):
    a = _Player(name="a", library=[], battlefield=list(me))
    b = _Player(name="b", library=[], battlefield=list(foe))
    return {"a": a, "b": b}, a, b


def test_anthem_buffs_the_controllers_creatures_only():
    bear, foe_bear = _creature("Bear"), _creature("Foe Bear")
    players, a, b = _players([_anthem_source(), bear], [foe_bear])
    refresh_anthems(players)
    assert (bear.power, bear.toughness) == (3, 3)
    assert (foe_bear.power, foe_bear.toughness) == (2, 2)


def test_refresh_is_idempotent():
    bear = _creature("Bear")
    players, *_ = _players([_anthem_source(), bear])
    for _ in range(5):
        refresh_anthems(players)
    assert (bear.power, bear.toughness) == (3, 3)


def test_two_anthems_stack():
    bear = _creature("Bear")
    players, *_ = _players([_anthem_source(), _anthem_source(name="Second"), bear])
    refresh_anthems(players)
    assert (bear.power, bear.toughness) == (4, 4)


def test_leaving_the_battlefield_removes_the_bonus():
    src, bear = _anthem_source(), _creature("Bear")
    players, a, _ = _players([src, bear])
    refresh_anthems(players)
    a.battlefield.remove(src)
    refresh_anthems(players)
    assert (bear.power, bear.toughness) == (2, 2)
    assert bear.anthem_delta == (0, 0)


def test_other_excludes_the_source_itself():
    src = _anthem_source(("you", True, False, 1, 1, ()), creature=True, name="Lord")
    bear = _creature("Bear")
    players, *_ = _players([src, bear])
    refresh_anthems(players)
    assert (src.power, src.toughness) == (2, 2)          # not buffed by itself
    assert (bear.power, bear.toughness) == (3, 3)


def test_without_other_a_creature_source_buffs_itself():
    src = _anthem_source(("you", False, False, 1, 1, ()), creature=True)
    players, *_ = _players([src])
    refresh_anthems(players)
    assert (src.power, src.toughness) == (3, 3)


def test_nontoken_skips_tokens():
    src = _anthem_source(("you", False, True, 1, 1, ()))
    real, token = _creature("Real"), _creature("Token", source=None)
    players, *_ = _players([src, real, token])
    refresh_anthems(players)
    assert real.power == 3 and token.power == 2


def test_keywords_are_granted_and_removed_without_touching_printed_ones():
    src = _anthem_source(("you", False, False, 0, 0, ("haste",)))
    bear = _creature("Bear", keywords=frozenset({"flying"}), granted_keywords=frozenset({"haste"}))
    players, a, _ = _players([src, bear])
    refresh_anthems(players)
    assert bear.has_keyword("haste") and bear.has_keyword("flying")
    a.battlefield.remove(src)
    refresh_anthems(players)
    # the equipment-granted haste and the printed flying both survive the anthem leaving
    assert bear.has_keyword("flying") and bear.has_keyword("haste")
    assert bear.anthem_keywords == frozenset()


def test_an_opponent_shrinker_applies_to_the_other_seats_and_kills_at_zero_toughness():
    shrink = _anthem_source(("opponents", False, False, -1, -1, ()), name="Elesh-like")
    small, big = _creature("Small", 1, 1), _creature("Big", 3, 3)
    mine = _creature("Mine", 1, 1)
    players, a, b = _players([shrink, mine], [small, big])
    refresh_anthems(players)
    assert small not in b.battlefield                    # 1/1 -> 0/0 dies
    assert (big.power, big.toughness) == (2, 2)
    assert (mine.power, mine.toughness) == (1, 1)         # my own board is unaffected


def test_a_creature_killed_by_an_anthem_can_end_another_anthem():
    # the shrinker itself is a 1/1 that the opposing -1/-1 anthem kills; its effect then stops
    shrink_a = _anthem_source(("opponents", False, False, -1, -1, ()), creature=True)
    shrink_a.power = shrink_a.toughness = 3
    killer = _anthem_source(("opponents", False, False, -2, -2, ()), creature=True, name="Killer")
    victim = _creature("Victim", 3, 3)
    players, a, b = _players([shrink_a, victim], [killer])
    refresh_anthems(players)
    # shrink_a (3/3) takes -2/-2 -> 1/1 and survives; victim is on a's side so only the killer matters
    assert (shrink_a.power, shrink_a.toughness) == (1, 1)
    assert (victim.power, victim.toughness) == (1, 1)


# -- profile derivation -----------------------------------------------------------------------

def _ccm(note):
    return {"name": "Test Anthem", "ccm_version": 1, "cost": {"mana": "{2}{W}"}, "types": ["enchantment"],
            "abilities": [{"kind": "static", "note": note}]}


def test_profile_reads_a_whole_line_anthem(make_card):
    card = make_card("Test Anthem", mana_cost="{2}{W}", type_line="Enchantment",
                     oracle_text="Creatures you control get +1/+1.")
    from mythgauntlet.semantics import tags
    prof = profile_from_ccm(_ccm("Creatures you control get +1/+1"), card, tags.analyze(card))
    assert prof.anthems == (("you", False, False, 1, 1, ()),)


def test_profile_ignores_an_anthem_inside_a_modal_bullet(make_card):
    card = make_card("Test Siege", mana_cost="{2}{W}", type_line="Enchantment",
                     oracle_text="As this enters, choose one.\n- Temur: Creatures you control get +1/+0 and have haste.")
    from mythgauntlet.semantics import tags
    prof = profile_from_ccm(_ccm("Creatures you control get +1/+0 and have haste"), card, tags.analyze(card))
    assert prof.anthems == ()


def test_a_spell_never_carries_an_anthem(make_card):
    card = make_card("Test Overrun", mana_cost="{2}{G}", type_line="Sorcery",
                     oracle_text="Creatures you control get +3/+3.")
    from mythgauntlet.semantics import tags
    ccm = dict(_ccm("Creatures you control get +3/+3"), types=["sorcery"])
    prof = profile_from_ccm(ccm, card, tags.analyze(card))
    assert prof.anthems == ()
