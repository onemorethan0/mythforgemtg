"""A deck must not be called illegal because the card data is older than a set release
(2026-11-12: Star Trek Commander cards, released_at 2026-11-13, were `not_legal` in a copy fetched
on 11-07, so a fully legal Locutus of Borg deck reported "1 legality issue"). Two defences: the card
store refreshes daily while a release is near, and a saved deck re-derives its ban status from the
current store instead of trusting the one saved at build time. Offline."""
import datetime

import pytest

import scryfall_bulk
from api import state


def _rec(name, released, legal="legal"):
    return {"name": name, "layout": "normal", "released_at": released,
            "legalities": {"commander": legal}, "oracle_text": "x"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = tmp_path / "bulk.sqlite"
    monkeypatch.setattr(scryfall_bulk, "db_path", lambda: db)
    monkeypatch.setenv("MYTHFORGE_SCRYFALL_BULK", "on")
    scryfall_bulk._close()
    yield db
    scryfall_bulk._close()


def _today():
    return datetime.date.today()


def _iso(delta_days):
    return (_today() + datetime.timedelta(days=delta_days)).isoformat()


# ── the card store's refresh age ──────────────────────────────────────────────────────────────

def test_the_store_remembers_the_next_upcoming_release(store):
    scryfall_bulk._build_db([_rec("Old", _iso(-400)), _rec("Soon", _iso(5)), _rec("Later", _iso(60))], store)
    assert scryfall_bulk.next_release() == _today() + datetime.timedelta(days=5)


def test_a_store_with_nothing_upcoming_has_no_next_release(store):
    scryfall_bulk._build_db([_rec("Old", _iso(-400))], store)
    assert scryfall_bulk.next_release() is None
    assert scryfall_bulk.effective_max_age() == scryfall_bulk.MAX_AGE_DAYS


def test_it_refreshes_daily_while_a_release_is_near_and_weekly_otherwise(store):
    scryfall_bulk._build_db([_rec("Soon", _iso(5))], store)
    assert scryfall_bulk.effective_max_age() == scryfall_bulk.NEAR_RELEASE_MAX_AGE_DAYS
    scryfall_bulk._build_db([_rec("Far", _iso(40))], store)
    assert scryfall_bulk.effective_max_age() == scryfall_bulk.MAX_AGE_DAYS


def test_a_release_that_has_passed_since_the_store_was_built_counts_as_near(store):
    scryfall_bulk._build_db([_rec("Soon", _iso(3))], store)
    in_ten_days = _today() + datetime.timedelta(days=10)       # the release is now 7 days gone
    assert scryfall_bulk.effective_max_age(today=in_ten_days) == scryfall_bulk.NEAR_RELEASE_MAX_AGE_DAYS


def test_a_missing_store_reads_as_the_default_age(tmp_path, monkeypatch):
    monkeypatch.setattr(scryfall_bulk, "db_path", lambda: tmp_path / "none.sqlite")
    assert scryfall_bulk.next_release() is None
    assert scryfall_bulk.effective_max_age() == scryfall_bulk.MAX_AGE_DAYS


def test_refresh_uses_the_tighter_age_when_a_release_is_near(store, monkeypatch):
    scryfall_bulk._build_db([_rec("Soon", _iso(2))], store)
    import os, time
    two_days_ago = time.time() - 2 * 86400
    os.utime(store, (two_days_ago, two_days_ago))
    called = []

    class Boom(Exception):
        pass

    def fake_get(*a, **k):
        called.append(a)
        raise Boom("network reached")
    monkeypatch.setattr(scryfall_bulk.requests, "get", fake_get)
    with pytest.raises(Boom):                  # 2 days old with a release near: it goes to the network
        scryfall_bulk.refresh()
    assert called


# ── a saved deck re-derives its legality from the current store ──────────────────────────────

def _stored(name, status, ident=("U",)):
    return {"original_name": name, "themed_name": name, "quantity": 1, "type_line": "Artifact",
            "colors": list(ident), "commander_legality": status}


def _deck(statuses):
    return {"commander": {"original_name": "Cmd", "colors": ["U"], "type_line": "Legendary Creature",
                          "commander_legality": "legal"},
            "deck": [_stored(f"Card {i}", s) for i, s in enumerate(statuses)],
            "stats": {}}


def _fake_bulk(monkeypatch, status_by_name):
    def lookup_many(names):
        return {n.lower(): {"legalities": {"commander": status_by_name[n]}}
                for n in names if n in status_by_name}
    monkeypatch.setattr(scryfall_bulk, "lookup_many", lookup_many)


def test_a_stale_not_legal_is_replaced_by_the_current_status(monkeypatch):
    data = _deck(["not_legal"] * 3 + ["legal"] * 96)
    _fake_bulk(monkeypatch, {f"Card {i}": "legal" for i in range(99)})
    state._backfill_legality(data)
    kinds = {i["kind"] for i in data["stats"]["legality"]["issues"]}
    assert "banned" not in kinds and "not_legal" not in kinds
    assert data["stats"]["legality"]["legal"] is True


def test_a_report_saved_on_the_deck_is_recomputed_not_trusted(monkeypatch):
    data = _deck(["legal"] * 99)
    data["stats"] = {"legality": {"legal": False, "issues": [{"kind": "banned", "message": "stale"}]}}
    _fake_bulk(monkeypatch, {f"Card {i}": "legal" for i in range(99)})
    state._backfill_legality(data)
    assert data["stats"]["legality"]["legal"] is True and data["stats"]["legality"]["issues"] == []


def test_a_new_ban_shows_even_though_the_deck_was_saved_legal(monkeypatch):
    data = _deck(["legal"] * 99)
    _fake_bulk(monkeypatch, {"Card 4": "banned"})
    state._backfill_legality(data)
    issues = data["stats"]["legality"]["issues"]
    assert any("Card 4" in i["message"] for i in issues)


def test_a_card_the_store_does_not_know_keeps_its_saved_status(monkeypatch):
    data = _deck(["legal"] * 98 + ["banned"])
    _fake_bulk(monkeypatch, {})                               # nothing known: keep what was saved
    state._backfill_legality(data)
    assert any("Card 98" in i["message"] for i in data["stats"]["legality"]["issues"])


def test_an_unavailable_store_does_not_break_loading(monkeypatch):
    data = _deck(["legal"] * 99)

    def boom(names):
        raise RuntimeError("store offline")
    monkeypatch.setattr(scryfall_bulk, "lookup_many", boom)
    state._backfill_legality(data)                            # must not raise
    assert data["stats"]["legality"]["total"] == 100


# ── a cached import re-derives legality too ──────────────────────────────────────────────────

def _imported(name, status, ident=("U",), type_line="Artifact"):
    return {"name": name, "type_line": type_line, "color_identity": list(ident),
            "legalities": {"commander": status}, "quantity": 1}


def _commander(status):
    return _imported("Cmd", status, type_line="Legendary Creature — Human")


class _Imp:
    def __init__(self, deck, commander):
        self.deck, self.commander, self.partners = deck, commander, []


def test_a_cached_import_is_judged_by_the_current_status(monkeypatch):
    from api import routes_decks
    cmd = _commander("not_legal")
    deck = [_imported(f"Card {i}", "not_legal") for i in range(99)]
    _fake_bulk(monkeypatch, {**{f"Card {i}": "legal" for i in range(99)}, "Cmd": "legal"})
    lg = routes_decks._import_legality(_Imp(deck, cmd))
    assert lg["legal"] is True and lg["issues"] == []
    assert deck[0]["legalities"]["commander"] == "not_legal"     # the cached card itself is not mutated


def test_a_cached_import_with_a_new_ban_reports_it(monkeypatch):
    from api import routes_decks
    cmd = _commander("legal")
    deck = [_imported(f"Card {i}", "legal") for i in range(99)]
    _fake_bulk(monkeypatch, {"Card 7": "banned"})
    lg = routes_decks._import_legality(_Imp(deck, cmd))
    assert any("Card 7" in i["message"] for i in lg["issues"])


def test_an_import_whose_card_store_is_unavailable_keeps_the_carried_status(monkeypatch):
    from api import routes_decks

    def boom(names):
        raise RuntimeError("offline")
    monkeypatch.setattr(scryfall_bulk, "lookup_many", boom)
    cmd = _commander("legal")
    deck = [_imported(f"Card {i}", "legal") for i in range(98)] + [_imported("Bad", "banned")]
    lg = routes_decks._import_legality(_Imp(deck, cmd))
    assert any("Bad" in i["message"] for i in lg["issues"])
