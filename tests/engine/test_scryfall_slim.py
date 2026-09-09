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


# --- keywords (docs/PLAN_FIDELITY.md Phase B1, 2026-09-10) -------------------------

def test_keywords_roundtrip_lowercased():
    card = _card_from_slim(_slim(_raw_card(keywords=["Flying", "Vigilance"])))
    assert card.keywords == frozenset({"flying", "vigilance"})


def test_no_keywords_is_an_empty_frozenset_not_none():
    card = _card_from_slim(_slim(_raw_card()))  # no "keywords" key at all
    assert card.keywords == frozenset()


def test_a_transform_cards_keywords_are_declined_not_attributed_to_the_front_face():
    """Verified live against the real Scryfall API 2026-09-10: Delver of Secrets //
    Insectile Aberration reports top-level keywords ["Flying", "Transform"], but Flying
    belongs to the BACK face (Insectile Aberration) -- the front face this Card
    represents (Delver of Secrets) has none of its own. `keywords` is a TOP-LEVEL-ONLY
    Scryfall field with no per-face breakdown, so crediting the front face would be a
    fabrication (Delver isn't a flier until it transforms, which this engine does not
    model), not an honest under-count. Declining is correct; this pins it against
    regressing to a naive "use raw.get('keywords')" that would silently start lying
    about 343 stored creature cards (measured 2026-09-10, 1.8% of all creatures)."""
    raw = {
        "name": "Delver of Secrets // Insectile Aberration",
        "layout": "transform",
        "color_identity": ["U"],
        "keywords": ["Flying", "Transform"],  # top-level, aggregated across BOTH faces
        "card_faces": [
            {"name": "Delver of Secrets", "mana_cost": "{U}",
             "type_line": "Creature — Human Wizard", "colors": ["U"],
             "power": "1", "toughness": "1"},
            {"name": "Insectile Aberration", "type_line": "Creature — Human Insect"},
        ],
    }
    card = _card_from_slim(_slim(raw))
    assert card.keywords == frozenset()


def test_a_single_faced_creature_keeps_its_real_keywords():
    """The overwhelming majority of the format (33,327 of 34,856 stored cards are
    `normal` layout) has no face-ambiguity at all -- only the risky layouts decline."""
    raw = _raw_card(name="Serra Angel", layout="normal",
                    type_line="Creature — Angel", keywords=["Flying", "Vigilance"])
    card = _card_from_slim(_slim(raw))
    assert card.keywords == frozenset({"flying", "vigilance"})


@pytest.mark.parametrize("layout", ["transform", "modal_dfc", "meld", "flip"])
def test_every_face_ambiguous_layout_declines(layout):
    card = _card_from_slim(_slim(_raw_card(layout=layout, keywords=["Flying"])))
    assert card.keywords == frozenset()


@pytest.mark.parametrize("layout", ["normal", "adventure", "split", "saga", "class",
                                    "prototype", "leveler", "mutate"])
def test_single_object_layouts_keep_their_keywords(layout):
    """Not every non-'normal' layout is face-ambiguous -- adventure/split/prototype/
    leveler/etc. are all ONE physical object (a creature also castable as a spell, or
    with alternate stats), so a printed keyword genuinely belongs to it. Verified
    2026-09-10 by checking real examples (Adventurous Eater // Have a Bite is a
    'prepare'-layout adventure creature; Goring Warplow is a 'prototype' artifact
    creature; Zulaport Enforcer is a 'leveler') before excluding only the four layouts
    that are genuinely two distinct permanents."""
    card = _card_from_slim(_slim(_raw_card(layout=layout, keywords=["Trample"])))
    assert card.keywords == frozenset({"trample"})


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


def _write_printings_store(tmp_path, monkeypatch, age_days):
    """Point the data dir at tmp_path with a printings slim store aged `age_days`."""
    import json
    import os
    import time

    monkeypatch.setenv("MYTHGAUNTLET_DATA", str(tmp_path))
    store = tmp_path / "printings_slim.json"
    store.write_text(json.dumps({"schema": 1, "printings": {}}), encoding="utf-8")
    when = time.time() - age_days * 86400
    os.utime(store, (when, when))
    return store


def test_printings_fetch_bulk_serves_a_fresh_store(tmp_path, monkeypatch):
    from mythgauntlet.data import printings

    store = _write_printings_store(tmp_path, monkeypatch, age_days=1)
    monkeypatch.setattr(printings.requests, "get", _no_network)
    assert printings.fetch_bulk() == store


def test_printings_fetch_bulk_refetches_a_stale_store(tmp_path, monkeypatch):
    """The same no-age-check bug that froze the oracle store, in the sibling module.

    `printings.fetch_bulk` returned on mere existence long after `scryfall.fetch_bulk`
    was fixed. Only the EDHPlay art export reads printings, so the blast radius is
    smaller — but a frozen store simply has no printings for recently-released cards,
    and art selection falls back or comes up empty with nothing reported.
    """
    from mythgauntlet.data import printings

    _write_printings_store(tmp_path, monkeypatch, age_days=printings.MAX_AGE_DAYS + 1)
    monkeypatch.setattr(printings.requests, "get", _no_network)
    with pytest.raises(_Reached):
        printings.fetch_bulk()


def test_printings_fetch_bulk_max_age_none_accepts_any_store(tmp_path, monkeypatch):
    from mythgauntlet.data import printings

    store = _write_printings_store(tmp_path, monkeypatch, age_days=999)
    monkeypatch.setattr(printings.requests, "get", _no_network)
    assert printings.fetch_bulk(max_age_days=None) == store
