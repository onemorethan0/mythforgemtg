"""Final whole-branch review fixes (I1, I3, I5, M1, M2, M5, M6). Offline."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collection
import collection_index as ci
import collection_repair

CANON = "Count,Name,Edition,Collector Number,Foil,Language,Condition,Scryfall ID\n"


def _csv(tmp_path, *lines, header=CANON):
    p = tmp_path / "collection.csv"
    p.write_text(header + "".join(l + "\n" for l in lines), encoding="utf-8")
    return p


# ---- I1: legacy name-based set_printing -------------------------------------------------

def test_set_printing_foil_does_not_merge_into_nonfoil(tmp_path):
    p = _csv(tmp_path, "1,Sol Ring,C21,263,,,,", "2,Sol Ring,LTC,273,foil,,,")
    rows = collection.set_printing("Sol Ring", "C21", "263", from_set="LTC", from_cn="273", path=p)
    got = sorted((r["set"], r["cn"], r["finish"], r["count"]) for r in rows)
    assert got == [("C21", "263", "foil", 2), ("C21", "263", "nonfoil", 1)]


def test_set_printing_clears_stale_scryfall_id_on_move(tmp_path):
    p = _csv(tmp_path, "3,Sol Ring,LTC,273,,,,old-id")
    (r,) = collection.set_printing("Sol Ring", "C21", "263", from_set="LTC", from_cn="273", path=p)
    assert (r["set"], r["cn"], r["count"], r["scryfall_id"]) == ("C21", "263", 3, "")


def test_set_printing_same_printing_keeps_scryfall_id(tmp_path):
    p = _csv(tmp_path, "1,Sol Ring,C21,263,,,,keep")
    (r,) = collection.set_printing("Sol Ring", "C21", "263", from_set="C21", from_cn="263", path=p)
    assert r["scryfall_id"] == "keep"


# ---- I5: repair keeps etched, carries scryfall_id through merges ------------------------

def test_repair_keeps_etched_finish():
    rows = [{"name": "1x Sol Ring (cmr) 472 *E*", "count": 1, "set": "", "cn": ""}]
    out, _ = collection_repair.apply_repairs(rows)
    assert (out[0]["name"], out[0]["set"], out[0]["finish"]) == ("Sol Ring", "CMR", "etched")


def test_repair_collision_merge_carries_scryfall_id():
    rows = [{"name": "Sol Ring", "count": 1, "set": "C21", "cn": "263", "finish": "nonfoil"},
            {"name": "1x Sol Ring (c21) 263", "count": 1, "set": "", "cn": "", "scryfall_id": "sid1"}]
    out, rep = collection_repair.apply_repairs(rows)
    assert rep["merged"] == 1 and len(out) == 1
    assert out[0]["count"] == 2 and out[0]["scryfall_id"] == "sid1"


# ---- M2 / M6: enrich_row -----------------------------------------------------------------

_INDEX = {"sol ring": {"name": "Sol Ring", "cmc": 1, "type": "Artifact", "type_line": "Artifact",
                       "colors": [], "color_identity": [], "rarity": "uncommon", "set": "SOC",
                       "set_name": "Commander", "is_land": False, "image": "o"}}


def _row(**kw):
    base = {"name": "Sol Ring", "count": 1, "set": "C21", "cn": "263", "finish": "nonfoil",
            "lang": "en", "condition": "", "scryfall_id": "", "_extra": {}}
    base.update(kw)
    return base


def test_unresolved_foil_and_etched_rows_get_no_price():
    for finish in ("foil", "etched"):
        r = ci.enrich_row(_row(finish=finish, price=0.75), _INDEX, resolve_print=lambda r: None)
        assert r["price"] is None
    r = ci.enrich_row(_row(price=0.75), _INDEX, resolve_print=lambda r: None)
    assert r["price"] == 0.75


def test_scryfall_id_compare_is_case_insensitive():
    p = {"id": "ABC-123", "set": "ltc", "cn": "273", "name": "Sol Ring", "finishes": ["nonfoil"],
         "prices": {"usd": 1.0}, "set_name": "T"}
    r = ci.enrich_row(_row(scryfall_id="  abc-123 "), _INDEX, resolve_print=lambda r: p)
    assert r["printing_mismatch"] is True and r["set"] == "ltc"


# ---- M5: one-time pre-printings backup ---------------------------------------------------

def test_pre_printings_backup_is_made_once(tmp_path):
    legacy = "Count,Name,Edition,Collector Number\n"
    p = _csv(tmp_path, "1,Sol Ring,C21,263", header=legacy)
    orig = p.read_bytes()
    rows = collection.load_collection(p)
    collection.write_collection(rows, p)
    bak = tmp_path / "collection.csv.pre-printings.bak"
    assert bak.read_bytes() == orig
    # second write: file is now canonical; the copy must stay as it was
    rows[0]["count"] = 5
    collection.write_collection(rows, p)
    assert bak.read_bytes() == orig
    # even if the header were still legacy, an existing copy is never overwritten
    p.write_bytes(orig)
    collection.write_collection(rows, p)
    assert bak.read_bytes() == orig


def test_canonical_header_file_gets_no_pre_printings_backup(tmp_path):
    p = _csv(tmp_path, "1,Sol Ring,C21,263,,,,")
    collection.write_collection(collection.load_collection(p), p)
    assert not (tmp_path / "collection.csv.pre-printings.bak").exists()
    assert (tmp_path / "collection.csv.bak").exists()


# ---- I3 / M1: server --------------------------------------------------------------------

def test_refresh_prices_also_refreshes_prints_store(tmp_path, monkeypatch):
    import server
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path))
    _csv(tmp_path, "1,Sol Ring,C21,263,,,,")
    db = tmp_path / "prints.sqlite"
    db.write_bytes(b"x")
    future = time.time() + 86400
    os.utime(db, (future, future))
    calls = []
    monkeypatch.setattr(server.scryfall_prints, "refresh", lambda **kw: calls.append(kw))
    monkeypatch.setattr(server.scryfall_prints, "db_path", lambda: db)
    monkeypatch.setattr(server._scryfall, "fetch_prices", lambda rows: {})
    saved = {}
    monkeypatch.setattr(server, "_save_prices", lambda d: saved.update(d))
    monkeypatch.setattr(server, "_load_prices", lambda: dict(saved) or {})
    out = server.collection_refresh_prices()
    assert calls == [{"force": True}]
    assert out["prices_updated"] == server._dt.fromtimestamp(future).isoformat(timespec="seconds")
    assert out["prices_updated"] > saved["updated"]


def test_refresh_prices_survives_prints_refresh_failure(tmp_path, monkeypatch):
    import server
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path))
    _csv(tmp_path, "1,Sol Ring,C21,263,,,,")

    def boom(**kw):
        raise RuntimeError("offline")

    monkeypatch.setattr(server.scryfall_prints, "refresh", boom)
    monkeypatch.setattr(server.scryfall_prints, "db_path", lambda: tmp_path / "missing.sqlite")
    monkeypatch.setattr(server._scryfall, "fetch_prices", lambda rows: {})
    saved = {}
    monkeypatch.setattr(server, "_save_prices", lambda d: saved.update(d))
    monkeypatch.setattr(server, "_load_prices", lambda: dict(saved))
    out = server.collection_refresh_prices()
    assert saved["updated"] and out["prices_updated"] == saved["updated"]


def test_owned_printings_cache_not_poisoned_by_failure_and_keyed_on_store(tmp_path, monkeypatch):
    import server
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path))
    _csv(tmp_path, "1,Sol Ring,C21,263,,,,")
    db = tmp_path / "prints.sqlite"
    monkeypatch.setattr(server.scryfall_prints, "db_path", lambda: db)
    monkeypatch.setattr(server, "_owned_print_cache", {"mtime": None, "index": {}})
    state = {"fail": True, "calls": 0}

    def fake_enriched():
        state["calls"] += 1
        if state["fail"]:
            raise RuntimeError("store busy")
        return [], [{"name": "Sol Ring"}]

    monkeypatch.setattr(server, "_enriched_collection", fake_enriched)
    monkeypatch.setattr(server, "owned_printings_index", lambda enriched: {"sol ring": ["p"]})
    assert server._owned_printings_cached() == {}
    state["fail"] = False
    assert server._owned_printings_cached() == {"sol ring": ["p"]}     # retried, not stuck empty
    n = state["calls"]
    server._owned_printings_cached()
    assert state["calls"] == n                                         # cached now
    db.write_bytes(b"new store")                                       # store rebuilt
    server._owned_printings_cached()
    assert state["calls"] == n + 1
