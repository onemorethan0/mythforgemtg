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


def test_default_resolver_assumes_a_real_condition_holds():
    ability = {"effects": [{"op": "draw", "count": 1, "condition": "if you control a Dragon"}]}
    assert interpret_ability(ability)  # DefaultResolver's optimistic-by-design bias


def test_default_resolver_does_not_fire_the_otherwise_branch():
    """Found live 2026-08-25: Approach of the Second Sun compiles to two effects in one
    ability -- win_game conditioned on "if [cast twice from hand]", and gain_life
    conditioned on "otherwise". DefaultResolver assumes the IF branch holds (the existing
    convention), so consistency requires the paired OTHERWISE branch NOT fire too --
    crediting both is two contradictory outcomes at once, not an optimistic assumption.
    Same fix needed in sim/tier2.py's _EngineResolver, which shares this exact bug.

    UPDATED 2026-09-09: this used to assert the win_game DID survive, on the "assume the
    IF branch holds" convention. That was only ever harmless because `win_game` has no
    dispatch branch in `_apply_resolved` -- the resolved effect was produced and then
    silently dropped. Measuring the op to decide whether to implement it showed why it
    must not be: **all 34 stored win_game effects carry a condition**, every one of them
    board state the engine cannot evaluate, so implementing the op under that convention
    would have made all 34 cards win outright on resolution. `win_game` and `extra_turn`
    are now refused a condition they cannot verify (interpreter._GAME_DECIDING_OPS), so
    NEITHER branch of Approach of the Second Sun fires. The original point of this test --
    the paired `otherwise` must never fire alongside its if-branch -- is unchanged and
    still asserted below.
    """
    ability = {"effects": [
        {"op": "win_game", "condition": "if you've cast another spell named this"},
        {"op": "gain_life", "amount": 7, "condition": "otherwise"},
    ]}
    resolved = interpret_ability(ability)
    assert "gain_life" not in [r.op for r in resolved]  # the original guard
    assert resolved == []  # and the win is no longer assumed either


def test_an_unconditional_life_gain_beside_a_refused_win_still_resolves():
    """The refusal is per-EFFECT, not per-ability -- a card that wins under a condition
    and does something else unconditionally keeps the unconditional half."""
    ability = {"effects": [
        {"op": "win_game", "condition": "if you have 200 or more cards in your library"},
        {"op": "gain_life", "amount": 7},
    ]}
    assert [r.op for r in interpret_ability(ability)] == ["gain_life"]


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
