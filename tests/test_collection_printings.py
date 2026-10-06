"""Task 1: collection.py reads and writes every printing column the suite writes
(set code, finish, language, condition, Scryfall id), and finish joins the row identity."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import collection

LIVE_HEADER = ("Count,Name,Edition,Collector Number,Finish,Condition,Date Added,Language,"
               "Edition Name,Edition Code,Multiverse Id,Scryfall ID,Tags")


def test_live_scanner_header_reads_edition_code():
    text = LIVE_HEADER + "\n1,Coastal Piracy,,156,Normal,NM,2026-07-16,EN,Tales,tle,0,abc-id,\n"
    (r,) = collection._parse_rows(text)
    assert (r["set"], r["cn"], r["finish"], r["lang"], r["condition"], r["scryfall_id"]) == \
           ("TLE", "156", "nonfoil", "en", "NM", "abc-id")
    assert "Edition Code" not in r.get("_extra", {}) and "Date Added" in r["_extra"]
    # derivable columns are consumed, not carried
    assert "Edition Name" not in r["_extra"] and "Multiverse Id" not in r["_extra"]


def test_moxfield_edition_is_a_code():
    (r,) = collection._parse_rows("Count,Name,Edition,Foil,Collector Number\n1,Sol Ring,c21,foil,263\n")
    assert (r["set"], r["finish"]) == ("C21", "foil")


def test_deckbox_edition_name_is_not_adopted_as_a_code():
    (r,) = collection._parse_rows("Count,Name,Edition\n1,Sol Ring,Commander 2021\n")
    assert r["set"] == ""


def test_edition_code_wins_even_when_edition_holds_a_name():
    (r,) = collection._parse_rows(
        "Count,Name,Edition,Edition Code\n1,Sol Ring,Commander 2021,c21\n")
    assert r["set"] == "C21"


def test_foil_and_nonfoil_of_one_printing_stay_separate():
    rows = collection._parse_rows("1 Sol Ring (C21) 263\n1 Sol Ring (C21) 263 *F*\n")
    assert sorted((r["finish"], r["count"]) for r in rows) == [("foil", 1), ("nonfoil", 1)]


def test_etched_marker():
    assert collection.parse_decorated_line("1 Sol Ring (CMR) 472 *E*")["finish"] == "etched"


def test_decorated_line_keeps_the_foil_bool_for_existing_callers():
    assert collection.parse_decorated_line("1 Sol Ring (C21) 263 *F*")["foil"] is True
    assert collection.parse_decorated_line("1 Sol Ring (C21) 263")["foil"] is False
    assert collection.parse_decorated_line("1 Sol Ring (C21) 263")["finish"] == "nonfoil"


@pytest.mark.parametrize("value,want", [
    ("", "nonfoil"), ("Normal", "nonfoil"), ("nonfoil", "nonfoil"), ("Non-Foil", "nonfoil"),
    ("no", "nonfoil"), ("false", "nonfoil"),
    ("foil", "foil"), ("F", "foil"), ("Yes", "foil"), ("TRUE", "foil"),
    ("etched", "etched"), ("E", "etched"), ("Foil Etched", "etched"),
])
def test_normalize_finish(value, want):
    assert collection.normalize_finish(value) == want


def test_row_identity_blank_language_is_english_and_finish_separates():
    base = {"name": "Sol Ring", "set": "c21", "cn": "263", "finish": "nonfoil",
            "lang": "", "condition": "nm"}
    assert collection.row_identity(base) == collection.row_identity({**base, "lang": "en",
                                                                     "condition": "NM"})
    assert collection.row_identity(base) != collection.row_identity({**base, "finish": "foil"})
    assert collection.row_identity(base) != collection.row_identity({**base, "lang": "ja"})


def test_blank_condition_merges_into_unique_conditioned_row(tmp_path):
    p = tmp_path / "c.csv"
    collection.write_collection([{"name": "Sol Ring", "count": 1, "set": "C21", "cn": "263",
                                  "finish": "nonfoil", "lang": "en", "condition": "NM"}], p)
    rows = collection.bulk_import("1 Sol Ring (C21) 263", path=p)
    assert [(r["count"], r["condition"]) for r in rows] == [(2, "NM")]


def test_blank_condition_does_not_merge_when_ambiguous_or_other_finish(tmp_path):
    p = tmp_path / "c.csv"
    collection.write_collection([
        {"name": "Sol Ring", "count": 1, "set": "C21", "cn": "263", "finish": "nonfoil",
         "condition": "NM"},
        {"name": "Sol Ring", "count": 1, "set": "C21", "cn": "263", "finish": "nonfoil",
         "condition": "LP"},
        {"name": "Island", "count": 1, "set": "C21", "cn": "1", "finish": "nonfoil",
         "condition": "NM"},
    ], p)
    rows = collection.bulk_import("1 Sol Ring (C21) 263\n1 Island (C21) 1 *F*", path=p)
    sol = [(r["count"], r["condition"]) for r in rows if r["name"] == "Sol Ring"]
    assert sorted(sol) == [(1, ""), (1, "LP"), (1, "NM")]          # ambiguous: new row
    isl = sorted((r["finish"], r["count"]) for r in rows if r["name"] == "Island")
    assert isl == [("foil", 1), ("nonfoil", 1)]                     # foil is not nonfoil


def test_write_header_is_canonical_and_round_trips(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text(LIVE_HEADER + "\n2,Sol Ring,,263,Foil,NM,2026-07-16,EN,C21,c21,0,id1,Unsure\n",
                 encoding="utf-8-sig")
    collection.write_collection(collection.load_collection(p), p)
    head = p.read_text(encoding="utf-8-sig").splitlines()[0]
    assert head == "Count,Name,Edition,Collector Number,Foil,Language,Condition,Scryfall ID,Date Added,Tags"
    (r,) = collection.load_collection(p)
    assert (r["set"], r["finish"], r["scryfall_id"], r["_extra"]["Tags"]) == ("C21", "foil", "id1", "Unsure")


def test_etched_round_trips_through_the_foil_column(tmp_path):
    p = tmp_path / "c.csv"
    collection.write_collection([{"name": "Sol Ring", "count": 1, "set": "CMR", "cn": "472",
                                  "finish": "etched"}], p)
    assert p.read_text(encoding="utf-8-sig").splitlines()[1].split(",")[4] == "etched"
    assert collection.load_collection(p)[0]["finish"] == "etched"


def test_every_row_carries_the_new_keys(tmp_path):
    (r,) = collection._parse_rows("1 Sol Ring")
    for key in ("name", "count", "set", "cn", "finish", "lang", "condition", "scryfall_id"):
        assert key in r
    p = tmp_path / "c.csv"
    rows = collection.add_card("Sol Ring", 1, p)
    assert rows[0]["finish"] == "nonfoil" and rows[0]["scryfall_id"] == ""


def test_owned_names_unchanged_by_printing_columns():
    assert collection.parse_owned(LIVE_HEADER + "\n1,Fire // Ice,,1,,,,,,,,,\n") == {"fire"}


def test_repair_keeps_printing_columns_of_untouched_rows():
    import collection_repair
    rows = [{"name": "Sol Ring", "count": 1, "set": "C21", "cn": "263", "finish": "foil",
             "lang": "ja", "condition": "LP", "scryfall_id": "id9"},
            {"name": "1x Island (msh) 290 *F* [Land]", "count": 1, "set": "", "cn": ""}]
    out, _ = collection_repair.apply_repairs(rows)
    assert (out[0]["finish"], out[0]["lang"], out[0]["condition"], out[0]["scryfall_id"]) == \
           ("foil", "ja", "LP", "id9")
    assert (out[1]["name"], out[1]["set"], out[1]["finish"]) == ("Island", "MSH", "foil")


@pytest.mark.parametrize("edition,want", [
    ("Mirage", ""), ("Alpha", ""), ("Ixalan", ""), ("znr", "ZNR"), ("C21", "C21"), ("40K", "40K"),
])
def test_generic_edition_adopted_only_when_code_shaped(edition, want):
    (r,) = collection._parse_rows(f"Count,Name,Edition\n1,Sol Ring,{edition}\n")
    assert r["set"] == want


def test_dedicated_code_column_is_trusted_even_if_mixed_case():
    (r,) = collection._parse_rows("Count,Name,Edition Code\n1,Sol Ring,Znr\n")
    assert r["set"] == "ZNR"


@pytest.mark.parametrize("order", [("", "NM"), ("NM", "")])
def test_load_keeps_blank_and_conditioned_rows_apart_in_either_order(order):
    body = "".join(f"1,Sol Ring,C21,263,{c}\n" for c in order)
    rows = collection._parse_rows("Count,Name,Edition,Collector Number,Condition\n" + body)
    assert sorted(r["condition"] for r in rows) == ["", "NM"]
