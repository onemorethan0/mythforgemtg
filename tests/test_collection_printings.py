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


# ---- Task 4: printing-faithful enrichment and finish-aware value -------------------------
import collection_index as ci


def _print(**kw):
    base = {"id": "p1", "oracle_id": "o1", "name": "Sol Ring", "set": "C21", "set_name": "Commander 2021",
            "cn": "263", "rarity": "uncommon", "released_at": "2021-04-23", "lang": "en",
            "finishes": ["nonfoil", "foil"], "frame": "2015", "frame_effects": [], "full_art": False,
            "promo": False, "promo_types": [], "border_color": "black", "artist": "Mike Bierek",
            "layout": "normal", "prices": {"usd": 1.0, "usd_foil": None, "usd_etched": None},
            "images": {"small": "s", "normal": "n", "art_crop": "a"}, "back_images": None}
    base.update(kw)
    return base


def _row(**kw):
    base = {"name": "Sol Ring", "count": 1, "set": "C21", "cn": "263", "finish": "nonfoil",
            "lang": "en", "condition": "", "scryfall_id": "", "_extra": {}}
    base.update(kw)
    return base


_INDEX = {"sol ring": {"name": "Sol Ring", "mana_cost": "{1}", "cmc": 1, "type_line": "Artifact",
                       "type": "Artifact", "colors": [], "color_identity": [], "rarity": "uncommon",
                       "set": "SOC", "set_name": "Commander", "edhrec_rank": 1, "game_changer": False,
                       "is_land": False, "image": "oracle-small"}}


def test_enrich_uses_owned_printing_art():
    prints = {"C21": _print(images={"small": "c21-s", "normal": "c21-n", "art_crop": "c21-a"}),
              "LTC": _print(set="LTC", cn="273", images={"small": "ltc-s", "normal": "ltc-n", "art_crop": "ltc-a"})}
    res = lambda r: prints.get(r["set"])
    a = ci.enrich_row(_row(), _INDEX, resolve_print=res)
    b = ci.enrich_row(_row(set="LTC", cn="273"), _INDEX, resolve_print=res)
    assert (a["image"], b["image"]) == ("c21-s", "ltc-s")
    assert a["image_normal"] == "c21-n" and a["art_crop"] == "c21-a"
    assert a["print_resolved"] is True and a["image_representative"] is False


def test_unresolved_row_keeps_unknown_set_and_flags_representative():
    r = ci.enrich_row(_row(set="", cn=""), _INDEX, resolve_print=lambda r: None)
    assert r["set"] == "" and r["print_resolved"] is False
    assert r["image_representative"] is True and r["image"] == "oracle-small"
    assert r["treatments"] == [] and r["price"] is None


def test_resolver_raising_degrades_to_unresolved():
    def boom(r):
        raise RuntimeError("store exploded")
    r = ci.enrich_row(_row(), _INDEX, resolve_print=boom)
    assert r["print_resolved"] is False and r["image_representative"] is True


def test_default_resolver_with_store_off_degrades_silently():
    r = ci.enrich_row(_row(), _INDEX)       # conftest sets MYTHFORGE_SCRYFALL_PRINTS=off
    assert r["print_resolved"] is False and r["image_representative"] is True


def test_foil_price_never_falls_back_to_nonfoil():
    p = _print(prices={"usd": 1.0, "usd_foil": None, "usd_etched": None})
    r = ci.enrich_row(_row(finish="foil"), _INDEX, resolve_print=lambda r: p)
    assert r["price"] is None
    # even when prices.json knows a number: a resolved print's finish price is final
    r = ci.enrich_row({**_row(finish="foil"), "price": 0.5}, _INDEX, resolve_print=lambda r: p)
    assert r["price"] is None


def test_nonfoil_etched_and_foil_prices():
    p = _print(prices={"usd": 1.0, "usd_foil": 2.5, "usd_etched": 4.0})
    price = lambda finish: ci.enrich_row(_row(finish=finish), _INDEX, resolve_print=lambda r: p)["price"]
    assert (price("nonfoil"), price("foil"), price("etched")) == (1.0, 2.5, 4.0)
    assert ci.print_price(p, "etched") == 4.0
    assert ci.print_price(_print(prices={"usd": None, "usd_foil": 2.5, "usd_etched": None}), "nonfoil") is None


def test_unresolved_row_uses_prices_json_value():
    r = ci.enrich_row({**_row(), "price": 0.75}, _INDEX, resolve_print=lambda r: None)
    assert r["price"] == 0.75


def test_etched_price_is_not_the_foil_price():
    p = _print(prices={"usd": 1.0, "usd_foil": 2.5, "usd_etched": None})
    assert ci.enrich_row(_row(finish="etched"), _INDEX, resolve_print=lambda r: p)["price"] is None


def test_treatments():
    p = _print(border_color="borderless", frame_effects=["showcase", "extendedart"])
    r = ci.enrich_row(_row(), _INDEX, resolve_print=lambda r: p)
    assert set(r["treatments"]) == {"borderless", "showcase", "extended"}
    p = _print(full_art=True, promo=True, frame="1993")
    r = ci.enrich_row(_row(finish="etched"), _INDEX, resolve_print=lambda r: p)
    assert set(r["treatments"]) == {"full_art", "promo", "retro", "etched"}
    assert ci.enrich_row(_row(), _INDEX, resolve_print=lambda r: _print())["treatments"] == []


def test_scryfall_id_fills_blank_set_and_cn():
    p = _print(set="LTC", cn="273", set_name="Tales of Middle-earth Commander")
    r = ci.enrich_row(_row(set="", cn="", scryfall_id="p1"), _INDEX, resolve_print=lambda r: p)
    assert (r["set"], r["cn"], r["set_name"]) == ("LTC", "273", "Tales of Middle-earth Commander")


def test_resolved_fields_come_from_the_print():
    p = _print(rarity="mythic", released_at="2021-04-23", artist="X", finishes=["foil"],
               back_images={"small": "bs", "normal": "bn", "art_crop": "ba"})
    r = ci.enrich_row(_row(), _INDEX, resolve_print=lambda r: p)
    assert (r["rarity"], r["released_at"], r["artist"], r["finishes"], r["back_image"]) == \
           ("mythic", "2021-04-23", "X", ["foil"], "bn")


def test_date_added_comes_from_extra():
    r = ci.enrich_row(_row(_extra={"Date Added": "2026-07-16"}), _INDEX, resolve_print=lambda r: None)
    assert r["date_added"] == "2026-07-16"
    assert ci.enrich_row(_row(), _INDEX, resolve_print=lambda r: None)["date_added"] is None


def test_enrich_rows_resolves_once_per_distinct_printing():
    calls = []
    def res(r):
        calls.append(1)
        return _print()
    rows = [_row(), _row(finish="foil"), _row(), _row(set="LTC")]
    out = ci.enrich_rows(rows, _INDEX, resolve_print=res)
    assert len(out) == 4 and len(calls) == 2    # (C21,263) and (LTC,263); finish is not part of the key


def test_row_without_oracle_meta_still_enriches():
    r = ci.enrich_row(_row(name="Zzz Unknown"), {}, resolve_print=lambda r: _print(name="Zzz Unknown"))
    assert r["print_resolved"] is True and r["resolved"] is False


def test_collection_summary_total_value_uses_the_row_price(monkeypatch):
    import server
    p = _print(prices={"usd": 1.0, "usd_foil": None, "usd_etched": None})
    rows = [_row(count=2), _row(finish="foil", count=3)]
    enriched = ci.enrich_rows(rows, _INDEX, resolve_print=lambda r: p)
    s = server._collection_summary(rows, enriched=enriched)
    assert s["total_value"] == 2.0 and s["priced"] == 1      # the foil row is unpriced, not 3.0


def test_collection_summary_without_enriched_still_works_on_raw_rows():
    import server
    s = server._collection_summary([_row()], prices={})
    assert s["distinct"] == 1 and s["total_value"] == 0.0


def test_scryfall_id_print_wins_over_a_contradicting_row_set():
    p = _print(id="idLTC", set="LTC", cn="273", set_name="Tales Commander", rarity="rare",
               prices={"usd": 9.0, "usd_foil": None, "usd_etched": None})
    r = ci.enrich_row(_row(set="C21", cn="263", scryfall_id="idLTC"), _INDEX, resolve_print=lambda r: p)
    assert (r["set"], r["cn"], r["set_name"]) == ("LTC", "273", "Tales Commander")
    assert r["printing_mismatch"] is True and r["price"] == 9.0 and r["rarity"] == "rare"


def test_printing_mismatch_false_for_a_consistent_row():
    p = _print(id="p1")
    for row in (_row(), _row(scryfall_id="p1"), _row(set="c21", cn="263", scryfall_id="p1"),
                _row(set="", cn="", scryfall_id="p1")):
        assert ci.enrich_row(row, _INDEX, resolve_print=lambda r: p)["printing_mismatch"] is False
    assert ci.enrich_row(_row(), _INDEX, resolve_print=lambda r: None)["printing_mismatch"] is False
