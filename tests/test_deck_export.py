"""Deck export (deck_export.py and its routes): each format, the printing it names, and the batch
ZIP. Offline: the printings store is faked, nothing touches Scryfall, the engine or the GPU."""
from __future__ import annotations

import io
import json
import zipfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import deck_export
import server
from api import routes_decks, state

client = TestClient(server.app)
JOB = "0123456789abcdef"
JOB2 = "fedcba9876543210"


def _entry(name, qty=1, **kw):
    return {"original_name": name, "themed_name": f"Themed {name}", "quantity": qty,
            "mana_cost": "{1}", "type_line": "Artifact", "render_key": name.replace(" ", "_"), **kw}


def _job(**kw):
    job = {"status": "done", "is_commander_deck": True,
           "commander": _entry("Locutus of Borg", type_line="Legendary Artifact Creature — Borg"),
           "deck": [_entry("Sol Ring"), _entry("Island", 3), _entry("Arcane Signet")]}
    job.update(kw)
    return job


PRINTS = {
    "sol ring": [{"lang": "en", "set": "ECC", "cn": "57", "prices": {"usd": 2.01}},
                 {"lang": "en", "set": "C21", "cn": "263", "prices": {"usd": 1.5}},
                 {"lang": "ja", "set": "XXX", "cn": "9", "prices": {"usd": 0.1}}],
    "island": [{"lang": "en", "set": "BLB", "cn": "270", "prices": {"usd": 0.3}}],
    "locutus of borg": [{"lang": "en", "set": "TRC", "cn": "97", "prices": {"usd": 0.5}}],
}


def _lookup(names):
    return {n.strip().lower(): PRINTS.get(n.strip().lower(), []) for n in names}


def test_text_is_the_importable_format_and_round_trips():
    out = deck_export.render(_job(), "text")
    assert out.splitlines() == ["Commander: Locutus of Borg", "", "1 Sol Ring", "3 Island",
                                "1 Arcane Signet"]


def test_unresolved_cards_are_recorded_as_comments():
    out = deck_export.render(_job(import_unresolved=["Not A Card"]), "text")
    assert "# 1 card(s) from the source could not be matched" in out and "# Not A Card" in out


def test_moxfield_writes_the_cheapest_english_nonfoil_printing():
    lines = deck_export.render(_job(), "moxfield", _lookup).splitlines()
    assert lines[:3] == ["1 Locutus of Borg (TRC) 97", "", "1 Sol Ring (C21) 263"]   # not the ja print
    assert "3 Island (BLB) 270" in lines
    assert "1 Arcane Signet" in lines                  # nothing known about it: the bare name


def test_a_printing_named_by_the_source_list_wins():
    job = _job(import_source_input="Commander\n1 Locutus of Borg (TRC) 97\n\n1 Sol Ring (CMR) 472\n")
    out = deck_export.render(job, "moxfield", _lookup)
    assert "1 Sol Ring (CMR) 472" in out.splitlines()


def test_arena_uses_commander_and_deck_headers():
    out = deck_export.render(_job(), "arena", _lookup).splitlines()
    assert out[:4] == ["Commander", "1 Locutus of Borg (TRC) 97", "", "Deck"]
    assert out[4] == "1 Sol Ring (C21) 263"


def test_mtgo_files_the_command_zone_as_sideboard():
    out = deck_export.render(_job(), "mtgo").splitlines()
    assert out[:3] == ["1 Sol Ring", "3 Island", "1 Arcane Signet"]
    assert out[-1] == "SB: 1 Locutus of Borg"


def test_csv_has_a_row_per_card_with_its_zone():
    rows = deck_export.render(_job(), "csv", _lookup).splitlines()
    assert rows[0] == "Quantity,Name,Set,Collector Number,Zone,Mana Cost,Type"
    assert rows[1].startswith("1,Locutus of Borg,TRC,97,Commander,")
    assert any(r.startswith("3,Island,BLB,270,Mainboard,") for r in rows)


def test_partners_are_in_the_command_zone_not_the_99():
    job = _job(partners=["Thrasios, Triton Hero"],
               deck=[_entry("Thrasios, Triton Hero"), _entry("Sol Ring")])
    out = deck_export.render(job, "text").splitlines()
    assert out[:3] == ["Commander: Locutus of Borg", "Commander: Thrasios, Triton Hero", ""]
    assert out.count("1 Thrasios, Triton Hero") == 0


def test_an_auto_elected_face_exports_as_an_ordinary_card():
    job = _job(import_auto_face=True)
    out = deck_export.render(job, "text").splitlines()
    assert "Commander: Locutus of Borg" not in out and "1 Locutus of Borg" in out


def test_backup_is_the_saved_deck_as_json():
    back = json.loads(deck_export.render(_job(), "backup"))
    assert back["commander"]["original_name"] == "Locutus of Borg" and len(back["deck"]) == 3


def test_a_failing_printings_store_falls_back_to_names():
    def boom(names):
        raise RuntimeError("store unavailable")
    assert "1 Sol Ring" in deck_export.render(_job(), "moxfield", boom).splitlines()


def test_unknown_format_is_refused():
    with pytest.raises(ValueError):
        deck_export.render(_job(), "pdf")


# ── routes ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def decks(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    for jid, job in ((JOB, _job()), (JOB2, _job(commander=_entry("Atraxa", type_line="Creature")))):
        d = tmp_path / "renders" / jid
        d.mkdir(parents=True)
        (d / "deck.json").write_text(json.dumps(job), encoding="utf-8")
    with patch.dict(state._jobs, {}, clear=True), \
            patch.object(routes_decks, "_prints_lookup", lambda: _lookup):
        yield


def test_export_list_route_downloads_or_returns_text_for_copy(decks):
    r = client.get(f"/api/deck/{JOB}/export-list", params={"format": "moxfield"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "_moxfield.txt" in r.headers["content-disposition"]
    assert "1 Sol Ring (C21) 263" in r.text
    copy = client.get(f"/api/deck/{JOB}/export-list", params={"format": "arena", "download": "false"})
    assert "content-disposition" not in copy.headers and copy.text.startswith("Commander\n")


def test_export_list_route_rejects_an_unknown_format_and_a_missing_deck(decks):
    assert client.get(f"/api/deck/{JOB}/export-list", params={"format": "nope"}).status_code == 400
    assert client.get("/api/deck/ffffffffffffffff/export-list").status_code == 404


def test_the_old_decklist_route_is_unchanged(decks):
    r = client.get(f"/api/deck/{JOB}/export/decklist")
    assert r.text.splitlines()[0] == "Commander: Locutus of Borg"
    assert "_decklist.txt" in r.headers["content-disposition"]


def test_batch_export_zips_one_file_per_deck_and_reports_skips(decks):
    r = client.post("/api/decks/export-batch",
                    json={"job_ids": [JOB, JOB2, "ffffffffffffffff"], "format": "moxfield"})
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 2 and all(n.endswith(".txt") for n in names)
    assert r.headers["x-skipped"] == "ffffffffffffffff"


def test_batch_export_needs_a_deck_and_a_known_format(decks):
    assert client.post("/api/decks/export-batch", json={"job_ids": []}).status_code == 400
    assert client.post("/api/decks/export-batch",
                       json={"job_ids": [JOB], "format": "nope"}).status_code == 400
    assert client.post("/api/decks/export-batch",
                       json={"job_ids": ["ffffffffffffffff"]}).status_code == 400
