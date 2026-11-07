"""Legality fix-it (B21, docs/DEVELOPMENT_PLAN.md): the pure plan and the endpoint.

The endpoint never modifies the source deck; it writes a NEW deck. Scryfall, EDHREC and the
bulk stores are faked, so nothing touches the network.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import deck_builder
import deck_legality
import server
from api import routes_decks, state

client = TestClient(server.app)
JOB = "0123456789abcdef"


def _c(name, ci=(), tl="Artifact", qty=1, legal="legal", oracle=""):
    return {"name": name, "color_identity": list(ci), "type_line": tl, "quantity": qty,
            "commander_legality": legal, "oracle_text": oracle}


CMDR = _c("Marchesa, the Black Rose", ["U", "B", "R"], "Legendary Creature — Human Wizard")


# ── plan_fix (pure) ────────────────────────────────────────────────────────────────────

def test_off_identity_and_banned_cards_are_removed_and_refilled():
    deck = [_c(f"C{i}") for i in range(96)] + [
        _c("Cankerbloom", ["G"], "Creature"), _c("Mana Crypt", legal="banned"),
        _c("Island", ["U"], "Basic Land — Island")]
    plan = deck_legality.plan_fix(CMDR, deck)
    assert plan["remove"] == ["Cankerbloom", "Mana Crypt"]
    assert plan["refill"] == 2 and plan["fixable"] and plan["unfixable"] == []


def test_extra_copies_split_across_rows_are_reduced_to_the_limit():
    deck = [_c(f"C{i}") for i in range(97)] + [_c("Sol Ring"), _c("Sol Ring")]
    plan = deck_legality.plan_fix(CMDR, deck)
    assert plan["reduce"] == {"Sol Ring": 1} and plan["refill"] == 1


def test_over_100_trims_the_biggest_basic_stack_and_nothing_else():
    """The pre-partner_count Tymna builds: 99 library + 2 commanders = 101."""
    deck = [_c(f"C{i}") for i in range(80)] + [
        _c("Swamp", ["B"], "Basic Land — Swamp", 12), _c("Plains", ["W"], "Basic Land — Plains", 7)]
    tymna = _c("Tymna the Weaver", ["W", "B"], "Legendary Creature — Human", oracle="Partner")
    plan = deck_legality.plan_fix(tymna, deck, [{"name": "Thrasios, Triton Hero"}])
    assert plan["trim"] == {"Swamp": 1} and plan["remove"] == [] and plan["refill"] == 0
    assert plan["fixable"]


def test_a_list_far_too_short_is_not_repaired():
    plan = deck_legality.plan_fix(CMDR, [_c(f"C{i}") for i in range(16)])
    assert not plan["fixable"] and "Rebuild" in plan["unfixable"][0]


def test_over_100_with_no_basics_is_left_to_the_user():
    plan = deck_legality.plan_fix(CMDR, [_c(f"C{i}") for i in range(101)])
    assert not plan["fixable"] and "by hand" in plan["unfixable"][0]


def test_a_legal_deck_has_nothing_to_fix():
    plan = deck_legality.plan_fix(CMDR, [_c(f"C{i}") for i in range(99)])
    assert not plan["fixable"] and plan["unfixable"] == []


# ── endpoint ───────────────────────────────────────────────────────────────────────────

def _stored(name, colors=(), qty=1, tl="Artifact", legal="legal"):
    return {"original_name": name, "themed_name": name, "quantity": qty, "colors": list(colors),
            "type_line": tl, "original_type_line": tl, "commander_legality": legal,
            "render_key": name.replace(" ", "_")}


class _Scry:
    def __init__(self, *cards):
        self.cards = {c["name"].casefold(): c for c in cards}

    def get_card_by_name(self, name, fuzzy=False):
        return self.cards.get((name or "").casefold())


@pytest.fixture
def flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    d = tmp_path / "renders" / JOB
    d.mkdir(parents=True)
    deck = [_stored(f"Card {i}", ["U"]) for i in range(61)] + [
        _stored("Island", ["U"], 37, "Basic Land — Island"),
        _stored("Cankerbloom", ["G"], 1, "Creature — Phyrexian Fungus")]
    data = {"status": "done", "bracket": 3, "deck": deck,
            "commander": {"original_name": "Marchesa, the Black Rose", "colors": ["U", "B", "R"],
                          "type_line": "Legendary Creature — Human Wizard"},
            "last_measure": {"x": 1}}
    (d / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("scryfall_bulk.lookup_many", lambda names: {})
    with patch.dict(state._jobs, {}, clear=True):
        yield d


MARCHESA = {"name": "Marchesa, the Black Rose", "type_line": "Legendary Creature — Human Wizard",
            "oracle_text": "Dethrone", "color_identity": ["U", "B", "R"], "cmc": 4,
            "mana_cost": "{1}{U}{B}{R}", "keywords": []}


def test_dry_run_reports_and_writes_nothing(flagged):
    before = (flagged / "deck.json").read_text(encoding="utf-8")
    with patch.object(routes_decks, "_scryfall", _Scry(MARCHESA)):
        r = client.post(f"/api/deck/{JOB}/fix-legality", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["remove"] == ["Cankerbloom"] and body["refill"] == 1 and body["fixable"]
    assert (flagged / "deck.json").read_text(encoding="utf-8") == before
    assert len(list(flagged.parent.iterdir())) == 1


def test_apply_writes_a_new_legal_deck_and_leaves_the_source_alone(flagged, monkeypatch):
    before = (flagged / "deck.json").read_text(encoding="utf-8")
    refill_calls = {}

    def fake_refill(self, profile, existing, want, bracket=3, partner_names=None, blocked=None):
        refill_calls.update(want=want, blocked=set(blocked or ()), n_existing=len(existing))
        return [{"name": "Counterspell", "type_line": "Instant", "color_identity": ["U"],
                 "mana_cost": "{U}{U}", "cmc": 2, "legalities": {"commander": "legal"}}]
    monkeypatch.setattr(deck_builder.DeckBuilder, "refill", fake_refill)
    with patch.object(routes_decks, "_scryfall", _Scry(MARCHESA)):
        r = client.post(f"/api/deck/{JOB}/fix-legality", json={"apply": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["after"]["legal"] and body["added"] == ["Counterspell"]
    assert refill_calls == {"want": 1, "blocked": {"Cankerbloom"}, "n_existing": 62}
    assert (flagged / "deck.json").read_text(encoding="utf-8") == before
    new = json.loads((flagged.parent / body["new_job_id"] / "deck.json").read_text("utf-8"))
    names = [c["original_name"] for c in new["deck"]]
    assert "Cankerbloom" not in names and "Counterspell" in names
    assert new["fixed_from"] == JOB and "last_measure" not in new
    assert sum(c["quantity"] for c in new["deck"]) == 99


def test_apply_on_an_unfixable_deck_is_refused(flagged):
    with patch.object(routes_decks, "_scryfall", _Scry(MARCHESA)):
        bad = client.post(f"/api/deck/{JOB}/fix-legality",
                          json={"apply": True, "partner": "Thrasios, Triton Hero"})
    assert bad.status_code == 404                         # partner unknown to the fake


def test_a_partner_must_be_a_legal_pairing(flagged):
    sol = {"name": "Sol Ring", "type_line": "Artifact", "oracle_text": "{T}: Add {C}{C}."}
    with patch.object(routes_decks, "_scryfall", _Scry(MARCHESA, sol)):
        r = client.post(f"/api/deck/{JOB}/fix-legality", json={"partner": "Sol Ring"})
    assert r.status_code == 400 and "partner" in r.json()["detail"]


# ── refill respects the bracket's Game Changer cap ─────────────────────────────────────

def test_existing_game_changers_count_against_the_cap():
    from bracket import BracketFilter
    f = BracketFilter(3)                              # Upgraded: max 3 Game Changers
    held = [{"name": n, "game_changer": True} for n in ("A", "B", "C")]
    assert f.count_existing(held + [{"name": "Sol Ring", "game_changer": False}]) == 3
    assert not f.allows({"name": "Force of Will", "game_changer": True, "oracle_text": ""})
    assert f.allows({"name": "Ponder", "game_changer": False, "oracle_text": ""})


def test_refill_never_exceeds_the_cap(monkeypatch):
    import commander_analysis as ca

    class _Client:
        def search_cards_paged(self, query, max_results=60):
            return ([{"name": "Force of Will", "game_changer": True, "type_line": "Instant",
                      "cmc": 5, "oracle_text": "", "color_identity": ["U"]}]
                    + [{"name": f"Filler {i}", "game_changer": False, "type_line": "Instant",
                        "cmc": 2, "oracle_text": "", "color_identity": []} for i in range(10)])

        def search_cards(self, q):
            return {"data": []}

    monkeypatch.setattr(deck_builder.edhrec_lift, "lift_map", lambda name: {})
    lead = {"name": "Talrand, Sky Summoner", "type_line": "Legendary Creature — Merfolk Wizard",
            "oracle_text": "", "color_identity": ["U"], "cmc": 4, "mana_cost": "{2}{U}{U}"}
    existing = [{"name": n, "game_changer": True, "type_line": "Instant", "cmc": 2}
                for n in ("Rhystic Study", "Cyclonic Rift", "Mystic Remora")]
    got = deck_builder.DeckBuilder(_Client()).refill(
        ca.build_commander_profile(lead), existing, 2, bracket=3)
    assert "Force of Will" not in {c["name"] for c in got} and len(got) == 2


def test_a_recorded_partner_missing_from_the_list_is_restored(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    d = tmp_path / "renders" / JOB
    d.mkdir(parents=True)
    deck = [_stored(f"Card {i}", ["W"]) for i in range(87)] + [
        _stored("Swamp", ["B"], 12, "Basic Land — Swamp")]   # 99 library + 2 zone = 101
    data = {"status": "done", "bracket": 3, "deck": deck, "partners": ["Thrasios, Triton Hero"],
            "commander": {"original_name": "Tymna the Weaver", "colors": ["W", "B"],
                          "type_line": "Legendary Creature — Human Cleric"}}
    (d / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("scryfall_bulk.lookup_many", lambda names: {})
    tymna = {"name": "Tymna the Weaver", "type_line": "Legendary Creature — Human Cleric",
             "oracle_text": "Partner", "color_identity": ["W", "B"]}
    thras = {"name": "Thrasios, Triton Hero", "type_line": "Legendary Creature — Merfolk Wizard",
             "oracle_text": "Partner", "color_identity": ["G", "U"],
             "legalities": {"commander": "legal"}}
    with patch.dict(state._jobs, {}, clear=True), \
            patch.object(routes_decks, "_scryfall", _Scry(tymna, thras)):
        r = client.post(f"/api/deck/{JOB}/fix-legality", json={"apply": True})
    assert r.status_code == 200, r.text
    new = json.loads((d.parent / r.json()["new_job_id"] / "deck.json").read_text("utf-8"))
    assert "Thrasios, Triton Hero" in [c["original_name"] for c in new["deck"]]
    assert sum(c["quantity"] for c in new["deck"]) + 1 == 100 and r.json()["after"]["legal"]
