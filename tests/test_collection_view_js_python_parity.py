"""frontend/src/utils/collectionView.js says its sort keys and group-bys "mirror the backend".
A key in the dropdown that the server does not know silently falls back to sorting by name, so the
control would look broken; a server key with no control is unreachable. This runs the real JS under
Node and compares both lists with collection_index. Skipped when Node is not installed."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import collection_index as ci

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "frontend" / "src" / "utils" / "collectionView.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None or not JS.exists(), reason="node or the JS source is unavailable")


def _exports():
    script = ("import * as v from " + json.dumps(JS.as_uri()) + ";\n"
              "console.log(JSON.stringify({sorts: v.SORT_KEYS.map(([k, label]) => [k, label]),"
              " groups: v.GROUP_BYS, defaults: v.DEFAULT_VIEW}));\n")
    out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_sort_dropdown_and_the_server_know_the_same_keys():
    js = {k for k, _ in _exports()["sorts"]}
    assert js == set(ci._SORTS), (
        f"only in the UI: {sorted(js - set(ci._SORTS))}; only on the server: {sorted(set(ci._SORTS) - js)}")


def test_every_sort_key_has_a_human_label_and_no_duplicates():
    sorts = _exports()["sorts"]
    keys = [k for k, _ in sorts]
    assert len(keys) == len(set(keys))
    assert all(label.strip() and label != key for key, label in sorts)


def test_group_bys_match_exactly_and_in_order():
    assert _exports()["groups"] == list(ci.GROUP_BYS)


def test_the_default_view_only_uses_values_the_server_accepts():
    d = _exports()["defaults"]
    assert d["sort"] in ci._SORTS
    assert d["groupBy"] in ci.GROUP_BYS or d["groupBy"] == "none"
    assert d["direction"] in ("asc", "desc") and d["thenDirection"] in ("asc", "desc")
    assert d["then"] is None or d["then"] in ci._SORTS


def test_every_server_sort_actually_runs_on_a_mixed_row_set():
    """A key that exists in _SORTS but crashes on rows with missing fields would 500 the list."""
    rows = [{"name": "A"}, {"name": "b", "price": 2.5, "cmc": 3, "rarity": "rare", "set": "C21", "count": 2},
            {"name": "C", "edhrec_rank": 10, "finish": "foil", "released_at": "2020-01-01", "date_added": "2021-01-01"}]
    for key in ci._SORTS:
        for direction in ("asc", "desc"):
            out = ci.sort_rows(rows, key, direction)
            assert len(out) == 3, (key, direction)
