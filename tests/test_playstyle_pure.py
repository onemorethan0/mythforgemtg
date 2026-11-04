"""playstyle.py slot adjustments and theme resolution.

Drafted on a local model (qwen3:8b), then corrected: its "empty input" case ignored that
``lifegain`` force-adds its own theme, and its negative-slots check was vacuous.
"""
from __future__ import annotations

import playstyle


def test_every_playstyle_returns_all_default_slots_as_non_negative_ints():
    for key in playstyle.PLAYSTYLES:
        slots = playstyle.get_slot_adjustments(key)
        assert set(slots) >= set(playstyle.DEFAULT_SLOTS), key
        assert all(isinstance(v, int) and v >= 0 for v in slots.values()), key


def test_unknown_key_falls_back_to_auto():
    assert playstyle.get_slot_adjustments("nope") == playstyle.get_slot_adjustments("auto")


def test_returned_slots_are_a_copy():
    slots = playstyle.get_slot_adjustments("auto")
    slots["ramp"] = 999
    assert playstyle.DEFAULT_SLOTS["ramp"] != 999


def test_control_overrides_apply_on_top_of_defaults():
    ov = playstyle.PLAYSTYLES["control"]["role_adjustments"]
    slots = playstyle.get_slot_adjustments("control")
    for k, v in ov.items():
        assert slots[k] == v
    untouched = set(playstyle.DEFAULT_SLOTS) - set(ov)
    assert all(slots[k] == playstyle.DEFAULT_SLOTS[k] for k in untouched)


def test_auto_keeps_commander_themes_unchanged():
    assert playstyle.resolve_themes("auto", []) == []
    assert playstyle.resolve_themes("auto", ["tokens", "counters"]) == ["tokens", "counters"]


def test_forced_themes_come_first_and_are_not_duplicated():
    forced = playstyle.PLAYSTYLES["lifegain"]["themes"]
    out = playstyle.resolve_themes("lifegain", [forced[0], "tokens"])
    assert out[: len(forced)] == forced
    assert out.count(forced[0]) == 1
    assert out[-1] == "tokens"


def test_forced_themes_alone_when_commander_has_none():
    assert playstyle.resolve_themes("voltron", []) == playstyle.PLAYSTYLES["voltron"]["themes"]


def test_tribal_keeps_only_tribal_themes_when_any_exist():
    assert playstyle.resolve_themes("tribal", ["tribal_elf", "tokens", "tribal_human"]) == [
        "tribal_elf", "tribal_human"]


def test_tribal_with_no_tribal_theme_keeps_what_it_was_given():
    assert playstyle.resolve_themes("tribal", ["tokens"]) == ["tokens"]
