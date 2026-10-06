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
