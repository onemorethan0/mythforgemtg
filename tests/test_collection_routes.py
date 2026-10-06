"""Stable row identity on the collection API (D6): row_id, id-targeted edits, stale = 409.

Offline: each test points MYTHSUITE_DIR at tmp_path and writes a real collection.csv there
(collection.suite_collection_path() reads the env var on every call).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import collection
import server

client = TestClient(server.app)

_HEADER = "Count,Name,Edition,Collector Number,Foil,Language,Condition,Scryfall ID\n"


@pytest.fixture
def csv_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path))
    return tmp_path / "collection.csv"


def _write(path, *lines):
    path.write_text(_HEADER + "".join(l + "\n" for l in lines), encoding="utf-8")


def _cards():
    r = client.get("/api/collection", params={"limit": 0})
    assert r.status_code == 200
    return r.json()["cards"]


def _by(cards, name, finish):
    return next(c for c in cards if c["name"] == name and c["finish"] == finish)


def test_row_id_is_stable_and_finish_sensitive(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "2,Sol Ring,C21,263,foil,,,")
    first = _cards()
    second = _cards()
    plain, foil = _by(first, "Sol Ring", "nonfoil"), _by(first, "Sol Ring", "foil")
    assert plain["row_id"] != foil["row_id"]
    assert _by(second, "Sol Ring", "nonfoil")["row_id"] == plain["row_id"]
    assert len(plain["row_id"]) == 12 and int(plain["row_id"], 16) >= 0
    # Count is not part of the identity: the id survives a count edit.
    assert collection.row_id({**collection.load_collection()[0], "count": 99}) == plain["row_id"]


def test_row_id_handles_blank_printing_and_unicode(csv_path):
    _write(csv_path, "1,Sol Ring,,,,,,", "1,Lim-Dûl's Vault,,,,,,")
    rows = collection.load_collection()
    ids = [collection.row_id(r) for r in rows]
    assert len(set(ids)) == 2 and all(len(i) == 12 for i in ids)
    assert collection.find_by_id(rows, ids[1])["name"] == "Lim-Dûl's Vault"
    assert collection.find_by_id(rows, "000000000000") is None


def test_get_collection_rows_carry_row_id(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "3,Arcane Signet,C21,297,,,,")
    cards = _cards()
    assert len(cards) == 2
    raw = {r["name"]: collection.row_id(r) for r in collection.load_collection()}
    assert {c["name"]: c["row_id"] for c in cards} == raw


def test_count_by_row_id(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "2,Sol Ring,C21,263,foil,,,")
    foil = _by(_cards(), "Sol Ring", "foil")
    r = client.patch("/api/collection/count", json={"row_id": foil["row_id"], "count": 5})
    assert r.status_code == 200
    after = _cards()
    assert _by(after, "Sol Ring", "foil")["count"] == 5
    assert _by(after, "Sol Ring", "nonfoil")["count"] == 1


def test_count_zero_by_row_id_removes_only_that_row(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "2,Sol Ring,C21,263,foil,,,")
    foil = _by(_cards(), "Sol Ring", "foil")
    client.patch("/api/collection/count", json={"row_id": foil["row_id"], "count": 0})
    left = _cards()
    assert [(c["finish"], c["count"]) for c in left] == [("nonfoil", 1)]


def test_stale_row_id_is_409(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,")
    old = _cards()[0]["row_id"]
    # A second writer (the scanner) changes the row behind the client's back.
    _write(csv_path, "1,Sol Ring,C21,263,foil,,,")
    r = client.patch("/api/collection/count", json={"row_id": old, "count": 9})
    assert r.status_code == 409
    assert "reload" in r.json()["detail"]
    assert collection.load_collection()[0]["count"] == 1   # nothing was written


def test_delete_by_row_id_and_stale_409(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "2,Sol Ring,C21,263,foil,,,")
    plain = _by(_cards(), "Sol Ring", "nonfoil")
    assert client.delete("/api/collection", params={"row_id": plain["row_id"]}).status_code == 200
    assert [c["finish"] for c in _cards()] == ["foil"]
    again = client.delete("/api/collection", params={"row_id": plain["row_id"]})
    assert again.status_code == 409


def test_bulk_remove_by_row_id(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "2,Sol Ring,C21,263,foil,,,",
           "1,Arcane Signet,C21,297,,,,")
    foil = _by(_cards(), "Sol Ring", "foil")
    r = client.post("/api/collection/bulk", json={
        "action": "remove", "targets": [{"row_id": foil["row_id"]}]})
    assert r.status_code == 200 and r.json()["affected"] == 1
    assert sorted((c["name"], c["finish"]) for c in _cards()) == [
        ("Arcane Signet", "nonfoil"), ("Sol Ring", "nonfoil")]


def test_bulk_stale_row_id_is_409_and_writes_nothing(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "1,Arcane Signet,C21,297,,,,")
    good = _by(_cards(), "Arcane Signet", "nonfoil")["row_id"]
    r = client.post("/api/collection/bulk", json={
        "action": "remove", "targets": [{"row_id": good}, {"row_id": "deadbeef0000"}]})
    assert r.status_code == 409
    assert len(_cards()) == 2


def test_old_name_set_cn_targeting_still_works(csv_path):
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "1,Arcane Signet,C21,297,,,,")
    r = client.patch("/api/collection/count",
                     json={"name": "Sol Ring", "count": 4, "set_code": "C21", "cn": "263"})
    assert r.status_code == 200
    assert _by(_cards(), "Sol Ring", "nonfoil")["count"] == 4
    r = client.post("/api/collection/bulk", json={
        "action": "remove", "targets": [{"name": "Arcane Signet", "set": "C21", "cn": "297"}]})
    assert r.json()["affected"] == 1
    assert client.delete("/api/collection", params={"name": "Sol Ring"}).status_code == 200
    assert _cards() == []


# --------------------------------------------------------------------------------------
# Task 5: offline printing picker, finish-aware printing changes, non-destructive Fill
# --------------------------------------------------------------------------------------
import scryfall_prints


def _print(pid, set_code, cn, finishes=("nonfoil", "foil"), usd=1.0, foil=None, released="2024-01-01",
           name="Sol Ring"):
    return {"id": pid, "name": name, "set": set_code, "set_name": f"{set_code} name", "cn": cn,
            "rarity": "uncommon", "released_at": released, "finishes": list(finishes),
            "prices": {"usd": usd, "usd_foil": foil, "usd_etched": None},
            "images": {"small": "s", "normal": f"n-{pid}", "art_crop": f"a-{pid}"},
            "back_images": None, "frame": "2015", "frame_effects": [], "full_art": False,
            "promo": False, "border_color": "black"}


@pytest.fixture
def store(monkeypatch):
    """An in-memory prints store: {name: [prints newest first]}. Fully offline."""
    data: dict[str, list[dict]] = {}

    def prints_of(name):
        return list(data.get((name or "").strip().casefold(), []))

    def by_id(sid):
        return next((p for ps in data.values() for p in ps if p["id"] == sid), None)

    def resolve(name, set_code="", cn="", scryfall_id=""):
        if scryfall_id and by_id(scryfall_id):
            return by_id(scryfall_id)
        ps = [p for p in prints_of(name) if p["set"] == (set_code or "").upper()]
        if cn:
            ps = [p for p in ps if p["cn"].casefold() == str(cn).casefold()]
        return ps[0] if len(ps) == 1 else None

    monkeypatch.setattr(scryfall_prints, "prints_of", prints_of)
    monkeypatch.setattr(scryfall_prints, "by_id", by_id)
    monkeypatch.setattr(scryfall_prints, "resolve", resolve)
    monkeypatch.setattr(scryfall_prints, "enabled", lambda: True)

    def no_network(*a, **k):
        raise AssertionError("network used while the prints store had the card")
    monkeypatch.setattr(server._scryfall, "get_printings", no_network)
    monkeypatch.setattr(server._scryfall, "cheapest_printing", no_network)
    return data


def _sol_store(store):
    store["sol ring"] = [
        _print("id-c21", "C21", "263", usd=1.5, foil=3.0, released="2021-04-23"),
        _print("id-tle", "TLE", "7", finishes=("nonfoil",), usd=0.9, released="2020-01-01"),
        _print("id-old", "LEA", "270", finishes=("nonfoil",), usd=None, released="1993-08-05"),
    ]


def test_printings_marks_owned_rows(csv_path, store):
    _sol_store(store)
    _write(csv_path, "1,Sol Ring,C21,263,,,,", "2,Sol Ring,C21,263,foil,,,", "1,Sol Ring,TLE,,,,,id-tle")
    r = client.get("/api/collection/printings", params={"name": "Sol Ring"})
    assert r.status_code == 200
    items = r.json()["printings"]
    assert [i["id"] for i in items] == ["id-c21", "id-tle", "id-old"]      # store order, newest first
    c21 = items[0]
    assert c21["set"] == "C21" and c21["cn"] == "263" and c21["rarity"] == "uncommon"
    assert c21["prices"] == {"nonfoil": 1.5, "foil": 3.0, "etched": None}
    assert c21["image"] == "n-id-c21" and c21["art_crop"] == "a-id-c21"
    assert c21["finishes"] == ["nonfoil", "foil"] and isinstance(c21["treatments"], list)
    by_finish = {c["finish"]: c for c in _cards() if c["set"] == "C21"}
    assert sorted((o["finish"], o["count"], o["row_id"]) for o in c21["owned"]) == sorted([
        ("nonfoil", 1, by_finish["nonfoil"]["row_id"]), ("foil", 2, by_finish["foil"]["row_id"])])
    # Owned by scryfall id alone (blank cn on the row).
    assert [(o["finish"], o["count"]) for o in items[1]["owned"]] == [("nonfoil", 1)]
    assert items[2]["owned"] == [] and items[2]["prices"]["nonfoil"] is None


def test_printings_live_fallback_when_store_empty(csv_path, monkeypatch):
    monkeypatch.setattr(scryfall_prints, "prints_of", lambda name: [])
    monkeypatch.setattr(server._scryfall, "get_printings", lambda name: [
        {"name": "Sol Ring", "set": "C21", "set_name": "Commander 2021", "collector_number": "263",
         "usd": 1.5, "image": "http://img"}])
    _write(csv_path, "1,Sol Ring,C21,263,,,,")
    items = client.get("/api/collection/printings", params={"name": "Sol Ring"}).json()["printings"]
    assert len(items) == 1
    it = items[0]
    assert it["id"] is None and it["set"] == "C21" and it["cn"] == "263" and it["image"] == "http://img"
    assert it["prices"]["nonfoil"] == 1.5 and it["prices"]["foil"] is None
    assert it["finishes"] == [] and it["treatments"] == [] and it["released_at"] is None
    assert [o["count"] for o in it["owned"]] == [1]


def test_set_printing_rejects_unavailable_finish(csv_path, store):
    _sol_store(store)
    _write(csv_path, "1,Sol Ring,C21,263,foil,,,")
    rid = _cards()[0]["row_id"]
    r = client.patch("/api/collection/printing", json={
        "row_id": rid, "name": "Sol Ring", "set_code": "TLE", "cn": "7", "finish": "foil",
        "scryfall_id": "id-tle"})
    assert r.status_code == 400
    after = collection.load_collection()
    assert (after[0]["set"], after[0]["finish"]) == ("C21", "foil")      # nothing written


def test_set_printing_changes_printing_and_finish_by_id(csv_path, store):
    _sol_store(store)
    _write(csv_path, "3,Sol Ring,C21,263,foil,,,")
    rid = _cards()[0]["row_id"]
    r = client.patch("/api/collection/printing", json={
        "row_id": rid, "set_code": "TLE", "cn": "7", "finish": "nonfoil", "scryfall_id": "id-tle"})
    assert r.status_code == 200
    row = collection.load_collection()[0]
    assert (row["set"], row["cn"], row["finish"], row["scryfall_id"], row["count"]) == (
        "TLE", "7", "nonfoil", "id-tle", 3)


def test_set_printing_stale_row_id_is_409(csv_path, store):
    _sol_store(store)
    _write(csv_path, "1,Sol Ring,C21,263,,,,")
    r = client.patch("/api/collection/printing", json={
        "row_id": "deadbeef0000", "set_code": "TLE", "cn": "7", "finish": "nonfoil"})
    assert r.status_code == 409 and "reload" in r.json()["detail"]


def test_set_printing_merges_identical_row(csv_path, store):
    _sol_store(store)
    _write(csv_path, "2,Sol Ring,C21,263,,,,", "3,Sol Ring,TLE,7,,,,")
    c21 = next(c for c in _cards() if c["set"] == "C21")
    r = client.patch("/api/collection/printing", json={
        "row_id": c21["row_id"], "set_code": "TLE", "cn": "7", "finish": "nonfoil",
        "scryfall_id": "id-tle"})
    assert r.status_code == 200
    rows = collection.load_collection()
    assert len(rows) == 1 and rows[0]["set"] == "TLE" and rows[0]["count"] == 5


def test_set_printing_by_id_unit(tmp_path):
    p = tmp_path / "c.csv"
    _write(p, "2,Sol Ring,C21,263,foil,,,", "1,Sol Ring,C21,263,,,,")
    rows = collection.load_collection(p)
    foil = next(r for r in rows if r["finish"] == "foil")
    out = collection.set_printing_by_id(collection.row_id(foil), "C21", "263", "nonfoil", "id-c21", path=p)
    assert len(out) == 1 and out[0]["count"] == 3 and out[0]["scryfall_id"] == "id-c21"
    with pytest.raises(KeyError):
        collection.set_printing_by_id("deadbeef0000", "C21", "263", "foil", "", path=p)


def test_add_with_finish_creates_separate_row(csv_path, store):
    _sol_store(store)
    for finish in ("nonfoil", "foil", "foil"):
        r = client.post("/api/collection/add", json={
            "name": "Sol Ring", "validate": False, "set_code": "C21", "cn": "263", "finish": finish})
        assert r.status_code == 200
    rows = {(r["finish"]): r["count"] for r in collection.load_collection()}
    assert rows == {"nonfoil": 1, "foil": 2}


def test_add_with_scryfall_id_fills_set_and_cn_from_store(csv_path, store):
    _sol_store(store)
    r = client.post("/api/collection/add", json={"name": "Sol Ring", "validate": False,
                                                 "scryfall_id": "id-tle"})
    assert r.status_code == 200
    row = collection.load_collection()[0]
    assert (row["set"], row["cn"], row["scryfall_id"], row["finish"]) == ("TLE", "7", "id-tle", "nonfoil")


def test_add_with_scryfall_id_and_no_store_stores_as_given(csv_path, monkeypatch):
    monkeypatch.setattr(scryfall_prints, "by_id", lambda sid: None)
    r = client.post("/api/collection/add", json={"name": "Sol Ring", "validate": False,
                                                 "set_code": "c21", "cn": "263", "scryfall_id": "zzz"})
    assert r.status_code == 200
    row = collection.load_collection()[0]
    assert (row["set"], row["cn"], row["scryfall_id"]) == ("C21", "263", "zzz")


def test_add_unavailable_finish_is_400(csv_path, store):
    _sol_store(store)
    r = client.post("/api/collection/add", json={"name": "Sol Ring", "validate": False,
                                                 "scryfall_id": "id-tle", "finish": "foil"})
    assert r.status_code == 400 and collection.load_collection() == []


def test_backfill_never_overwrites_scanner_printing(csv_path, store):
    _sol_store(store)
    store["sol ring"][0]["prices"]["usd"] = 0.01      # C21 is now the cheapest: a replace would pick it
    store["arcane signet"] = [_print("id-as", "C21", "297", usd=0.5, name="Arcane Signet")]
    _write(csv_path, "1,Sol Ring,TLE,7,,,,id-tle", "1,Sol Ring,LEA,270,,,,", "1,Arcane Signet,,,,,,")
    body = client.post("/api/collection/backfill-printings").json()
    rows = {(x["name"], x["set"]): x for x in collection.load_collection()}
    assert rows[("Sol Ring", "TLE")]["scryfall_id"] == "id-tle"
    assert ("Sol Ring", "LEA") in rows and ("Sol Ring", "C21") not in rows
    assert rows[("Arcane Signet", "C21")]["cn"] == "297"
    assert body["filled"] == 1 and body["failed"] == 0


def test_backfill_normalizes_blank_set_from_id_and_merges(csv_path, store):
    _sol_store(store)
    _write(csv_path, "1,Sol Ring,,,,,,id-tle", "2,Sol Ring,TLE,7,,,,")
    body = client.post("/api/collection/backfill-printings").json()
    rows = collection.load_collection()
    assert len(rows) == 1 and rows[0]["set"] == "TLE" and rows[0]["count"] == 3
    assert body["normalized"] == 1 and body["filled"] == 0


def test_backfill_picks_cheapest_print_offering_the_finish(csv_path, store):
    _sol_store(store)
    _write(csv_path, "1,Sol Ring,,,foil,,,", "1,Sol Ring,,,,,,")
    client.post("/api/collection/backfill-printings")
    got = {r["finish"]: r["set"] for r in collection.load_collection()}
    assert got == {"foil": "C21", "nonfoil": "TLE"}      # only C21 prices foil; TLE cheapest nonfoil


def test_backfill_single_write(csv_path, store, monkeypatch):
    _sol_store(store)
    _write(csv_path, "1,Sol Ring,,,,,,", "1,Sol Ring,,,foil,,,")
    calls = []
    real = server.coll_write
    monkeypatch.setattr(server, "coll_write", lambda rows, *a, **k: (calls.append(1), real(rows, *a, **k))[1])
    client.post("/api/collection/backfill-printings")
    assert len(calls) == 1


def test_backfill_live_fallback_only_when_store_unavailable(csv_path, monkeypatch):
    monkeypatch.setattr(scryfall_prints, "prints_of", lambda name: [])
    monkeypatch.setattr(scryfall_prints, "by_id", lambda sid: None)
    monkeypatch.setattr(server._scryfall, "cheapest_printing",
                        lambda name: {"set": "C21", "collector_number": "263"})
    _write(csv_path, "1,Sol Ring,,,,,,")
    body = client.post("/api/collection/backfill-printings").json()
    assert body["filled"] == 1 and collection.load_collection()[0]["set"] == "C21"
