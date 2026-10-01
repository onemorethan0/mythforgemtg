"""Tests for the per-bracket axis reference (plan E1)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from mythgauntlet.ratings import advisor, reference
from mythgauntlet.ratings.reference import LOWER_IS_BETTER, percentile_band

EXPECTED_METRICS = {*advisor.PROFILE_AXES, "pod", "avg_kill_turn", "avg_commander_turn"}


def _cell(p25, p50, p75, n=30, thin=False):
    return {"p25": p25, "p50": p50, "p75": p75, "n": n, "none_count": 0, "thin": thin}


TABLE = {
    3: {
        "consistency": _cell(60.0, 70.0, 80.0),
        "ceiling": _cell(10.0, 20.0, 30.0, n=5, thin=True),
        "avg_kill_turn": _cell(8.0, 9.0, 10.0),
    },
}


@pytest.mark.parametrize("value, band", [
    (59.9, "below_p25"),
    (60.0, "p25_p50"),
    (69.9, "p25_p50"),
    (70.0, "p50_p75"),
    (79.9, "p50_p75"),
    (80.0, "above_p75"),
    (100.0, "above_p75"),
])
def test_percentile_band_all_bands(value, band):
    got = percentile_band(3, "consistency", value, table=TABLE)
    assert got == {"bracket": 3, "p25": 60.0, "p50": 70.0, "p75": 80.0, "n": 30,
                   "percentile_band": band}


def test_percentile_band_declines_thin_missing_and_none():
    assert percentile_band(3, "ceiling", 25.0, table=TABLE) is None       # thin
    assert percentile_band(3, "speed", 50.0, table=TABLE) is None         # unknown metric
    assert percentile_band(4, "consistency", 50.0, table=TABLE) is None   # unknown bracket
    assert percentile_band(3, "consistency", None, table=TABLE) is None   # no value
    empty = {3: {"x": _cell(None, None, None, n=0, thin=True)}}
    assert percentile_band(3, "x", 1.0, table=empty) is None


def test_band_is_about_the_raw_value_for_lower_is_better_metrics():
    assert "avg_kill_turn" in LOWER_IS_BETTER
    # a FAST deck (turn 7) is below p25 - the raw value, not a judgement
    assert percentile_band(3, "avg_kill_turn", 7.0, table=TABLE)["percentile_band"] == "below_p25"


def test_baked_constant_covers_exactly_the_expected_metrics():
    table = reference.BRACKET_AXIS_REFERENCE
    assert set(table) == {1, 2, 3, 4, 5}
    for bracket, cells in table.items():
        assert set(cells) == EXPECTED_METRICS, bracket
        for metric, cell in cells.items():
            assert {"p25", "p50", "p75", "n", "none_count", "thin"} <= set(cell)
            assert cell["thin"] == (cell["n"] < 20)
            if cell["n"]:
                assert cell["p25"] <= cell["p50"] <= cell["p75"], (bracket, metric)
            else:
                assert cell["p50"] is None


def _load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "bracket_axis_reference.py"
    spec = importlib.util.spec_from_file_location("bracket_axis_reference", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_aggregate_sorts_and_excludes_none():
    script = _load_script()
    rows = [{"label": 2, "metrics": {"ceiling": v, "avg_kill_turn": k}}
            for v, k in [(40.0, None), (10.0, 9.0), (30.0, 7.0), (20.0, 8.0)]]
    table = script.aggregate(rows)
    ceiling = table[2]["ceiling"]
    assert (ceiling["p25"], ceiling["p50"], ceiling["p75"], ceiling["n"]) == (17.5, 25.0, 32.5, 4)
    kill = table[2]["avg_kill_turn"]
    assert kill["n"] == 3 and kill["none_count"] == 1 and kill["p50"] == 8.0
    assert kill["thin"] is True
    assert table[5]["ceiling"]["n"] == 0 and table[5]["ceiling"]["p50"] is None


def test_cache_roundtrip_is_resumable(tmp_path):
    script = _load_script()
    path = tmp_path / "rows.jsonl"
    script.append_cache(path, {"deck": "a.txt", "runs": 120, "label": 1, "metrics": {}})
    script.append_cache(path, {"deck": "a.txt", "runs": 50, "label": 1, "metrics": {}})
    with path.open("a", encoding="utf-8") as f:
        f.write("not json\n\n")
    assert set(script.load_cache(path)) == {("a.txt", 120), ("a.txt", 50)}
