"""POST /api/deck/import-preview and /import-save. The importer and the engine are faked; what is
under test is the route's own logic: input validation, error translation (a user error is a 400, an
unexpected failure a 500 that leaks nothing), the response shape, and what import-save writes."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import deck_import
import server
from api import routes_decks, state

client = TestClient(server.app)


def _card(name, type_line="Artifact", ci=(), qty=None, **kw):
    c = {"name": name, "type_line": type_line, "color_identity": list(ci), "cmc": 1,
         "mana_cost": "{1}", "oracle_text": "", "rarity": "common",
         "image_uris": {"normal": f"http://img/{name}"}}
    if qty is not None:
        c["quantity"] = qty
    c.update(kw)
    return c


def _imported(**kw):
    base = dict(
        name="My Deck", source="text",
        commander=_card("Atraxa, Praetors' Voice", "Legendary Creature — Angel Horror // Back", "WUBG"),
        deck=[_card("Sol Ring", qty=1), _card("Island", "Basic Land — Island", qty=30)],
        partners=[], unresolved=["Mystery Card"], auto_face=False)
    base.update(kw)
    return deck_import.ImportedDeck(**base)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    (tmp_path / "renders").mkdir()
    monkeypatch.setattr(routes_decks, "_gauntlet_analyze", lambda *a, **k: {"fake": True})
    yield tmp_path


def _patch_import(result=None, exc=None):
    def fake(source, scryfall, force_refresh=False):
        if exc:
            raise exc
        return result
    return patch.object(deck_import, "import_deck", fake)


# -- preview ------------------------------------------------------------------------------------------

def test_preview_requires_a_source():
    assert client.post("/api/deck/import-preview", json={"source": "   "}).status_code == 400
    assert client.post("/api/deck/import-preview", json={}).status_code == 400


def test_preview_translates_a_user_error_to_400_and_an_unexpected_one_to_500_without_leaking():
    with _patch_import(exc=deck_import.DeckImportError("No cards found")):
        r = client.post("/api/deck/import-preview", json={"source": "x"})
    assert r.status_code == 400 and r.json()["detail"] == "No cards found"
    with _patch_import(exc=RuntimeError("secret internal path C:\\Users\\x")):
        r = client.post("/api/deck/import-preview", json={"source": "x"})
    assert r.status_code == 500 and r.json()["detail"] == "Import failed."
    assert "secret" not in r.text


def test_preview_reports_the_commander_cards_colours_and_unresolved():
    with _patch_import(_imported()):
        body = client.post("/api/deck/import-preview", json={"source": "x"}).json()
    assert body["commander"]["name"] == "Atraxa, Praetors' Voice"
    assert body["commander"]["type_line"] == "Legendary Creature — Angel Horror"      # back face dropped
    assert body["colors"] == ["B", "G", "U", "W"]                                       # sorted, deduped
    assert body["unique_cards"] == 2 and body["total_cards"] == 1 + 1 + 30
    assert [c["name"] for c in body["cards"]] == ["Sol Ring", "Island"]
    assert body["unresolved"] == ["Mystery Card"] and body["simulation"] == {"fake": True}


def test_preview_with_no_commander_still_answers():
    with _patch_import(_imported(commander=None, auto_face=False)):
        body = client.post("/api/deck/import-preview", json={"source": "x"}).json()
    assert body["commander"] is None and body["total_cards"] == 31


def test_preview_lists_partners():
    with _patch_import(_imported(partners=[_card("Thrasios", "Legendary Creature — Merfolk", "GU")])):
        body = client.post("/api/deck/import-preview", json={"source": "x"}).json()
    assert body["partners"] == ["Thrasios"]


# -- save ---------------------------------------------------------------------------------------------

def _saved(tmp, resp):
    return json.loads((tmp / "renders" / resp.json()["job_id"] / "deck.json").read_text(encoding="utf-8"))


def test_save_requires_a_source_and_translates_errors():
    assert client.post("/api/deck/import-save", json={"source": ""}).status_code == 400
    with _patch_import(exc=deck_import.DeckImportError("bad")):
        assert client.post("/api/deck/import-save", json={"source": "x"}).status_code == 400
    with _patch_import(exc=ValueError("boom")):
        assert client.post("/api/deck/import-save", json={"source": "x"}).status_code == 500


def test_save_writes_a_complete_unthemed_deck_json(_isolated):
    with _patch_import(_imported()):
        r = client.post("/api/deck/import-save", json={"source": "1 Sol Ring"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["job_id"]) == 16 and body["imported_only"] is True
    assert body["name"] == "My Deck" and body["unresolved"] == ["Mystery Card"]
    saved = _saved(_isolated, r)
    assert saved["status"] == "done" and saved["imported"] is True and saved["imported_only"] is True
    assert saved["generate_art"] is False and saved["is_commander_deck"] is True
    assert saved["import_source_input"] == "1 Sol Ring" and saved["import_unresolved"] == ["Mystery Card"]
    assert [c["original_name"] for c in saved["deck"]] == ["Sol Ring", "Island"]
    assert saved["commander"]["original_name"] == "Atraxa, Praetors' Voice"
    assert saved["deck_slug"].endswith(r.json()["job_id"][:8])
    assert saved["gen_settings"] == {} and saved["theme_spec"] == {}      # retheme reads these


def test_save_each_time_creates_a_new_entry():
    with _patch_import(_imported()):
        a = client.post("/api/deck/import-save", json={"source": "x"}).json()["job_id"]
        b = client.post("/api/deck/import-save", json={"source": "x"}).json()["job_id"]
    assert a != b


def test_save_renders_partners_as_cards_with_a_quantity():
    with _patch_import(_imported(partners=[_card("Thrasios", "Legendary Creature — Merfolk", "GU")])):
        r = client.post("/api/deck/import-save", json={"source": "x"})
    saved = json.loads((state.RENDER_DIR / r.json()["job_id"] / "deck.json").read_text(encoding="utf-8"))
    names = [c["original_name"] for c in saved["deck"]]
    assert names[-1] == "Thrasios" and saved["deck"][-1]["quantity"] == 1


def test_save_without_any_commander_is_a_400():
    with _patch_import(_imported(commander=None)):
        assert client.post("/api/deck/import-save", json={"source": "x"}).status_code == 400


def test_save_a_non_commander_deck_keeps_the_flag_and_only_trusts_an_auto_face_it_chose():
    with _patch_import(_imported(auto_face=True)):
        r = client.post("/api/deck/import-save", json={"source": "x", "is_commander_deck": False})
    saved = json.loads((state.RENDER_DIR / r.json()["job_id"] / "deck.json").read_text(encoding="utf-8"))
    assert saved["is_commander_deck"] is False and saved["import_auto_face"] is True


def test_a_commander_override_swaps_the_face_and_drops_the_auto_face_flag(monkeypatch):
    class Scry:
        def get_card_by_name(self, name, fuzzy=False):
            return _card("Krenko, Mob Boss", "Legendary Creature — Goblin Warrior", "R")
    monkeypatch.setattr(routes_decks, "_scryfall", Scry())
    with _patch_import(_imported(auto_face=True)):
        r = client.post("/api/deck/import-save", json={"source": "x", "commander_name": "krenko"})
    saved = json.loads((state.RENDER_DIR / r.json()["job_id"] / "deck.json").read_text(encoding="utf-8"))
    assert saved["commander"]["original_name"] == "Krenko, Mob Boss"
    assert saved["import_auto_face"] is False                    # the face is the user's choice now


def test_an_override_that_matches_the_current_commander_changes_nothing(monkeypatch):
    class Scry:
        def get_card_by_name(self, name, fuzzy=False):
            raise AssertionError("must not look up a name that already matches")
    monkeypatch.setattr(routes_decks, "_scryfall", Scry())
    with _patch_import(_imported()):
        r = client.post("/api/deck/import-save", json={"source": "x", "commander_name": "atraxa"})
    assert r.status_code == 200


def test_an_unresolvable_override_falls_back_to_the_imported_commander(monkeypatch):
    class Scry:
        def get_card_by_name(self, name, fuzzy=False):
            return None
    monkeypatch.setattr(routes_decks, "_scryfall", Scry())
    with _patch_import(_imported()):
        r = client.post("/api/deck/import-save", json={"source": "x", "commander_name": "zzzz"})
    saved = json.loads((state.RENDER_DIR / r.json()["job_id"] / "deck.json").read_text(encoding="utf-8"))
    assert saved["commander"]["original_name"] == "Atraxa, Praetors' Voice"


def test_oversized_sources_are_rejected_by_validation():
    assert client.post("/api/deck/import-preview", json={"source": "x" * 20001}).status_code == 422
    assert client.post("/api/deck/import-save", json={"source": "x", "commander_name": "y" * 121}).status_code == 422
