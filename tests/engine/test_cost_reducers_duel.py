"""Static cost reducers in the duel simulator (docs/BACKLOG.md B3). Legality and payment share ONE
helper, `tier2.cast_cost`, so a card is never offered that cannot then be paid for. Tier 0 (the
bracket path) deliberately ignores reducers; see sim/cost_rules.py."""
from __future__ import annotations

from mythgauntlet.model.card import ManaCost
from mythgauntlet.sim import cost_rules
from mythgauntlet.sim.game import MAIN, CastSpell, GameState, advance, apply, legal_actions
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import DuelConfig, _Permanent, _Player, cast_cost, make_game_card


# -- the rules module --------------------------------------------------------------------------------

def test_reducers_are_read_from_whole_oracle_lines_and_not_from_instants():
    assert cost_rules.reducers_in_text("Flash\nCreature spells you cast cost {1} less to cast.") == (
        ("creature spells", 1),)
    assert cost_rules.reducers_in_text("Spells cost {1} less to cast.") == ()          # all players: declined
    assert cost_rules.reducers_in_text("") == ()


def test_an_instant_or_sorcery_never_provides_a_static_reducer(make_card):
    sorc = make_card("Not A Medallion", type_line="Sorcery", oracle_text="Spells you cast cost {1} less to cast.")
    art = make_card("Medallion", type_line="Artifact", oracle_text="Spells you cast cost {1} less to cast.")
    assert cost_rules.reducers_for_card(sorc) == ()
    assert cost_rules.reducers_for_card(art) == (("spells", 1),)


def test_discounted_never_goes_below_the_coloured_requirement():
    cost = ManaCost.parse("{2}{W}")
    assert cost_rules.discounted(cost, 1).generic == 1 and cost_rules.discounted(cost, 1).mana_value == 2
    assert cost_rules.discounted(cost, 99).generic == 0 and cost_rules.discounted(cost, 99).mana_value == 1
    assert cost_rules.discounted(cost, 0) is cost and cost_rules.discounted(cost, -3) is cost


def test_matching_by_card_type_and_colour(make_card):
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature — Bear", colors=("G",))
    bolt = make_card("Bolt", mana_cost="{R}", type_line="Instant", colors=("R",))
    rock = make_card("Rock", mana_cost="{2}", type_line="Artifact")
    assert cost_rules.matches("creature spells", bear) and not cost_rules.matches("creature spells", bolt)
    assert cost_rules.matches("instant and sorcery spells", bolt)
    assert cost_rules.matches("noncreature spells", rock) and not cost_rules.matches("noncreature spells", bear)
    assert cost_rules.matches("green spells", bear) and not cost_rules.matches("green spells", bolt)
    assert cost_rules.matches("colorless spells", rock) and cost_rules.matches("artifact spells", rock)


# -- cast_cost -----------------------------------------------------------------------------------------------------

def _medallion(subject_text="Creature spells you cast cost {1} less to cast.", creature=False):
    return _Permanent(name="Medallion", power=0, toughness=0, is_creature=creature,
                      cost_reducers=cost_rules.reducers_in_text(subject_text))


def _fatty(make_card):
    card = make_card("Fatty", mana_cost="{2}{G}", type_line="Creature — Beast", colors=("G",), color_identity=("G",))
    card.power, card.toughness = "3", "3"
    return make_game_card(card, None)


def test_cast_cost_without_a_reducer_is_the_printed_cost(make_card):
    gc = _fatty(make_card)
    p = _Player(name="a", library=[])
    assert cast_cost(p, gc) == gc.card.cost


def test_cast_cost_applies_every_matching_reducer_and_ignores_others(make_card):
    gc = _fatty(make_card)
    p = _Player(name="a", library=[], battlefield=[_medallion(), _medallion(),
                                                   _medallion("Instant and sorcery spells you cast cost {1} less to cast.")])
    assert cast_cost(p, gc).generic == 0                       # two creature reducers: {2}{G} -> {G}
    assert cast_cost(p, gc).mana_value == 1


def test_an_opponents_reducer_does_not_help_me(make_card):
    gc = _fatty(make_card)
    me, foe = _Player(name="a", library=[]), _Player(name="b", library=[], battlefield=[_medallion()])
    assert cast_cost(me, gc) == gc.card.cost and cast_cost(foe, gc).generic == 1


def test_a_reducer_that_leaves_the_battlefield_stops_applying(make_card):
    gc = _fatty(make_card)
    m = _medallion()
    p = _Player(name="a", library=[], battlefield=[m])
    assert cast_cost(p, gc).generic == 1
    p.battlefield.remove(m)
    assert cast_cost(p, gc).generic == 2


# -- legality and payment agree --------------------------------------------------------------------------------------------

def _main_state(me, foe):
    st = GameState(players={"a": me, "b": foe}, order=["a", "b"], cfg=DuelConfig(), active="a", phase=MAIN)
    advance(st)
    return st


def _sources(n):
    return [_Source(frozenset("G")) for _ in range(n)]


def test_a_discount_makes_an_unaffordable_spell_castable_and_payable(make_card):
    gc = _fatty(make_card)                                      # {2}{G}: three mana
    me = _Player(name="a", library=[], hand=[gc], sources=_sources(2), life=40)
    foe = _Player(name="b", library=[], life=40)
    st = _main_state(me, foe)
    assert not any(isinstance(a, CastSpell) for a in legal_actions(st))      # 2 mana, needs 3

    me2 = _Player(name="a", library=[], hand=[_fatty(make_card)], sources=_sources(2), life=40,
                  battlefield=[_medallion()])
    st2 = _main_state(me2, _Player(name="b", library=[], life=40))
    casts = [a for a in legal_actions(st2) if isinstance(a, CastSpell)]
    assert casts, "the discounted creature should be castable with two sources"
    apply(st2, casts[0])                                                       # must not trip 'unpayable cast'
    advance(st2)                                                               # the spell waits in the counter window
    assert any(p.name == "Fatty" for p in me2.battlefield)
    assert sum(1 for s in me2.sources if s.ready) == 0                        # it really spent 2, not 3


def test_a_nonmatching_reducer_does_not_make_it_castable(make_card):
    me = _Player(name="a", library=[], hand=[_fatty(make_card)], sources=_sources(2), life=40,
                 battlefield=[_medallion("Artifact spells you cast cost {2} less to cast.")])
    st = _main_state(me, _Player(name="b", library=[], life=40))
    assert not any(isinstance(a, CastSpell) for a in legal_actions(st))
