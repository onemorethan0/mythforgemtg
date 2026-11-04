"""deck_import.py offline parsing helpers (no network, no Scryfall).

Drafted on a local model (qwen3:14b), then rewritten: the draft invented RawDeck fields
(``cards``, ``quantity``), expected ``_strip_line_metadata`` to return a bare string
(it returns ``(name, tags, printing)``) and assumed an invalid host returns a label
(it raises DeckImportError).
"""
from __future__ import annotations

import pytest

import deck_import as di


def test_detect_source_by_host():
    assert di.detect_source("https://www.moxfield.com/decks/abc") == "moxfield"
    assert di.detect_source("https://archidekt.com/decks/123/x") == "archidekt"
    assert di.detect_source("https://manabox.app/decks/9") == "manabox"
    assert di.detect_source("1 Sol Ring\n4 Island") == "text"
    assert di.detect_source("") == "text"


def test_detect_source_rejects_an_unknown_site():
    with pytest.raises(di.DeckImportError):
        di.detect_source("https://example.com/deck/1")


def test_parse_text_quantities_and_names():
    raw = di._parse_text("1 Sol Ring\n4 Island\n")
    assert raw.source == "text"
    assert raw.card_entries == [("Sol Ring", 1), ("Island", 4)]
    assert raw.commander_names == []


def test_parse_text_accepts_x_suffix_and_skips_blank_and_comment_lines():
    raw = di._parse_text("\n# note\n1x Sol Ring\n\n4x Island\n")
    assert raw.card_entries == [("Sol Ring", 1), ("Island", 4)]


def test_commander_header_collects_the_commander_not_the_deck():
    raw = di._parse_text("Commander\n1 Atraxa, Praetors' Voice\n\nDeck\n1 Sol Ring\n")
    assert raw.commander_names == ["Atraxa, Praetors' Voice"]
    assert raw.card_entries == [("Sol Ring", 1)]


def test_inline_commander_line_and_cmdr_tag():
    assert di._parse_text("Commander: Krenko, Mob Boss\n1 Sol Ring\n").commander_names == ["Krenko, Mob Boss"]
    assert di._parse_text("1 Krenko, Mob Boss *CMDR*\n1 Sol Ring\n").commander_names == ["Krenko, Mob Boss"]


def test_sideboard_lines_are_not_in_the_maindeck():
    raw = di._parse_text("1 Sol Ring\nSB: 1 Swords to Plowshares\n")
    assert raw.card_entries == [("Sol Ring", 1)]


def test_set_and_collector_number_become_a_printing():
    raw = di._parse_text("1 Sol Ring (C21) 263\n")
    assert raw.card_entries == [("Sol Ring", 1)]
    assert raw.printings["sol ring"] == {"set": "C21", "collector_number": "263"}


def test_empty_or_cardless_text_raises():
    for bad in ("", "   \n\n", "# just a comment\n"):
        with pytest.raises(di.DeckImportError):
            di._parse_text(bad)


def test_strip_line_metadata_returns_name_tags_printing():
    assert di._strip_line_metadata("Sol Ring") == ("Sol Ring", [], None)
    name, tags, printing = di._strip_line_metadata("Sol Ring (C21) 263")
    assert (name, tags) == ("Sol Ring", [])
    assert printing == {"set": "C21", "collector_number": "263"}
    name, tags, _ = di._strip_line_metadata("Krenko, Mob Boss *CMDR*")
    assert name == "Krenko, Mob Boss" and tags == ["cmdr"]


def test_cache_id_is_stable_distinct_and_filesystem_safe():
    assert di._cache_id("text", "1 Sol Ring") == di._cache_id("text", " 1 Sol Ring\n")
    assert di._cache_id("text", "1 Sol Ring") != di._cache_id("text", "1 Island")
    assert di._cache_id("text", "x").startswith("text_")
    # URL ids use the LAST path segment only
    assert di._cache_id("archidekt", "https://archidekt.com/decks/111/foo") == "archidekt_foo"
    assert di._cache_id("archidekt", "https://archidekt.com/decks/111") == "archidekt_111"
    assert di._cache_id("archidekt", "https://archidekt.com/decks/111") != di._cache_id(
        "archidekt", "https://archidekt.com/decks/222")
    nasty = di._cache_id("moxfield", "https://moxfield.com/decks/a%20b/../c$d")
    assert all(c.isalnum() or c in "_-" for c in nasty)
