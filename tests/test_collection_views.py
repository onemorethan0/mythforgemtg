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


# ---- Task 7: grouping ---------------------------------------------------------------

def test_cmc_groups_put_lands_last():
    rows = [row("land", type="Land", is_land=True, cmc=0), row("zero", cmc=0),
            row("big", cmc=9), row("six", cmc=6), row("two", cmc=2)]
    ordered, groups = ci.group_rows(ci.sort_rows(rows, "name"), "cmc")
    assert [g["label"] for g in groups] == ["0", "2", "6", "7+", "Lands"]
    assert [r["group"] for r in ordered][-1] == "lands"
    assert groups[-1]["rows"] == 1


def test_card_group_counts_printings():
    rows = [row("Sol Ring", set="C21", count=2), row("Sol Ring", set="C21", finish="foil", count=1),
            row("Sol Ring", set="CMR", count=4), row("Arcane Signet", set="C21", count=1)]
    ordered, groups = ci.group_rows(rows, "card")
    sol = next(g for g in groups if g["label"] == "Sol Ring")
    assert sol["printings"] == 3 and sol["cards"] == 7 and sol["rows"] == 3
    assert len(groups) == 2
    assert [g["label"] for g in groups] == ["Sol Ring", "Arcane Signet"]   # first appearance
    assert [r["name"] for r in ordered][:3] == ["Sol Ring"] * 3


def test_card_group_merges_faces_by_front_name():
    rows = [row("Fire // Ice", set="A"), row("Fire", set="B")]
    _, groups = ci.group_rows(rows, "card")
    assert len(groups) == 1 and groups[0]["printings"] == 2


def test_value_subtotal_ignores_unpriced():
    rows = [row("a", price=2.0, count=3), row("b", price=None, count=5), row("c", price=1.5, count=2)]
    _, groups = ci.group_rows(rows, "type")
    assert groups[0]["value"] == 9.0 and groups[0]["cards"] == 10


def test_type_color_rarity_finish_orders():
    rows = [row("l", type="Land"), row("o", type="Other"), row("c", type="Creature"),
            row("i", type="Instant"), row("pw", type="Planeswalker")]
    _, g = ci.group_rows(rows, "type")
    assert [x["key"] for x in g] == ["Creature", "Planeswalker", "Instant", "Land", "Other"]
    rows = [row("m", colors=["W", "U"]), row("c"), row("g", colors=["G"]), row("w", colors=["W"])]
    _, g = ci.group_rows(rows, "color")
    assert [x["key"] for x in g] == ["W", "G", "Multicolor", "Colorless"]
    rows = [row("x", rarity="mythic"), row("y"), row("z", rarity="common")]
    _, g = ci.group_rows(rows, "rarity")
    assert [x["label"] for x in g] == ["common", "mythic", "Unknown"]
    rows = [row("e", finish="etched"), row("n")]
    _, g = ci.group_rows(rows, "finish")
    assert [x["key"] for x in g] == ["nonfoil", "etched"]


def test_set_groups_newest_first_unknown_last():
    rows = [row("a", set="OLD", set_name="Old Set", released_at="1999-01-01"),
            row("b", set=""), row("c", set="NEW", set_name="New Set", released_at="2024-01-01"),
            row("d", set="NODATE", set_name="No Date")]
    _, g = ci.group_rows(rows, "set")
    assert [x["label"] for x in g] == ["New Set (NEW)", "Old Set (OLD)", "No Date (NODATE)", "—"]


def test_group_none_and_unknown_by_are_noops():
    rows = [row("a"), row("b")]
    for by in ("none", "bogus", ""):
        ordered, groups = ci.group_rows(rows, by)
        assert groups == [] and names(ordered) == ["a", "b"]
        assert "group" not in ordered[0]


def test_group_rows_keeps_sort_within_group_and_does_not_mutate():
    rows = [row("b", type="Creature"), row("a", type="Instant"), row("c", type="Creature")]
    ordered, _ = ci.group_rows(rows, "type")
    assert names(ordered) == ["b", "c", "a"]
    assert "group" not in rows[0]


def test_groups_total_over_whole_filter_not_page(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "1,Arcane Signet,C21,297,,,,",
           "1,Command Tower,C21,300,,,,", "1,Mind Stone,C21,1,,,,", "1,Island,C21,2,,,,")
    full = _get(group="type")
    page = _get(group="type", limit=2)
    assert len(page["cards"]) == 2
    assert page["matched"] == 5
    assert sum(g["rows"] for g in page["groups"]) == page["matched"]
    assert page["groups"] == full["groups"]
    # "Show all" at the 5000 cap path reports the same whole-set totals
    assert sum(g["rows"] for g in _get(group="type", limit=0)["groups"]) == 5


def test_route_rows_ordered_by_group_then_sort(csv_path):
    _write(csv_path, "1,Zebra Land,C21,1,,,,", "1,Alpha Thing,C21,2,,,,", "1,Mid Thing,C21,3,,,,")
    # offline test: nothing resolves, so every row is type "Other"/unresolved; ordering by
    # name inside the single group must still hold
    cards = _get(group="type")["cards"]
    assert [c["name"] for c in cards] == ["Alpha Thing", "Mid Thing", "Zebra Land"]
    assert {c["group"] for c in cards} == {"Other"}


def test_group_none_is_backward_compatible(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "2,Arcane Signet,C21,297,,,,")
    base = _get()
    assert base["groups"] == []
    assert all("group" not in c for c in base["cards"])
    assert _get(group="none") == base
    assert _get(group="bogus") == base


# ---- Task 8: printing filters and facets --------------------------------------------

def test_filter_foil_only():
    rows = [row("a"), row("b", finish="foil"), row("c", finish="etched")]
    assert names(ci.filter_rows(rows, finishes=["foil"])) == ["b"]
    assert names(ci.filter_rows(rows, finishes=["foil", "etched"])) == ["b", "c"]
    assert names(ci.filter_rows(rows, finishes=[])) == ["a", "b", "c"]


def test_filter_treatment_any_of():
    rows = [row("a", treatments=["borderless"]), row("b", treatments=["showcase", "promo"]),
            row("c"), row("d", treatments=["retro"])]
    assert names(ci.filter_rows(rows, treatments=["promo", "borderless"])) == ["a", "b"]


def test_filter_languages():
    rows = [row("a"), row("b", lang="ja"), row("c", lang="")]
    assert names(ci.filter_rows(rows, languages=["JA"])) == ["b"]
    assert names(ci.filter_rows(rows, languages=["en"])) == ["a", "c"]


def test_multi_printing_uses_whole_collection():
    rows = [row("Sol Ring", set="C21"), row("Sol Ring", set="CMR", finish="foil"),
            row("Arcane Signet", set="C21"), row("Fire // Ice", set="A"), row("Fire", set="B")]
    # a set filter hides the second Sol Ring printing; the card is still multi-printing
    out = ci.filter_rows(rows, sets=["C21"], multi_printing=True)
    assert names(out) == ["Sol Ring"]
    both = ci.filter_rows(rows, multi_printing=True)
    assert names(both) == ["Sol Ring", "Sol Ring", "Fire // Ice", "Fire"]


def test_facets_list_only_present_finishes():
    rows = [row("a"), row("b", finish="foil", treatments=["promo"]),
            row("c", lang="ja", treatments=["promo", "retro"])]
    f = ci.facets(rows)
    assert f["finishes"] == [{"key": "nonfoil", "count": 2}, {"key": "foil", "count": 1}]
    assert f["treatments"] == [{"key": "retro", "count": 1}, {"key": "promo", "count": 2}]
    assert f["languages"] == [{"key": "en", "count": 2}, {"key": "ja", "count": 1}]
    assert "etched" not in {e["key"] for e in f["finishes"]}
    assert ci.facets([row("x")])["treatments"] == []


def test_route_printing_filters(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "2,Sol Ring,C21,263,foil,,,",
           "1,Arcane Signet,C21,297,,ja,,", "1,Mind Stone,C21,1,etched,,,")
    assert [c["name"] for c in _get(finishes="foil,etched")["cards"]] == ["Mind Stone", "Sol Ring"]
    assert [c["name"] for c in _get(finishes="foil")["cards"]] == ["Sol Ring"]
    multi = _get(multi_printing="true", sets="C21")
    assert {c["name"] for c in multi["cards"]} == {"Sol Ring"} and multi["matched"] == 2
    facets = _get()["facets"]
    assert {e["key"] for e in facets["finishes"]} == {"nonfoil", "foil", "etched"}
    assert _get(treatments="promo")["matched"] == 0
    assert _get(languages="zz")["cards"] == []
