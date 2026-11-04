"""A blink is not removal: the interpreter drops the exile + return pair.

The compiler has no blink op, so "exile target creature, then return it" is stored as `exile`
plus a return op. `profile._is_flicker` already kept such an ability out of the removal COUNT, but
`interpret_ability` -- which every execution path goes through -- still produced the exile, so the
sim exiled an opponent's best creature for good (64 stored flicker abilities: Astral Slide,
Eldrazi Displacer, Angel of Condemnation ...). Found with scripts/blink_scan.py.
"""
from __future__ import annotations

from mythgauntlet.semantics import interpreter
from mythgauntlet.semantics.interpreter import interpret_ability, is_flicker
from mythgauntlet.semantics import profile


def _ops(ability):
    return [e.op for e in interpret_ability(ability)]


ASTRAL_SLIDE_LIKE = {
    "kind": "triggered",
    "effects": [
        {"op": "exile", "target": {"type": "creature", "count": 1, "controller": "any"}},
        {"op": "return_to_hand", "target": {"type": "creature", "count": 1,
                                            "condition": "at the beginning of the next end step"}},
    ],
}
PARTING_GUST_LIKE = {
    "kind": "spell_effect",
    "effects": [
        {"op": "exile", "target": {"type": "creature", "count": 1, "controller": "any"}},
        {"op": "return_to_hand", "target": {"type": "creature", "count": 1,
                                            "condition": "if the gift wasn't promised"}},
    ],
}
OBLIVION_RING_LIKE = {
    "kind": "triggered",
    "effects": [
        {"op": "exile", "target": {"type": "permanent", "count": 1, "zone": "battlefield"}},
        {"op": "return_to_hand", "target": {"type": "permanent", "count": 1, "zone": "exile"}},
    ],
}
SWORDS_LIKE = {
    "kind": "spell_effect",
    "effects": [{"op": "exile", "target": {"type": "creature", "count": 1, "controller": "opponent"}},
                {"op": "gain_life", "who": "opponent", "amount": 3}],
}


def test_a_blink_produces_neither_the_exile_nor_the_return():
    assert is_flicker(ASTRAL_SLIDE_LIKE)
    assert _ops(ASTRAL_SLIDE_LIKE) == []


def test_other_effects_in_a_blink_ability_still_run():
    ability = {"kind": "spell_effect", "effects": [
        ASTRAL_SLIDE_LIKE["effects"][0], ASTRAL_SLIDE_LIKE["effects"][1],
        {"op": "draw", "count": 1}]}
    assert _ops(ability) == ["draw"]


def test_a_conditional_return_is_still_an_answer():
    # Parting Gust: the exile is permanent on the other branch, so it must still execute
    assert not is_flicker(PARTING_GUST_LIKE)
    assert "exile" in _ops(PARTING_GUST_LIKE)


def test_oblivion_ring_style_exile_still_executes():
    assert not is_flicker(OBLIVION_RING_LIKE)
    assert "exile" in _ops(OBLIVION_RING_LIKE)


def test_plain_removal_is_untouched():
    assert not is_flicker(SWORDS_LIKE)
    assert _ops(SWORDS_LIKE) == ["exile", "gain_life"]


def test_a_return_with_no_exile_is_not_a_blink():
    bounce = {"kind": "spell_effect", "effects": [
        {"op": "return_to_hand", "target": {"type": "creature", "controller": "opponent"}}]}
    assert not is_flicker(bounce)
    assert _ops(bounce) == ["return_to_hand"]


def test_profile_and_interpreter_share_one_definition():
    # two copies of this rule would drift (tags.py / profile.py already did once)
    assert profile._is_flicker is interpreter.is_flicker
    assert profile._RETURN_OPS is interpreter._RETURN_OPS or profile._RETURN_OPS == interpreter._RETURN_OPS
