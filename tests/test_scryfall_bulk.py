"""The local Scryfall bulk store and how ScryfallClient uses it. Offline: synthetic records."""

import json

import pytest

import scryfall_bulk
import scryfall_client


def _card(name, layout="normal", legal=True, rank=100, **kw):
    return {"name": name, "layout": layout, "edhrec_rank": rank,
            "legalities": {"commander": "legal" if legal else "not_legal"},
            "oracle_text": f"{name} text", "uri": "https://drop.me", **kw}


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = tmp_path / "bulk.sqlite"
    monkeypatch.setattr(scryfall_bulk, "db_path", lambda: db)
    monkeypatch.setenv("MYTHFORGE_SCRYFALL_BULK", "on")
    scryfall_bulk._close()
    records = [
        _card("Start // Fire", legal=False, rank=None),   # earlier in the file, not legal
        _card("Fire // Ice", rank=900),
        _card("Sol Ring", rank=1),
        _card("Soldier", layout="token"),
        _card("Delver of Secrets // Insectile Aberration", layout="transform"),
    ]
    assert scryfall_bulk._build_db(records, db) == 4      # the token is not stored
    yield db
    scryfall_bulk._close()


def test_keys_cover_full_name_and_faces():
    assert scryfall_bulk._keys({"name": "Fire // Ice"}) == ["fire // ice", "fire", "ice"]
    assert scryfall_bulk._keys({"name": "Sol Ring"}) == ["sol ring"]


def test_lookup_by_name_face_and_case(store):
    assert scryfall_bulk.lookup("SOL RING ")["name"] == "Sol Ring"
    assert scryfall_bulk.lookup("insectile aberration")["name"].startswith("Delver")
    assert scryfall_bulk.lookup("soldier") is None            # tokens never shadow cards
    assert "uri" not in scryfall_bulk.lookup("sol ring")      # DROP_FIELDS stripped


def test_shared_face_name_goes_to_the_legal_card(store):
    """Live data: "fire" first resolved to Start // Fire (not Commander-legal) because it came
    first in the file; Scryfall's own exact lookup answers Fire // Ice."""
    assert scryfall_bulk.lookup("fire")["name"] == "Fire // Ice"


def test_lookup_many_and_disabled(store, monkeypatch):
    got = scryfall_bulk.lookup_many(["Sol Ring", "nope", "sol ring"])
    assert list(got) == ["sol ring"]
    monkeypatch.setenv("MYTHFORGE_SCRYFALL_BULK", "off")
    assert scryfall_bulk.lookup("sol ring") is None and scryfall_bulk.lookup_many(["sol ring"]) == {}


def test_client_uses_bulk_before_the_network(store, monkeypatch):
    client = scryfall_client.ScryfallClient()
    monkeypatch.setattr(client, "_get", lambda *a, **k: pytest.fail("network called"))
    monkeypatch.setattr(client, "_post_collection", lambda *a, **k: pytest.fail("network called"))
    assert client.get_card_by_name("Sol Ring")["name"] == "Sol Ring"
    got = client.get_cards_collection(["Sol Ring", "Fire // Ice"])
    assert set(got) == {"sol ring", "fire // ice"}


def test_search_cache_reuses_and_never_caches_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(scryfall_client, "_SEARCH_CACHE_DIR", tmp_path / "search")
    monkeypatch.setenv("MYTHFORGE_SCRYFALL_SEARCH_CACHE", "on")
    client = scryfall_client.ScryfallClient()
    calls = []

    def fake_get(path, params=None):
        calls.append(params["q"])
        return None if params["q"] == "broken" else {"data": [{"name": "X"}], "has_more": False}

    monkeypatch.setattr(client, "_get", fake_get)
    assert client.search_cards("otag:ramp")["data"][0]["name"] == "X"
    assert client.search_cards("otag:ramp")["data"][0]["name"] == "X"
    assert calls == ["otag:ramp"]                               # second answer came from disk
    assert client.search_cards("broken")["data"] == []
    assert client.search_cards("broken")["data"] == []
    assert calls.count("broken") == 2                           # a failure is retried, not cached
