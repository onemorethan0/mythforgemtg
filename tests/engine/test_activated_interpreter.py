"""Activated abilities the flattening cannot express now run through the interpreter.

`semantics/profile._activated_from` predates the interpreter: it squeezes an activated
ability into six fixed numbers over a FOUR-op vocabulary (draw / deal_damage /
create_token / gain_life), while `sim/tier2._apply_resolved` executes THIRTEEN ops per
effect. Two parallel effect paths, different vocabularies — and the older one was
discarding abilities the newer one can already run.

`mythgauntlet sim-health` measured the split: of 9,108 stored activated abilities, 43.7%
are dropped by COST GATES (correct — they stop an unpayable cost becoming a free
repeatable outlet), 20.0% use ops neither path knows, and **23.9% (2,175) were dropped
for the vocabulary gap alone** — 1,104 `pump`, 570 `add_counter`, 188 `exile`, 147
`grant_ability`, 105 `destroy`, every one an op the interpreter already runs when the
same card prints it as a spell or a trigger.

Two things must hold and neither is obvious:
  * the rescue must not DOUBLE-APPLY anything (an ability on the interpreter path keeps
    all six numeric fields at zero), and
  * the greedy agent must actually choose these, or they are enumerated as legal actions
    and never taken — a feature that looks wired and does nothing.
"""

from __future__ import annotations

from mythgauntlet.semantics import profile
from mythgauntlet.semantics.profile import ActivatedEffect
from mythgauntlet.sim import health, tier2
from mythgauntlet.sim.game import _apply_activation
from mythgauntlet.sim.tier2 import _activation_value, _Permanent, _Player


def _ability(cost: dict, *effects: dict) -> dict:
    return {"kind": "activated", "cost": cost, "effects": list(effects)}


def _perm(power: int = 2, toughness: int = 2, **kw) -> _Permanent:
    return _Permanent(name="Src", power=power, toughness=toughness, is_creature=True, **kw)


def _player(*perms: _Permanent) -> _Player:
    p = _Player(name="P", library=[])
    p.battlefield = list(perms)
    return p


# --- the lock-step guard -----------------------------------------------------------

def test_the_restated_vocabulary_matches_the_real_dispatch():
    """profile cannot import tier2 (tier2 imports profile), so the op set is restated.

    A restated vocabulary is the silent-drift class this repo keeps re-learning. Pinned
    against the set read out of tier2's own AST: widening one without the other would
    either hand the engine abilities it cannot run, or keep discarding ones it can.
    """
    assert profile.INTERPRETER_EXECUTABLE_OPS == health.executed_ops()["resolved"]


# --- what gets rescued, and what stays dropped -------------------------------------

def test_a_vocabulary_gap_ability_is_rescued_onto_the_interpreter_path():
    eff = profile._activated_from(
        _ability({"mana": "{1}"}, {"op": "pump", "power": 2, "toughness": 0}),
        [{"op": "pump", "power": 2, "toughness": 0}],
    )
    assert eff is not None
    assert eff.ability is not None
    assert eff.cost_mana == 1
    # Every numeric field stays zero -- this is what makes double-application impossible.
    assert (eff.draw, eff.damage_face, eff.damage_any, eff.gain_life, eff.tokens) == (
        0, 0, 0, 0, None)


def test_an_ability_the_flattening_understands_is_unchanged():
    """The 1,068 already-kept abilities must not move onto the new path (golden master)."""
    effects = [{"op": "draw", "count": 2}]
    eff = profile._activated_from(_ability({"mana": "{2}"}, *effects), effects)
    assert eff is not None
    assert eff.ability is None
    assert eff.draw == 2


def test_cost_gates_still_drop_their_abilities():
    """43.7% of the loss is cost gates and every one of them is CORRECT.

    They exist because an ability whose cost the engine cannot pay becomes a free
    repeatable outlet -- the documented defect that made 1,488 abilities free once.
    The rescue must not reopen it.
    """
    effs = [{"op": "pump", "power": 5, "toughness": 5}]
    for cost in ({"sacrifice_self": True}, {"mana": "{1}", "other": "discard a card"},
                 {"mana": "{1}", "pay_life": 3}, {}):
        assert profile._activated_from(_ability(cost, *effs), effs) is None, cost


def test_an_op_no_path_can_run_is_still_dropped():
    """`attach` is in neither vocabulary -- rescuing it would promise nothing."""
    effs = [{"op": "attach", "target": {"type": "creature"}}]
    assert profile._activated_from(_ability({"mana": "{3}"}, *effs), effs) is None


# --- it actually fires -------------------------------------------------------------

def test_activating_a_rescued_ability_applies_its_effect_to_the_source():
    """"{1}: This creature gets +2/+0" -- the source permanent is the resolution scope."""
    perm = _perm(2, 2)
    me, opp = _player(perm), _player()
    effects = [{"op": "pump", "power": 2, "toughness": 0}]
    eff = profile._activated_from(_ability({"mana": "{1}"}, *effects), effects)
    _apply_activation(me, opp, perm, eff)
    assert perm.power == 4


def test_a_MIXED_ability_routes_ENTIRELY_through_the_interpreter():
    """179 abilities across 172 cards print a flattenable op AND one that isn't.

    Handling only the pure-gap case would leave those half-modelled — Alaundo the Seer
    keeping its draw and losing its counter. Routing the WHOLE ability is also what makes
    double-application impossible: the numeric fields stay zero and the interpreter runs
    every effect, including the ones the flattening could have expressed.
    """
    perm = _perm()
    me, opp = _player(perm), _player()
    me.library = [object()] * 5
    effects = [{"op": "add_counter", "count": 1, "counter_type": "+1/+1"},
               {"op": "draw", "count": 1}]
    eff = profile._activated_from(_ability({"mana": "{2}"}, *effects), effects)
    assert eff.ability is not None
    assert eff.draw == 0  # not ALSO counted into the numeric field
    before = len(me.library)
    _apply_activation(me, opp, perm, eff)
    assert len(me.library) == before - 1  # drew exactly once, via the interpreter
    assert perm.counters == 1             # and the counter is no longer lost


# --- the agent has to choose it ----------------------------------------------------

def test_a_rescued_ability_scores_above_zero_so_greedy_will_take_it():
    """Greedy's gate is `value > 0`; a zero score means enumerated-but-never-chosen."""
    eff = ActivatedEffect(cost_mana=1, needs_tap=False,
                          ability=_ability({}, {"op": "pump", "power": 2, "toughness": 2}))
    assert _activation_value(eff, _player()) > 0


def test_removal_is_worthless_against_an_empty_board():
    """_apply_resolved's destroy/exile declines with no opposing creature, so scoring it
    above zero would spend mana on a guaranteed no-op every single turn."""
    eff = ActivatedEffect(cost_mana=2, needs_tap=False,
                          ability=_ability({}, {"op": "destroy",
                                                "target": {"type": "creature"}}))
    assert _activation_value(eff, _player()) == 0.0
    assert _activation_value(eff, _player(_perm())) > 0


def test_every_interpreter_op_can_score_so_none_is_silently_unchoosable():
    """A missing entry means "enumerated as a legal action and never taken".

    `deal_damage` was missing from the value table on the first pass and a live duel
    caught it: a rescued damage ability scored 0.0, and greedy's `value > 0` gate meant
    it was offered every turn and chosen never. Any op the interpreter runs can appear on
    a rescued (mixed) ability, so every one needs a defined weight.
    """
    opp = _player()
    for op in profile.INTERPRETER_EXECUTABLE_OPS:
        eff = ActivatedEffect(cost_mana=1, needs_tap=False,
                              ability=_ability({}, {"op": op, "amount": 1, "count": 1}))
        value = _activation_value(eff, opp)
        if op in ("destroy", "exile"):
            continue  # correctly zero against an empty board; covered by its own test
        if op == "add_mana":
            assert value == 0.0, "mana made after the cast step is never spent"
            continue
        assert value > 0.0, f"{op} would be enumerated but never chosen"


def test_damage_activation_agrees_with_the_numeric_path():
    """Both paths weigh burn the same way, so a mixed ability isn't valued differently
    from the identical effect expressed numerically."""
    opp = _player()
    opp.life = 40
    eff = ActivatedEffect(cost_mana=1, needs_tap=False,
                          ability=_ability({}, {"op": "deal_damage", "amount": 3}))
    assert _activation_value(eff, opp) == 3 * 0.9
    opp.life = 2
    assert _activation_value(eff, opp) == 100.0  # lethal is decisive on both paths


def test_numeric_abilities_keep_their_original_scoring():
    """The rescue must not perturb how the 1,068 existing abilities are valued."""
    eff = ActivatedEffect(cost_mana=1, needs_tap=False, draw=2)
    assert _activation_value(eff, _player()) == 1.4 * 2
