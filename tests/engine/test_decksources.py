"""Deck source payload parsing (offline fixtures)."""

from mythgauntlet.data import decksources
from mythgauntlet.data.decksources import (
    archidekt_top,
    parse_archidekt_deck,
    parse_edhrec_average,
)
from mythgauntlet.model.deck import Deck


def test_archidekt_top_passes_bracket_filter(monkeypatch):
    """--bracket flows to the API as edhBracket (server-side labeled-anchor filter)."""
    seen = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{"id": 1, "name": "cEDH deck", "edhBracket": 5,
                                 "viewCount": 9, "owner": {"username": "x"}}]}

    def fake_get(url, params=None, **kw):
        seen.update(params or {})
        return _Resp()

    monkeypatch.setattr(decksources.requests, "get", fake_get)
    monkeypatch.setattr(decksources.time, "sleep", lambda s: None)
    metas = archidekt_top(page_size=3, bracket=5)
    assert seen["edhBracket"] == 5
    assert metas[0].edh_bracket == 5
    seen.clear()
    archidekt_top(page_size=3)  # no bracket -> param absent (unfiltered search unchanged)
    assert "edhBracket" not in seen


def test_edhrec_average_builds_parseable_decklist():
    # The payload's deck list is COMPLETE (basics included with counts); `basic` is
    # informational only and must not add cards.
    payload = {
        "deck": [
            "1 Selvala, Heart of the Wilds",
            "1 Sol Ring",
            "1 Craterhoof Behemoth",
            "25 Forest",
        ],
        "basic": 25,
    }
    fetched = parse_edhrec_average(payload, "Selvala, Heart of the Wilds")
    deck = Deck.parse_text(fetched.text)
    assert deck.commanders == ["Selvala, Heart of the Wilds"]
    names = {e.name: e.count for e in deck.entries}
    assert names["Sol Ring"] == 1
    assert names["Forest"] == 25
    assert deck.total_cards == 28  # exactly the payload's cards, nothing added


def test_edhrec_average_commander_matched_case_insensitively():
    payload = {"deck": ["1 SOME COMMANDER", "1 Sol Ring"]}
    fetched = parse_edhrec_average(payload, "Some Commander")
    deck = Deck.parse_text(fetched.text)
    assert deck.commanders == ["SOME COMMANDER"]
    assert [e.name for e in deck.entries] == ["Sol Ring"]


def test_archidekt_deck_parsing_respects_categories():
    payload = {
        "id": 123,
        "name": "Test Deck",
        "edhBracket": 3,
        "categories": [
            {"name": "Commander", "includedInDeck": True},
            {"name": "Maybeboard", "includedInDeck": False},
            {"name": "Ramp", "includedInDeck": True},
        ],
        "cards": [
            {
                "card": {"oracleCard": {"name": "Kess, Dissident Mage"}},
                "quantity": 1,
                "categories": ["Commander"],
            },
            {
                "card": {"oracleCard": {"name": "Sol Ring"}},
                "quantity": 1,
                "categories": ["Ramp"],
            },
            {
                "card": {"oracleCard": {"name": "Not In Deck"}},
                "quantity": 1,
                "categories": ["Maybeboard"],
            },
            {"card": {"oracleCard": {}}, "quantity": 1, "categories": []},  # tolerated
        ],
    }
    fetched = parse_archidekt_deck(payload)
    assert fetched.bracket == 3
    assert "# bracket: 3" in fetched.text
    deck = Deck.parse_text(fetched.text)
    assert deck.commanders == ["Kess, Dissident Mage"]
    names = [e.name for e in deck.entries]
    assert "Sol Ring" in names
    assert "Not In Deck" not in names
