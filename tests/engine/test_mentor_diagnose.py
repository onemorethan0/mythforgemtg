"""mentor.diagnose (PLAN_MENTOR_ADHOC D1): the pure driver/lever table. Offline and sim-free.
The table was drafted by muse-glimmer from docs/specs/mentor_adhoc/D1.md; these tests pin the gold
set the spec names and the table's internal consistency (every lever points at a real driver of
every axis it lists, every driver reads a fact the tool wrapper actually supplies)."""

from __future__ import annotations

import pytest

from mythgauntlet.mentor import diagnose as dg
from mythgauntlet.ratings import reference

KILL = dg.Driver("avg_kill_turn", "avg_kill_turn", "lower_is_better", 6.0, 9.0)
KILL_REF = dg.Driver("avg_kill_turn", "avg_kill_turn", "lower_is_better", 6.0, 9.0,
                     ref_metric="avg_kill_turn")


# -- reading: the spec's gold set ---------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (5.5, ("strong", "fixed_threshold")),
    (6.0, ("strong", "fixed_threshold")),     # <= strong_at
    (7.0, ("typical", "fixed_threshold")),
    (9.0, ("weak", "fixed_threshold")),       # >= weak_at
])
def test_fixed_threshold_lower_is_better(value, expected):
    assert dg.reading(KILL, value, None) == expected


@pytest.mark.parametrize("value,expected", [
    (0.9, "strong"), (0.95, "strong"), (0.7, "typical"), (0.5, "typical"), (0.49, "weak"),
])
def test_fixed_threshold_higher_is_better(value, expected):
    d = dg.Driver("r", "r", "higher_is_better", 0.9, 0.5)
    assert dg.reading(d, value, None)[0] == expected


def test_bracket_percentile_lower_is_better_is_mirrored():
    cell = reference.BRACKET_AXIS_REFERENCE[3]["avg_kill_turn"]
    assert dg.reading(KILL_REF, cell["p25"] - 0.5, 3) == ("strong", "bracket_percentile")
    assert dg.reading(KILL_REF, cell["p75"] + 0.5, 3) == ("weak", "bracket_percentile")
    mid = (cell["p25"] + cell["p75"]) / 2
    assert dg.reading(KILL_REF, mid, 3) == ("typical", "bracket_percentile")


def test_bracket_percentile_higher_is_better_and_scale():
    cell = reference.BRACKET_AXIS_REFERENCE[3]["speed"]
    d = dg.Driver("g", "g", "higher_is_better", 0.9, 0.5, ref_metric="speed", ref_scale=100.0)
    assert dg.reading(d, (cell["p75"] + 1) / 100, 3) == ("strong", "bracket_percentile")
    assert dg.reading(d, (cell["p25"] - 1) / 100, 3) == ("weak", "bracket_percentile")


def test_reference_metric_without_a_bracket_falls_back_to_the_fixed_thresholds():
    assert dg.reading(KILL_REF, 5.5, None) == ("strong", "fixed_threshold")


def test_a_thin_or_missing_reference_cell_falls_back(monkeypatch):
    monkeypatch.setattr(reference, "BRACKET_AXIS_REFERENCE", {3: {}})
    assert dg.reading(KILL_REF, 5.5, 3) == ("strong", "fixed_threshold")


def test_none_value_uses_the_drivers_none_reading():
    assert dg.reading(KILL, None, 3) == ("unknown", "none")
    weak_none = dg.Driver("k", "k", "lower_is_better", 6.0, 9.0, none_reading="weak")
    assert dg.reading(weak_none, None, 3) == ("weak", "none")


def test_list_and_bool_kinds():
    lst = dg.Driver("x", "x", "higher_is_better", None, None, kind="empty_list")
    assert dg.reading(lst, [], 3) == ("strong", "fixed_threshold")
    assert dg.reading(lst, ["land"], 3) == ("weak", "fixed_threshold")
    flag = dg.Driver("b", "b", "higher_is_better", None, None, kind="bool")
    assert dg.reading(flag, True, 3)[0] == "strong"
    assert dg.reading(flag, 5, 3)[0] == "strong"       # an integer go-off turn is present
    assert dg.reading(flag, False, 3)[0] == "typical"


# -- the table ---------------------------------------------------------------------------

def test_every_axis_is_present_and_speed_and_clock_share_drivers():
    assert set(dg.DRIVER_TABLE) == {"speed", "clock", "consistency", "resilience",
                                    "interaction", "ceiling"}
    assert dg.DRIVER_TABLE["speed"] is dg.DRIVER_TABLE["clock"]


def test_the_two_clock_drivers_that_may_be_absent_read_weak_not_unknown():
    """A deck that never kills / never casts its commander inside the horizon is a measured
    weakness, not a missing fact (the draft first left avg_commander_turn at 'unknown')."""
    by = {d.name: d for d in dg.DRIVER_TABLE["speed"]}
    assert by["avg_kill_turn"].none_reading == "weak"
    assert by["avg_commander_turn"].none_reading == "weak"
    assert {d.name: d for d in dg.DRIVER_TABLE["ceiling"]}["fast_kill_turn"].none_reading == "weak"


def test_every_lever_names_a_driver_of_each_axis_it_lists():
    for lever in dg.LEVERS:
        for axis in lever.axes:
            assert lever.driver in {d.name for d in dg.DRIVER_TABLE[axis]}, (axis, lever.driver)


def test_levers_are_fixed_plain_sentences_naming_no_cards_or_numbers():
    import re
    seen = set()
    for lever in dg.LEVERS:
        assert lever.text.endswith(".") and lever.text not in seen
        seen.add(lever.text)
        assert not re.search(r"\d", lever.text), lever.text


def test_requires_keys_are_the_applicability_facts():
    assert {lv.requires for lv in dg.LEVERS if lv.requires} == {
        "counterspell_applicable", "wipe_applicable"}


# -- diagnose ----------------------------------------------------------------------------

def test_diagnose_speed_reports_weak_drivers_and_their_levers_in_table_order():
    out = dg.diagnose("speed", 40.0, "w", {"avg_commander_turn": 7.0, "ramp_cards": 4}, None)
    assert out["axis"] == "speed" and out["score"] == 40.0 and out["why"] == "w"
    by = {d["name"]: d for d in out["drivers"]}
    assert by["avg_commander_turn"]["reading"] == "weak" and by["ramp_cards"]["reading"] == "weak"
    assert [d["name"] for d in out["drivers"]] == [d.name for d in dg.DRIVER_TABLE["speed"]]
    assert out["levers"][0].startswith("Cheaper ramp")
    assert out["levers"][1].startswith("More mana ramp")


def test_diagnose_clock_has_its_own_lever_speed_does_not():
    facts = {"avg_kill_turn": 10.5}
    clock = dg.diagnose("clock", 12.0, "w", facts, None)
    speed = dg.diagnose("speed", 12.0, "w", facts, None)
    assert any(t.startswith("The kill comes late") for t in clock["levers"])
    assert not any(t.startswith("The kill comes late") for t in speed["levers"])


def test_a_lever_requiring_an_inapplicable_role_is_suppressed():
    facts = {"counterspells": 0, "counterspell_applicable": False,
             "board_wipes": 0, "wipe_applicable": False, "spot_removal": 5}
    out = dg.diagnose("interaction", 20.0, "w", facts, None)
    by = {d["name"]: d for d in out["drivers"]}
    assert by["counterspells"]["reading"] == "weak"       # the table still reads it ...
    assert not any("counterspell" in t.lower() or "sweeper" in t.lower() for t in out["levers"])
    facts["counterspell_applicable"] = True
    out = dg.diagnose("interaction", 20.0, "w", facts, None)
    assert any("counterspell" in t.lower() for t in out["levers"])


def test_strong_drivers_trigger_no_levers():
    facts = {"keep_rate": 0.85, "avg_mulligans": 0.2, "curve_efficiency": 0.7,
             "commander_cast_rate": 1.0, "manabase_consistency": 0.9, "land_count": 37}
    assert dg.diagnose("consistency", 90.0, "w", facts, None)["levers"] == []


def test_unknown_axis_raises():
    with pytest.raises(ValueError, match="unknown axis"):
        dg.diagnose("pod", 1.0, "w", {}, None)


def test_missing_facts_read_unknown_and_trigger_nothing_unless_declared_weak():
    out = dg.diagnose("resilience", 50.0, "w", {}, 3)
    assert {d["reading"] for d in out["drivers"]} == {"unknown"}
    assert out["levers"] == []
