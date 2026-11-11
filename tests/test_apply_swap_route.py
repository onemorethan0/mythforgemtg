"""POST /api/deck/{id}/advise (apply_swap): one-click application of an advisor suggestion. It
rewrites the user's saved deck, so the invariants matter: the cut leaves, the add arrives exactly
once, a singleton deck never gains a duplicate, the stale measurement is dropped, and the swap is
recorded. Scryfall is faked; nothing touches the network or the engine."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from api import routes_strength, state

client = TestClient(server.app)
JOB = "0123456789abcdef"


class _FakeScryfall:
    """name (casefolded, exact OR the fuzzy typo) -> card dict."""

    def __init__(self, cards, typos=None):
        self.cards = {c["name"].casefold(): c for c in cards}
        self.typos = {k.casefold(): v for k, v in (typos or {}).items()}

    def get_card_by_name(self, name, fuzzy=False):
        key = name.casefold()
        if key in self.cards:
            return self.cards[key]
        if fuzzy and key in self.typos:
            return self.cards[self.typos[key].casefold()]
        return None


def _scry(name, **kw):
    return {"name": name, "mana_cost": "{1}", "type_line": "Artifact", "oracle_text": "x", "cmc": 1,
            "color_identity": [], "rarity": "common", "image_uris": {"normal": f"http://img/{name}"}, **kw}


def _entry(name, qty=1):
    return {"original_name": name, "themed_name": f"Themed {name}", "quantity": qty, "render_key": name.replace(" ", "_")}


@pytest.fixture
def deck(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    d = tmp_path / "renders" / JOB
    d.mkdir(parents=True)
    data = {"status": "done", "commander": {"original_name": "Atraxa", "themed_name": "A"},
            "deck": [_entry("Sol Ring"), _entry("Island", 5), _entry("Arcane Signet")],
            "last_measure": {"simulation": {"x": 1}}}
    (d / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    with patch.dict(state._jobs, {}, clear=True):
        yield d


def _swap(cut, add, scry):
    with patch.object(routes_strength, "_scryfall", scry):
        return client.post(f"/api/deck/{JOB}/apply-swap", json={"cut": cut, "add": add})


def _names(r):
    return [c["original_name"] for c in r.json()["deck"]]


def test_a_swap_replaces_the_cut_with_the_add_in_the_same_slot(deck):
    r = _swap("Sol Ring", "Mana Vault", _FakeScryfall([_scry("Mana Vault")]))
    assert r.status_code == 200
    assert _names(r) == ["Mana Vault", "Island", "Arcane Signet"]


def test_the_added_card_is_stored_unthemed_and_flagged(deck):
    r = _swap("Sol Ring", "Mana Vault", _FakeScryfall([_scry("Mana Vault")]))
    new = r.json()["deck"][0]
    assert new["themed_name"] == "Mana Vault" and new["swapped_in"] is True
    assert new["has_render"] is False and new["quantity"] == 1
    assert new["scryfall_img"] == "http://img/Mana Vault"
    assert new["render_key"].endswith("_swap01")


def test_the_stale_measurement_is_dropped_and_the_swap_is_recorded(deck):
    r = _swap("Sol Ring", "Mana Vault", _FakeScryfall([_scry("Mana Vault")]))
    body = r.json()
    assert "last_measure" not in body
    assert body["applied_swaps"][0]["add"] == "Mana Vault" and body["applied_swaps"][0]["cut"] == "Sol Ring"
    assert body["swap_count"] == 1


def test_the_swap_is_persisted_to_deck_json(deck):
    _swap("Sol Ring", "Mana Vault", _FakeScryfall([_scry("Mana Vault")]))
    on_disk = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    assert [c["original_name"] for c in on_disk["deck"]][0] == "Mana Vault"
    assert "last_measure" not in on_disk and on_disk["swap_count"] == 1
    assert on_disk["applied_swaps"][0]["add"] == "Mana Vault"


def test_cutting_one_of_a_stack_decrements_it_instead_of_removing_the_entry(deck):
    r = _swap("Island", "Mana Vault", _FakeScryfall([_scry("Mana Vault")]))
    by = {c["original_name"]: c for c in r.json()["deck"]}
    assert by["Island"]["quantity"] == 4 and "Mana Vault" in by


def test_two_swaps_get_distinct_render_keys_and_count_up(deck):
    scry = _FakeScryfall([_scry("Mana Vault"), _scry("Chrome Mox")])
    _swap("Sol Ring", "Mana Vault", scry)
    r = _swap("Arcane Signet", "Chrome Mox", scry)
    keys = [c["render_key"] for c in r.json()["deck"] if c.get("swapped_in")]
    assert len(set(keys)) == 2 and r.json()["swap_count"] == 2


def test_cut_matching_is_case_insensitive(deck):
    assert _swap("sol ring", "Mana Vault", _FakeScryfall([_scry("Mana Vault")])).status_code == 200


# -- rejections ---------------------------------------------------------------------------------------

def test_a_card_that_is_not_in_the_deck_cannot_be_cut(deck):
    r = _swap("Black Lotus", "Mana Vault", _FakeScryfall([_scry("Mana Vault")]))
    assert r.status_code == 400 and "not in this deck" in r.json()["detail"]


def test_adding_a_card_already_in_the_deck_is_refused(deck):
    r = _swap("Sol Ring", "Island", _FakeScryfall([_scry("Island")]))
    assert r.status_code == 400 and "already in this deck" in r.json()["detail"]


def test_a_typo_that_resolves_to_a_card_already_in_the_deck_is_refused(deck):
    """'arcane signt' passes the typed-name check, then the FUZZY lookup resolves it to 'Arcane
    Signet', which is already here: the swap used to add a second copy to a singleton deck."""
    scry = _FakeScryfall([_scry("Arcane Signet")], typos={"arcane signt": "Arcane Signet"})
    r = _swap("Sol Ring", "arcane signt", scry)
    assert r.status_code == 400
    assert "already in this deck" in r.json()["detail"]
    on_disk = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    assert [c["original_name"] for c in on_disk["deck"]].count("Arcane Signet") == 1
    assert "Sol Ring" in [c["original_name"] for c in on_disk["deck"]]      # and nothing was cut


def test_an_unknown_card_is_a_400_and_leaves_the_deck_untouched(deck):
    before = (deck / "deck.json").read_text(encoding="utf-8")
    r = _swap("Sol Ring", "Nonexistent Card", _FakeScryfall([]))
    assert r.status_code == 400 and "not found" in r.json()["detail"].lower()
    assert (deck / "deck.json").read_text(encoding="utf-8") == before


def test_unknown_deck_and_single_card_decks(deck, tmp_path):
    assert client.post("/api/deck/ffffffffffffffff/apply-swap", json={"cut": "a", "add": "b"}).status_code == 404
    assert client.post("/api/deck/short/apply-swap", json={"cut": "a", "add": "b"}).status_code == 404
    state._jobs[JOB] = {"status": "done", "commander": {"original_name": "X"}, "deck": []}
    assert client.post(f"/api/deck/{JOB}/apply-swap", json={"cut": "a", "add": "b"}).status_code == 400


# ── removing or adding a card on its own (2026-11-11) ────────────────────────────────────────

def _post(body, scry=None):
    with patch.object(routes_strength, "_scryfall", scry or _FakeScryfall([])):
        return client.post(f"/api/deck/{JOB}/apply-swap", json=body)


def test_a_card_can_be_removed_without_a_replacement(deck):
    r = _post({"cut": "Sol Ring"})
    assert r.status_code == 200
    assert _names(r) == ["Island", "Arcane Signet"]
    saved = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    assert [c["original_name"] for c in saved["deck"]] == ["Island", "Arcane Signet"]
    assert "last_measure" not in saved                       # the measurement is stale now
    assert saved["applied_swaps"][-1]["cut"] == "Sol Ring" and saved["applied_swaps"][-1]["add"] is None


def test_removing_one_of_a_stack_keeps_the_rest(deck):
    r = _post({"cut": "Island"})
    assert r.status_code == 200
    assert next(c for c in r.json()["deck"] if c["original_name"] == "Island")["quantity"] == 4


def test_a_card_can_be_added_without_a_cut(deck):
    r = _post({"add": "Mana Vault"}, _FakeScryfall([_scry("Mana Vault")]))
    assert r.status_code == 200
    assert _names(r) == ["Sol Ring", "Island", "Arcane Signet", "Mana Vault"]
    assert r.json()["deck"][-1]["swapped_in"] is True


def test_a_plain_add_is_still_held_to_singleton(deck):
    r = _post({"add": "Sol Ring"}, _FakeScryfall([_scry("Sol Ring")]))
    assert r.status_code == 400 and "already in this deck" in r.json()["detail"]


def test_naming_neither_card_is_refused(deck):
    assert _post({}).status_code == 400
    assert _post({"cut": "  ", "add": ""}).status_code == 400


def test_a_commander_cannot_be_removed_on_its_own(deck):
    data = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    data["partners"] = ["Sol Ring"]
    (deck / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    r = _post({"cut": "Sol Ring"})
    assert r.status_code == 400 and "commander" in r.json()["detail"]
