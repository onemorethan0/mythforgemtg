"""POST /api/deck/{id}/set-commander (owner request, 2026-11-10): make a card from the 99 the
commander. The two cards trade places as they are (themed name, art, render key); an ineligible
card is refused; off-identity cards are reported, not removed; stale measurements are dropped."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from api import state

client = TestClient(server.app)
JOB = "0123456789abcdef"


def _entry(name, type_line, colors, text=""):
    return {"original_name": name, "themed_name": f"Themed {name}", "quantity": 1,
            "render_key": name.replace(" ", "_"), "type_line": type_line,
            "original_type_line": type_line, "colors": colors, "oracle_text": text}


@pytest.fixture
def deck(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    d = tmp_path / "renders" / JOB
    d.mkdir(parents=True)
    data = {"status": "done",
            "commander": _entry("The Borg Queen", "Legendary Artifact Creature — Borg Noble",
                                ["W", "U", "B"]),
            "deck": [_entry("Sol Ring", "Artifact", []),
                     _entry("Locutus of Borg", "Legendary Artifact Creature — Borg",
                            ["W", "U", "B"]),
                     _entry("Seven of Nine", "Legendary Artifact Creature — Borg", ["W", "U"]),
                     _entry("Counterspell", "Instant", ["U"]),
                     _entry("Dark Ritual", "Instant", ["B"]),
                     _entry("Westvale Abbey // Ormendahl", "Land // Legendary Creature — Demon",
                            [])],
            "last_measure": {"simulation": {"x": 1}}, "advice_cache": {"auto": {}}}
    (d / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    with patch.dict(state._jobs, {}, clear=True):
        yield d


def _set(card):
    return client.post(f"/api/deck/{JOB}/set-commander", json={"card": card})


def test_the_two_cards_trade_places(deck):
    r = _set("Locutus of Borg")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["commander"]["original_name"] == "Locutus of Borg"
    assert body["commander"]["render_key"] == "Locutus_of_Borg"      # its art moves with it
    names = [c["original_name"] for c in body["deck"]]
    assert names[1] == "The Borg Queen" and "Locutus of Borg" not in names
    assert len(names) == 6
    assert body["off_identity"] == []
    disk = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    assert disk["commander"]["original_name"] == "Locutus of Borg"
    assert "last_measure" not in disk and "advice_cache" not in disk
    assert disk["commander_switches"][-1]["from"] == "The Borg Queen"


def test_off_identity_cards_are_reported_not_removed(deck):
    body = _set("seven of nine").json()                           # case-insensitive
    assert body["commander"]["original_name"] == "Seven of Nine"
    assert body["off_identity"] == ["Dark Ritual", "Locutus of Borg", "The Borg Queen"]
    assert "Dark Ritual" in [c["original_name"] for c in body["deck"]]


def test_ineligible_cards_are_refused(deck):
    assert _set("Sol Ring").status_code == 400
    # a back-face legend is not a commander (CR 903.3 reads the front face)
    assert _set("Westvale Abbey // Ormendahl").status_code == 400
    assert _set("Not In Deck").status_code == 400
    disk = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    assert disk["commander"]["original_name"] == "The Borg Queen"


def test_partner_decks_are_refused(deck):
    data = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    data["partners"] = ["Seven of Nine"]
    (deck / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    r = _set("Locutus of Borg")
    assert r.status_code == 400 and "partner" in r.json()["detail"]
