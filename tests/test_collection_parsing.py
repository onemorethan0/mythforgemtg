"""collection.py: ownership keys, the legacy owned-name parser, finish/code detection, row identity,
the decorated-line grammar and the pasted-text row parser. These read the user's own data, where a
mis-parse silently loses or miscounts cards."""
from __future__ import annotations

import pytest

import collection as col


# -- owned_key / columns ---------------------------------------------------------------------------

def test_owned_key_is_front_face_and_casefolded():
    assert col.owned_key("Fire // Ice") == "fire"
    assert col.owned_key("  Sol Ring ") == "sol ring"
    assert col.owned_key("SOL RING") == col.owned_key("sol ring")
    assert col.owned_key("") == "" and col.owned_key(None) == ""


def test_find_column_is_case_and_space_insensitive_and_returns_the_real_header():
    assert col._find_column(["  Card Name ", "Qty"], ("card name", "name")) == "  Card Name "
    assert col._find_column(["Qty"], ("name",)) is None
    assert col._find_column([None, "Name"], ("name",)) == "Name"


# -- the owned-name parser (every build reads this via load_owned_names) -------------------------------

def test_owned_from_a_csv_uses_the_name_column():
    text = "Count,Name,Edition\n1,Sol Ring,C21\n2,Fire // Ice,\n,,\n"
    assert col.parse_owned(text) == {"sol ring", "fire"}


def test_owned_from_a_plain_decklist():
    text = "1 Sol Ring\n2 Island\nSwords to Plowshares\n# a comment\n// another\n\n"
    assert col.parse_owned(text) == {"sol ring", "island", "swords to plowshares"}


def test_owned_decklist_accepts_the_1x_quantity_form():
    """'1x Sol Ring' became the key '1x sol ring', so the card never matched a build."""
    assert col.parse_owned("1x Sol Ring\n4x Lightning Bolt") == {"sol ring", "lightning bolt"}


def test_owned_decklist_strips_set_tags_and_section_headers():
    text = "Commander: Atraxa, Praetors' Voice\n1 Lightning Bolt (M11) 149\n2 Island (C21) 280 *F*"
    assert col.parse_owned(text) == {"atraxa, praetors' voice", "lightning bolt", "island"}


def test_owned_decklist_keeps_a_card_name_that_contains_parentheses():
    assert col.parse_owned("1 Erase (Not the Urza's Legacy One)") == {"erase (not the urza's legacy one)"}


def test_owned_empty_and_csv_without_a_name_column():
    assert col.parse_owned("") == set()
    assert col._from_csv("Qty,Edition\n1,C21\n") == set()       # no name column -> nothing invented


# -- finish and set codes ---------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("foil", "foil"), ("FOIL", "foil"), ("f", "foil"), ("yes", "foil"), ("true", "foil"),
    ("etched", "etched"), ("Foil Etched", "etched"), ("e", "etched"),
    ("", "nonfoil"), ("nonfoil", "nonfoil"), ("no", "nonfoil"), (None, "nonfoil"), ("???", "nonfoil"),
])
def test_normalize_finish(raw, expected):
    assert col.normalize_finish(raw) == expected


@pytest.mark.parametrize("value,is_code", [
    ("znr", True), ("C21", True), ("40K", True), ("MH2", True), ("M11", True),
    ("Mirage", False), ("Alpha", False), ("Zendikar Rising", False), ("", False), (None, False),
    ("x", False), ("toolongcode", False),
])
def test_looks_like_code(value, is_code):
    assert col._looks_like_code(value) is is_code


# -- row identity -----------------------------------------------------------------------------------------------

BASE = {"name": "Sol Ring", "set": "c21", "cn": "263", "finish": "nonfoil", "lang": "", "condition": ""}


def test_row_identity_normalises_case_blank_language_and_condition():
    a = dict(BASE)
    b = dict(BASE, name="SOL RING", set="C21", lang="EN", condition=" nm ")
    c = dict(BASE, condition="NM")
    assert col.row_identity(a)[:3] == ("sol ring", "C21", "263")
    assert col.row_identity(a)[4] == "en" and col.row_identity(b)[4] == "en"
    assert col.row_identity(b) == col.row_identity(c)


def test_foil_and_nonfoil_copies_are_different_rows():
    assert col.row_id(BASE) != col.row_id(dict(BASE, finish="foil"))
    assert col.row_id(BASE) != col.row_id(dict(BASE, finish="etched"))


def test_row_id_is_a_stable_12_hex_and_find_by_id_resolves_it():
    rid = col.row_id(BASE)
    assert len(rid) == 12 and all(ch in "0123456789abcdef" for ch in rid)
    assert col.row_id(dict(BASE)) == rid
    rows = [dict(BASE), dict(BASE, name="Island")]
    assert col.find_by_id(rows, rid) is rows[0]
    assert col.find_by_id(rows, "000000000000") is None


def test_printing_key_ignores_case_and_extra_space():
    assert col.printing_key("Sol Ring", "c21", " 263 ") == ("sol ring", "C21", "263")
    assert col.printing_key("Fire // Ice") == ("fire", "", "")


# -- the decorated-line grammar ---------------------------------------------------------------------------------------

def test_decorated_line_full_form():
    p = col.parse_decorated_line("4x Sol Ring (C21) 263 *F* [Ramp]")
    assert (p["name"], p["qty"], p["qty_x"], p["set"], p["cn"], p["finish"], p["tag"]) == (
        "Sol Ring", 4, True, "C21", "263", "foil", "Ramp")


def test_decorated_line_plain_and_bare_quantity():
    p = col.parse_decorated_line("Sol Ring")
    assert p["name"] == "Sol Ring" and p["qty"] is None and p["finish"] == "nonfoil"
    p = col.parse_decorated_line("3 Island")
    assert p["qty"] == 3 and p["qty_x"] is False and p["name"] == "Island"


def test_decorated_line_etched_marker_and_leading_set_code():
    assert col.parse_decorated_line("1 Sol Ring *E*")["finish"] == "etched"
    p = col.parse_decorated_line("1 [C21] Sol Ring")
    assert p["name"] == "Sol Ring" and p["set"] == "C21"


def test_a_leading_bracket_that_reads_like_a_category_is_not_adopted_as_a_set():
    p = col.parse_decorated_line("1 [Ramp] Sol Ring")
    assert p["name"] == "Sol Ring" and p["set"] == ""        # stripped off the name, not trusted as a set


def test_decorated_line_never_returns_an_empty_name():
    for raw in ("", "   ", "()", "*F*"):
        assert col.parse_decorated_line(raw)["name"] == raw.strip()


# -- the pasted-text row parser -------------------------------------------------------------------------------------------------

def test_parse_rows_from_a_decklist_merges_duplicates_and_keeps_finishes_apart():
    rows = col._parse_rows("2 Sol Ring (C21) 263\n1 Sol Ring (C21) 263\n1 Sol Ring (C21) 263 *F*")
    by_finish = {r["finish"]: r["count"] for r in rows}
    assert by_finish == {"nonfoil": 3, "foil": 1}


def test_parse_rows_from_a_csv_reads_set_codes_counts_and_finish():
    text = ("Name,Count,Edition Code,Collector Number,Foil,Language,Condition\n"
            "Sol Ring,3,c21,263,foil,EN,NM\n"
            "Island,2,,,,,\n")
    rows = col._parse_rows(text)
    sol = next(r for r in rows if r["name"] == "Sol Ring")
    assert (sol["count"], sol["set"], sol["cn"], sol["finish"], sol["lang"], sol["condition"]) == (
        3, "C21", "263", "foil", "en", "NM")
    assert next(r for r in rows if r["name"] == "Island")["count"] == 2


def test_parse_rows_csv_uses_a_generic_edition_only_when_it_looks_like_a_code():
    text = "Name,Count,Edition\nSol Ring,1,Commander 2021\nIsland,1,MH2\n"
    rows = {r["name"]: r for r in col._parse_rows(text)}
    assert rows["Sol Ring"]["set"] == ""          # a set NAME is not a code
    assert rows["Island"]["set"] == "MH2"


def test_parse_rows_csv_tolerates_bad_counts_and_keeps_unmodelled_columns():
    text = "Name,Count,Tags\nSol Ring,abc,vintage\nIsland,2.0,\nForest,0,\n"
    rows = {r["name"]: r for r in col._parse_rows(text)}
    assert rows["Sol Ring"]["count"] == 1 and rows["Sol Ring"]["_extra"] == {"Tags": "vintage"}
    assert rows["Island"]["count"] == 2
    assert rows["Forest"]["count"] == 1            # a zero never silently drops the card


def test_parse_rows_ignores_blank_lines_comments_and_section_headers():
    rows = col._parse_rows("# deck\n\n// note\nCommander: Atraxa, Praetors' Voice\n1 Sol Ring")
    assert sorted(r["name"] for r in rows) == ["Atraxa, Praetors' Voice", "Sol Ring"]


# -- by-id edits on a real file ----------------------------------------------------------------------------------------------------------

def _seed(tmp_path):
    path = tmp_path / "collection.csv"
    col.bulk_import("2 Sol Ring (C21) 263\n1 Island (MH2) 250", mode="replace", path=path)
    return path


def test_set_count_and_remove_by_id_round_trip(tmp_path):
    path = _seed(tmp_path)
    rows = col.load_collection(path)
    sol = next(r for r in rows if r["name"] == "Sol Ring")
    after = col.set_count_by_id(col.row_id(sol), 5, path)
    assert next(r for r in after if r["name"] == "Sol Ring")["count"] == 5
    assert next(r for r in col.load_collection(path) if r["name"] == "Sol Ring")["count"] == 5
    assert all(r["name"] != "Sol Ring" for r in col.set_count_by_id(col.row_id(sol), 0, path))
    isl = next(r for r in col.load_collection(path) if r["name"] == "Island")
    assert col.remove_by_id(col.row_id(isl), path) == []


def test_edits_by_a_stale_id_raise_keyerror(tmp_path):
    path = _seed(tmp_path)
    with pytest.raises(KeyError):
        col.set_count_by_id("deadbeef0000", 3, path)
    with pytest.raises(KeyError):
        col.remove_by_id("deadbeef0000", path)
