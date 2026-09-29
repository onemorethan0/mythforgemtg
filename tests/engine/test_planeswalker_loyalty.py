"""Planeswalker loyalty abilities: cost read from ORACLE TEXT, paid in loyalty, once per turn.

Before this, a compiled loyalty cost such as {"mana": "{2}"} (a -2) was read as two generic
mana and executed repeatedly with no loyalty at all -- 179 abilities across 88 cards.
"""

from __future__ import annotations

from mythgauntlet.semantics import profile
from mythgauntlet.semantics.profile import (
    ActivatedEffect,
    oracle_loyalty_deltas,
    planeswalker_activations,
    profile_from_ccm,
)
from mythgauntlet.semantics.tags import analyze
from mythgauntlet.sim.game import _apply_activation
from mythgauntlet.sim.tier2 import _Permanent, _Player, loyalty_ready

ORACLE = (
    "+1: You gain 2 life.\n"
    "−2: Draw two cards.\n"
    "−7: Create three 2/2 Knight tokens."
)


def _pw_doc(*costs):
    effects = [
        [{"op": "gain_life", "amount": 2}],
        [{"op": "draw", "count": 2}],
        [{"op": "create_token", "count": 3, "power": 2, "toughness": 2}],
    ]
    return {"name": "PW", "types": ["planeswalker"], "abilities": [
        {"kind": "activated", "cost": c, "effects": e} for c, e in zip(costs, effects)]}


def test_oracle_deltas_read_signs_zero_and_x():
    assert oracle_loyalty_deltas("+1: a\n−2: b\n0: c\n−X: d") == [1, -2, 0, None]
    assert oracle_loyalty_deltas("Flying\nWhenever you draw, gain 1 life.") == []


def test_every_spelling_of_the_cost_pairs_to_the_oracle_delta():
    for costs in (
        ({"mana": "+1"}, {"mana": "{2}"}, {"mana": "{7}"}),
        ({"other": "+1 loyalty"}, {"other": "−2 loyalty"}, {"other": "-7"}),
        ({"mana": "{2}", "other": "-2"}, {"mana": "{2}", "other": "-2"}, {"other": "−7"}),
        ({}, {}, {}),
    ):
        acts = _pw_doc(*costs)["abilities"]
        got = planeswalker_activations(acts, ORACLE)
        if costs[0] == {"mana": "{2}", "other": "-2"}:
            # +1 spelled as -2 disagrees with the oracle text -> that one is dropped
            assert got[id(acts[0])] is None
            continue
        assert [got[id(a)].loyalty_delta for a in acts] == [1, -2, -7], costs
        assert all(got[id(a)].cost_mana == 0 and not got[id(a)].needs_tap for a in acts)


def test_a_contradicting_cost_number_or_sign_drops_the_ability():
    acts = _pw_doc({"mana": "{3}"}, {"mana": "{2}"}, {"mana": "+7"})["abilities"]
    got = planeswalker_activations(acts, ORACLE)
    assert got[id(acts[0])] is None      # 3 != 1
    assert got[id(acts[1])].loyalty_delta == -2
    assert got[id(acts[2])] is None      # "+7" but oracle says -7


def test_real_coloured_mana_or_other_cost_text_is_not_a_loyalty_cost():
    acts = _pw_doc({"mana": "{1}{U}"}, {"other": "discard a card"}, {"tap": True})["abilities"]
    assert not any(planeswalker_activations(acts, ORACLE).values())


def test_count_mismatch_drops_everything_rather_than_guessing_the_pairing():
    acts = _pw_doc({"mana": "+1"}, {"mana": "{2}"}, {"mana": "{7}"})["abilities"]
    assert not any(planeswalker_activations(acts[:2], ORACLE).values())


def test_a_plus_ability_the_engine_cannot_run_still_raises_loyalty():
    doc = {"abilities": [{"kind": "activated", "cost": {"mana": "+1"},
                          "effects": [{"op": "look_at_top_card"}]}]}
    (eff,) = [v for v in planeswalker_activations(doc["abilities"], "+1: Look.").values()]
    assert eff is not None and eff.loyalty_delta == 1 and eff.draw == 0
    # ...but an unrunnable MINUS is dropped: spending loyalty for nothing is worse than idle
    doc2 = {"abilities": [{"kind": "activated", "cost": {"mana": "{2}"},
                           "effects": [{"op": "look_at_top_card"}]}]}
    assert not any(planeswalker_activations(doc2["abilities"], "−2: Look.").values())


def test_profile_never_prices_a_loyalty_ability_in_mana(make_card):
    card = make_card("PW", mana_cost="{3}{W}{W}", type_line="Legendary Planeswalker - Test",
                     oracle_text=ORACLE)
    doc = _pw_doc({"mana": "+1"}, {"mana": "{2}"}, {"mana": "{7}"})
    acts = profile_from_ccm(doc, card, analyze(card)).activated
    assert [a.loyalty_delta for a in acts] == [1, -2, -7]
    assert all(a.cost_mana == 0 for a in acts)


def _walker(loyalty):
    return _Permanent(name="PW", power=0, toughness=0, is_creature=False, sick=False,
                      loyalty=loyalty)


def test_one_loyalty_ability_per_turn_and_the_loyalty_must_cover_the_cost():
    perm = _walker(4)
    minus2 = ActivatedEffect(cost_mana=0, needs_tap=False, draw=2, loyalty_delta=-2)
    minus7 = ActivatedEffect(cost_mana=0, needs_tap=False, tokens=(3, 2, 2), loyalty_delta=-7)
    plus1 = ActivatedEffect(cost_mana=0, needs_tap=False, loyalty_delta=1)
    assert loyalty_ready(perm, minus2) and plus1 is not None and loyalty_ready(perm, plus1)
    assert not loyalty_ready(perm, minus7)  # 4 loyalty cannot pay -7
    perm.loyalty_used = True
    assert not loyalty_ready(perm, minus2)  # already activated this turn
    assert loyalty_ready(perm, ActivatedEffect(cost_mana=0, needs_tap=False, draw=1))


def test_activation_pays_loyalty_and_the_walker_dies_at_zero():
    perm = _walker(2)
    me = _Player(name="P", library=[object()] * 5)
    opp = _Player(name="O", library=[])
    me.battlefield = [perm]
    eff = ActivatedEffect(cost_mana=0, needs_tap=False, draw=2, loyalty_delta=-2)
    _apply_activation(me, opp, perm, eff)
    assert len(me.library) == 3          # drew two
    assert perm.loyalty == 0 and perm.loyalty_used
    assert perm not in me.battlefield    # 0 loyalty: state-based action


def test_a_plus_keeps_the_walker_alive():
    perm = _walker(3)
    me = _Player(name="P", library=[])
    me.battlefield = [perm]
    _apply_activation(me, _Player(name="O", library=[]), perm,
                      ActivatedEffect(cost_mana=0, needs_tap=False, loyalty_delta=1))
    assert perm.loyalty == 4 and perm in me.battlefield
