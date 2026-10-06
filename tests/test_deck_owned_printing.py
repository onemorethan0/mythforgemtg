"""Deck view: show the printing the user actually owns (Task 14).

Offline: enriched rows are built by hand (the prints store is off in tests), the collection
is isolated with MYTHSUITE_DIR, and the deck-load route reads a real deck.json written to a
monkeypatched RENDER_DIR.
"""
from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

import collection_index as ci
import server

client = TestClient(server.app)
_JOB_ID = "abcdef0123456789"


def _row(name, *, set_="LEA", cn="1", finish="nonfoil", count=1, released="2000-01-01",
         row_id=None, resolved=True):
    return {
        "row_id": row_id or f"{name}|{set_}|{cn}|{finish}",
        "name": name, "count": count, "set": set_, "cn": cn, "finish": finish,
        "rarity": "rare", "set_name": "Some Set", "released_at": released,
        "print_resolved": resolved,
        "image": f"https://img/{set_}{cn}/s.jpg", "image_normal": f"https://img/{set_}{cn}/n.jpg",
        "art_crop": None, "back_image": None,
    }


def _pick(card, rows):
    return ci.pick_owned_printing(card, ci.owned_printings_index(rows)[ci.index_key(card["original_name"])])


def test_pick_prefers_exact_deck_printing():
    rows = [
        _row("Sol Ring", set_="C21", cn="263", count=1, row_id="a"),
        _row("Sol Ring", set_="LEA", cn="270", count=5, row_id="b"),
    ]
    card = {"original_name": "Sol Ring", "set": "lea", "collector_number": "270"}
    # even though the other row has more copies, the exact printing wins
    card2 = {"original_name": "Sol Ring", "set": "c21", "collector_number": "263"}
    assert _pick(card2, rows)["row_id"] == "a"
    assert _pick(card, rows)["row_id"] == "b"


def test_pick_highest_count_then_nonfoil_then_newest():
    card = {"original_name": "Sol Ring"}
    rows = [
        _row("Sol Ring", set_="A", count=1, row_id="low"),
        _row("Sol Ring", set_="B", count=3, finish="foil", row_id="foil3"),
    ]
    assert _pick(card, rows)["row_id"] == "foil3"           # count first
    rows = [
        _row("Sol Ring", set_="A", count=2, finish="foil", row_id="f"),
        _row("Sol Ring", set_="B", count=2, finish="etched", row_id="e"),
        _row("Sol Ring", set_="C", count=2, finish="nonfoil", row_id="n"),
    ]
    assert _pick(card, rows)["row_id"] == "n"                # nonfoil < foil < etched
    rows = [
        _row("Sol Ring", set_="A", count=2, released="2010-01-01", row_id="old"),
        _row("Sol Ring", set_="B", count=2, released="2020-01-01", row_id="new"),
    ]
    assert _pick(card, rows)["row_id"] == "new"              # then newest
    rows = [
        _row("Sol Ring", set_="A", count=2, row_id="b"),
        _row("Sol Ring", set_="A", count=2, row_id="a"),
    ]
    assert _pick(card, rows)["row_id"] == "a"                # then row_id: deterministic
    assert _pick(card, list(reversed(rows)))["row_id"] == "a"
    got = _pick(card, rows)
    assert set(got) == {"row_id", "set", "cn", "finish", "rarity", "set_name",
                        "image", "image_normal", "art_crop", "back_image"}


def test_unresolved_owned_rows_give_none():
    idx = ci.owned_printings_index([_row("Sol Ring", resolved=False)])
    assert idx == {}
    assert ci.pick_owned_printing({"original_name": "Sol Ring"}, []) is None
    # a resolved row for ANOTHER card does not leak in
    idx = ci.owned_printings_index([_row("Sol Ring", resolved=False), _row("Island")])
    assert ci.index_key("Sol Ring") not in idx


def _write_deck(render_dir, deck_cards, commander):
    d = render_dir / _JOB_ID
    d.mkdir(parents=True)
    (d / "deck.json").write_text(json.dumps({
        "status": "done", "commander": commander, "deck": deck_cards,
        "bracket": 2, "bracket_label": "Core", "built_at": "2026-08-26T00:00:00",
    }), encoding="utf-8")


def _fake_enriched(rows):
    return lambda: ([], rows)


def test_annotate_owned_attaches_owned_printing(tmp_path, monkeypatch):
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path))
    (tmp_path / "collection.csv").write_text(
        "Name,Count,Set,Collector Number\nSol Ring,1,LEA,270\nGhost Card,1,,\n", encoding="utf-8")
    monkeypatch.setattr(server, "_owned_cache", {"mtime": None, "set": set()})
    monkeypatch.setattr(server, "_owned_print_cache", {"mtime": None, "index": {}})
    monkeypatch.setattr(server, "_enriched_collection", _fake_enriched([
        _row("Sol Ring", set_="LEA", cn="270"),
        _row("Ghost Card", resolved=False),
    ]))
    render_dir = tmp_path / "renders"
    monkeypatch.setattr(server, "RENDER_DIR", render_dir)
    server._jobs.pop(_JOB_ID, None)
    _write_deck(render_dir, [
        {"original_name": "Sol Ring", "type_line": "Artifact"},
        {"original_name": "Ghost Card", "type_line": "Creature"},
        {"original_name": "Forest", "type_line": "Basic Land — Forest"},
        {"original_name": "Not Owned", "type_line": "Instant"},
    ], {"original_name": "Sol Ring", "type_line": "Artifact"})
    try:
        res = client.get(f"/api/deck/{_JOB_ID}")
    finally:
        server._jobs.pop(_JOB_ID, None)
    assert res.status_code == 200, res.text
    body = res.json()
    by = {c["original_name"]: c for c in body["deck"]}
    assert by["Sol Ring"]["owned_printing"]["set"] == "LEA"
    assert by["Sol Ring"]["owned_printing"]["image_normal"].endswith("/n.jpg")
    assert by["Ghost Card"]["owned"] is True and by["Ghost Card"]["owned_printing"] is None
    assert by["Forest"]["owned"] is True and by["Forest"]["owned_printing"] is None
    assert by["Not Owned"].get("owned_printing") is None
    assert body["commander"]["owned_printing"]["set"] == "LEA"


def test_owned_printing_cache_invalidates_on_csv_change(tmp_path, monkeypatch):
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path))
    csv = tmp_path / "collection.csv"
    csv.write_text("Name,Count\nSol Ring,1\n", encoding="utf-8")
    monkeypatch.setattr(server, "_owned_print_cache", {"mtime": None, "index": {}})
    calls = []

    def fake():
        calls.append(1)
        return [], [_row("Sol Ring", set_="LEA" if len(calls) == 1 else "C21")]
    monkeypatch.setattr(server, "_enriched_collection", fake)

    first = server._owned_printings_cached()
    again = server._owned_printings_cached()
    assert len(calls) == 1 and first is again                 # built once per mtime
    assert first[ci.index_key("Sol Ring")][0]["set"] == "LEA"
    st = csv.stat()
    csv.write_text("Name,Count\nSol Ring,2\n", encoding="utf-8")
    os.utime(csv, (st.st_atime, st.st_mtime + 10))
    third = server._owned_printings_cached()
    assert len(calls) == 2
    assert third[ci.index_key("Sol Ring")][0]["set"] == "C21"
