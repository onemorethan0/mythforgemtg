"""Slim-record schema: raw Scryfall -> slim -> Card roundtrip (offline)."""

import pytest

from mythgauntlet.data.scryfall import _card_from_slim, _slim


class _Reached(Exception):
    """Raised in place of a real download, to assert that one was attempted."""


def _no_network(*args, **kwargs):
    raise _Reached



def _raw_card(**overrides):
    raw = {
        "name": "Rhystic Study",
        "layout": "normal",
        "mana_cost": "{2}{U}",
        "type_line": "Enchantment",
        "oracle_text": "Whenever an opponent casts a spell, you may draw a card unless "
        "that player pays {1}.",
        "colors": ["U"],
        "color_identity": ["U"],
        "edhrec_rank": 20,
        "game_changer": True,
        "oracle_id": "abc-123",
    }
    raw.update(overrides)
    return raw


def test_game_changer_flag_roundtrips():
    card = _card_from_slim(_slim(_raw_card()))
    assert card.game_changer is True
    assert card.name == "Rhystic Study"
    assert card.mana_value == 3


def test_game_changer_defaults_false():
    card = _card_from_slim(_slim(_raw_card(game_changer=False)))
    assert card.game_changer is False


def test_tokens_are_skipped():
    assert _slim(_raw_card(layout="token")) is None


def test_dfc_uses_front_face_fields():
    raw = {
        "name": "Delver of Secrets // Insectile Aberration",
        "layout": "transform",
        "color_identity": ["U"],
        "card_faces": [
            {
                "name": "Delver of Secrets",
                "mana_cost": "{U}",
                "type_line": "Creature — Human Wizard",
                "oracle_text": "At the beginning of your upkeep, look at the top card...",
                "colors": ["U"],
                "power": "1",
                "toughness": "1",
            },
            {"name": "Insectile Aberration", "type_line": "Creature — Human Insect"},
        ],
    }
    card = _card_from_slim(_slim(raw))
    assert card.mana_cost_str == "{U}"
    assert card.front_name == "Delver of Secrets"
    assert card.power == "1"


def _write_store(tmp_path, monkeypatch, age_days):
    """Point the data dir at tmp_path with a slim store aged `age_days`."""
    import json
    import os
    import time

    monkeypatch.setenv("MYTHGAUNTLET_DATA", str(tmp_path))
    store = tmp_path / "cards_slim.json"
    store.write_text(json.dumps({"schema": 2, "cards": []}), encoding="utf-8")
    when = time.time() - age_days * 86400
    os.utime(store, (when, when))
    return store


def test_fetch_bulk_serves_a_fresh_store_without_network(tmp_path, monkeypatch):
    from mythgauntlet.data import scryfall

    store = _write_store(tmp_path, monkeypatch, age_days=1)
    monkeypatch.setattr(scryfall.requests, "get", _no_network)
    assert scryfall.fetch_bulk() == store


def test_fetch_bulk_refetches_a_stale_store(tmp_path, monkeypatch):
    """The regression that froze the card universe at 2026-07-05 for 26 days.

    fetch_bulk returned early on mere existence, so the nightly fetch-data phase never
    re-downloaded. Cards printed after the first fetch didn't exist to the engine, and
    corpus decks whose commander was one of them dropped out of every gauntlet.
    """
    from mythgauntlet.data import scryfall

    _write_store(tmp_path, monkeypatch, age_days=scryfall.MAX_AGE_DAYS + 1)
    monkeypatch.setattr(scryfall.requests, "get", _no_network)
    with pytest.raises(_Reached):
        scryfall.fetch_bulk()


def test_fetch_bulk_max_age_none_accepts_any_store(tmp_path, monkeypatch):
    from mythgauntlet.data import scryfall

    store = _write_store(tmp_path, monkeypatch, age_days=999)
    monkeypatch.setattr(scryfall.requests, "get", _no_network)
    assert scryfall.fetch_bulk(max_age_days=None) == store
