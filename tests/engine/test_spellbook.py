"""Commander Spellbook parsing (offline fixtures)."""

from mythgauntlet.data.spellbook import (
    _request_body,
    is_winning_combo,
    parse_response,
    winning_combos,
)
from mythgauntlet.model.card import normalize_name


def _payload():
    return {
        "results": {
            "identity": "C",
            "included": [
                {
                    "id": "450",
                    "uses": [
                        {"card": {"name": "Basalt Monolith"}},
                        {"card": {"name": "Rings of Brighthearth"}},
                    ],
                    "produces": [{"feature": {"name": "Infinite colorless mana"}}],
                    "bracketTag": "R",
                    "manaNeeded": "{3}",
                    "popularity": 5000,
                },
                {"id": "bad", "uses": []},  # tolerated: dropped
            ],
            "almostIncluded": [
                {
                    "id": "451",
                    "uses": [
                        {"card": {"name": "Basalt Monolith"}},
                        {"card": {"name": "Forsaken Monument"}},
                    ],
                    "produces": [{"feature": {"name": "Infinite colorless mana"}}],
                }
            ],
        }
    }


def test_parse_included_and_almost():
    report = parse_response(_payload())
    assert report.identity == "C"
    assert len(report.included) == 1  # empty-uses variant dropped
    combo = report.included[0]
    assert combo.cards == ("Basalt Monolith", "Rings of Brighthearth")
    assert combo.produces == ("Infinite colorless mana",)
    assert combo.is_two_card
    assert report.two_card_count == 1
    assert len(report.almost_included) == 1


def test_missing_from_deck():
    report = parse_response(_payload())
    deck = {normalize_name("Basalt Monolith")}
    missing = report.almost_included[0].missing_from(deck)
    assert missing == ("Forsaken Monument",)


def test_request_body_shape():
    body = _request_body([("Sol Ring", 1), ("Forest", 30)], ["Selvala, Heart of the Wilds"])
    assert body["main"][0] == {"card": "Sol Ring", "quantity": 1}
    assert body["main"][1]["quantity"] == 30
    assert body["commanders"] == [{"card": "Selvala, Heart of the Wilds", "quantity": 1}]


def test_parse_tolerates_empty():
    report = parse_response({})
    assert report.included == [] and report.almost_included == []


def _combo(cards, produces):
    return {
        "id": "x", "uses": [{"card": {"name": c}} for c in cards],
        "produces": [{"feature": {"name": p}} for p in produces],
    }


def test_winning_combo_detection():
    lethal = parse_response({"results": {"included": [
        _combo(["A", "B"], ["Infinite colorless mana", "Infinite combat damage"]),
    ]}})
    mana_only = parse_response({"results": {"included": [
        _combo(["C", "D"], ["Infinite colorless mana"]),  # no outlet -> not a win
    ]}})
    tokens = parse_response({"results": {"included": [
        _combo(["E", "F", "G"], ["Infinite storm count", "Infinite creature tokens"]),
    ]}})
    assert is_winning_combo(lethal.included[0])
    assert not is_winning_combo(mana_only.included[0])
    assert is_winning_combo(tokens.included[0])  # an infinite board wins the next combat


def test_winning_combos_returns_normalized_piece_sets():
    report = parse_response({"results": {"included": [
        _combo(["Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"],
               ["Infinite combat damage"]),
        _combo(["Sol Ring", "Mana Vault"], ["Infinite colorless mana"]),  # excluded
        _combo(["Thassa's Oracle", "Demonic Consultation"], ["Win the game"]),
    ]}})
    combos = winning_combos(report)
    assert len(combos) == 2
    assert frozenset({normalize_name("Kiki-Jiki, Mirror Breaker"),
                      normalize_name("Zealous Conscripts")}) in combos
    assert all(isinstance(s, frozenset) for s in combos)
