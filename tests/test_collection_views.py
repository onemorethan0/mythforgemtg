"""New sort keys, secondary sort, server-side grouping and printing filters (T6-T8).

Unit tests run on hand-built enriched dicts (no stores, no network); the route tests write
a real collection.csv under tmp_path via MYTHSUITE_DIR, like test_collection_routes.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import collection_index as ci
import server

client = TestClient(server.app)


def row(name, **kw):
    base = {"name": name, "count": 1, "finish": "nonfoil", "lang": "en", "set": "", "cn": "",
            "colors": [], "color_identity": [], "type": "Creature", "cmc": 0,
            "is_land": False, "rarity": None, "released_at": None, "date_added": None,
            "treatments": [], "price": None, "set_name": None}
    base.update(kw)
    return base


def names(rows):
    return [r["name"] for r in rows]


# ---- Task 6 -------------------------------------------------------------------------

def test_collector_natural_order():
    rows = [row("d", set="C21", cn="★1"), row("c", set="C21", cn="10a"),
            row("b", set="C21", cn="10"), row("a", set="C21", cn="2")]
    assert names(ci.sort_rows(rows, "collector")) == ["a", "b", "c", "d"]
    assert names(ci.sort_rows(rows, "collector", "desc")) == ["d", "c", "b", "a"]


def test_collector_groups_by_set_first():
    rows = [row("x", set="MH2", cn="1"), row("y", set="C21", cn="99")]
    assert names(ci.sort_rows(rows, "collector")) == ["y", "x"]


def test_color_wubrg_order():
    spec = [("colorless", []), ("multi", ["W", "U"]), ("g", ["G"]), ("r", ["R"]),
            ("b", ["B"]), ("u", ["U"]), ("w", ["W"])]
    rows = [row(n, colors=c) for n, c in spec]
    assert names(ci.sort_rows(rows, "color")) == ["w", "u", "b", "r", "g", "multi", "colorless"]


def test_color_multicolor_tiebreak_is_wubrg_tuple():
    rows = [row("gr", colors=["G", "R"]), row("wu", colors=["W", "U"]), row("ub", colors=["U", "B"])]
    assert names(ci.sort_rows(rows, "color")) == ["wu", "ub", "gr"]


def test_rarity_unknown_last_both_directions():
    rows = [row("m", rarity="mythic"), row("none"), row("c", rarity="common"),
            row("r", rarity="rare")]
    assert names(ci.sort_rows(rows, "rarity")) == ["c", "r", "m", "none"]
    assert names(ci.sort_rows(rows, "rarity", "desc")) == ["m", "r", "c", "none"]


def test_released_added_nullable_last_both_directions():
    rows = [row("old", released_at="1999-01-01", date_added="2020-01-01"),
            row("new", released_at="2024-01-01", date_added="2024-05-05"),
            row("nil")]
    assert names(ci.sort_rows(rows, "released")) == ["old", "new", "nil"]
    assert names(ci.sort_rows(rows, "released", "desc")) == ["new", "old", "nil"]
    assert names(ci.sort_rows(rows, "added", "desc")) == ["new", "old", "nil"]


def test_finish_order():
    rows = [row("e", finish="etched"), row("f", finish="foil"), row("n")]
    assert names(ci.sort_rows(rows, "finish")) == ["n", "f", "e"]


def test_secondary_sort():
    rows = [row("a", type="Creature", cmc=1), row("b", type="Creature", cmc=5),
            row("c", type="Creature", cmc=3), row("d", type="Artifact", cmc=9)]
    out = ci.sort_rows(rows, "type", "asc", then="cmc", then_direction="desc")
    assert names(out) == ["d", "b", "c", "a"]   # Artifact < Creature; within it high cmc first


def test_secondary_nullable_last_in_both_directions():
    rows = [row("x", type="Creature", price=None), row("y", type="Creature", price=5.0),
            row("z", type="Creature", price=1.0)]
    assert names(ci.sort_rows(rows, "type", then="price")) == ["z", "y", "x"]
    assert names(ci.sort_rows(rows, "type", then="price", then_direction="desc")) == ["y", "z", "x"]


def test_primary_nullable_last_with_secondary():
    rows = [row("n1", rarity=None, cmc=1), row("c", rarity="common", cmc=2),
            row("n2", rarity=None, cmc=0)]
    out = ci.sort_rows(rows, "rarity", "desc", then="cmc")
    assert names(out) == ["c", "n2", "n1"]


def test_name_is_final_tiebreak():
    rows = [row("b", cmc=1), row("a", cmc=1), row("c", cmc=1)]
    assert names(ci.sort_rows(rows, "cmc", then="cmc")) == ["a", "b", "c"]


def test_unknown_then_key_ignored():
    rows = [row("b", cmc=2), row("a", cmc=2)]
    assert names(ci.sort_rows(rows, "cmc", then="bogus")) == ["a", "b"]
    assert names(ci.sort_rows(rows, "bogus", then="bogus")) == ["a", "b"]


# ---- route helpers ------------------------------------------------------------------

_HEADER = "Count,Name,Edition,Collector Number,Foil,Language,Condition,Scryfall ID\n"


@pytest.fixture
def csv_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path))
    return tmp_path / "collection.csv"


def _write(path, *lines):
    path.write_text(_HEADER + "".join(l + "\n" for l in lines), encoding="utf-8")


def _get(**params):
    params.setdefault("limit", 0)
    r = client.get("/api/collection", params=params)
    assert r.status_code == 200
    return r.json()


def test_route_secondary_sort_and_unknown_params(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "1,Arcane Signet,C21,297,,,,",
           "2,Sol Ring,C21,263,foil,,,")
    data = _get(sort="name", then="finish", then_direction="desc")
    assert [(c["name"], c["finish"]) for c in data["cards"]] == [
        ("Arcane Signet", "nonfoil"), ("Sol Ring", "foil"), ("Sol Ring", "nonfoil")]
    # junk values never error
    assert len(_get(then="bogus")["cards"]) == 3
