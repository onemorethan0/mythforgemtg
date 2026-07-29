"""CCM effect interpreter: faithful traversal + real-X / condition resolution. Offline."""

from __future__ import annotations

import json

from mythgauntlet.semantics import compiler, interpreter
from mythgauntlet.semantics.interpreter import ResolvedEffect, interpret_ability


class _FixedResolver:
    """Test resolver: a fixed X and a fixed condition verdict."""

    def __init__(self, x: int = 1, cond: bool = True):
        self.x, self._cond = x, cond
        self.seen_effects: list[dict | None] = []

    def amount(self, raw, op, param, effect=None):
        self.seen_effects.append(effect)
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        return self.x

    def condition_holds(self, condition, effect):
        return self._cond


def test_simple_effect_resolves():
    ability = {"kind": "triggered", "effects": [{"op": "draw", "count": 1, "who": "you"}]}
    assert interpret_ability(ability) == [ResolvedEffect("draw", {"count": 1, "who": "you"})]


def test_real_x_comes_from_the_resolver():
    ability = {"effects": [{"op": "create_token", "count": "X", "power": "X", "toughness": 1}]}
    # DefaultResolver reproduces the old flattening: X -> 1
    assert interpret_ability(ability)[0].params == {"count": 1, "power": 1, "toughness": 1}
    # a real resolver supplies the live value — the whole point of interpreting, not flattening
    assert interpret_ability(ability, _FixedResolver(x=5))[0].params == {
        "count": 5, "power": 5, "toughness": 1,
    }


def test_optional_condition_is_gated():
    ability = {"effects": [
        {"op": "draw", "count": 1, "optional": True, "condition": "unless that player pays {1}"}
    ]}
    assert interpret_ability(ability)                                   # default: it happens
    assert interpret_ability(ability, _FixedResolver(cond=False)) == []  # condition fails


def test_unknown_op_is_skipped_but_siblings_survive():
    ability = {"effects": [{"op": "time_travel", "amount": 3}, {"op": "draw", "count": 2}]}
    assert [r.op for r in interpret_ability(ability)] == ["draw"]


def test_signed_pump_keeps_negatives():
    ability = {"effects": [{"op": "pump", "power": "-X", "toughness": -1}]}
    assert interpret_ability(ability)[0].params == {"power": -1, "toughness": -1}


def test_non_numeric_params_pass_through():
    target = {"type": "creature", "controller": "opponent"}
    ability = {"effects": [{"op": "destroy", "target": target}]}
    assert interpret_ability(ability)[0].params == {"target": target}


def test_resolver_sees_the_full_effect_for_x_basis():
    """The resolver receives the effect dict, so it can consult x_basis (prompt v8+)."""
    effect = {"op": "deal_damage", "amount": "X", "x_basis": "mana_paid",
              "target": {"type": "any"}}
    resolver = _FixedResolver(x=3)
    interpret_ability({"effects": [effect]}, resolver)
    assert resolver.seen_effects == [effect]  # full effect, x_basis included


def test_all_committed_authored_ccms_interpret():
    """Every hand-authored (rung-3) CCM interprets without crashing — integration coverage."""
    files = list(compiler.authored_dir().glob("*.json"))
    assert files, "authored exemplars should be committed"
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        ability_lists = interpreter.interpret_ccm(doc.get("ccm", {}))
        assert isinstance(ability_lists, list)
        for effects in ability_lists:
            assert all(isinstance(e, ResolvedEffect) for e in effects)
