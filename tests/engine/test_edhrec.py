"""EDHREC client: slug rules and defensive payload parsing (offline fixtures only)."""

from mythgauntlet.data.edhrec import commander_slug, parse_commander_page


def test_slug_basic():
    assert commander_slug("Kess, Dissident Mage") == "kess-dissident-mage"


def test_slug_apostrophes_and_case():
    assert commander_slug("Atraxa, Praetors' Voice") == "atraxa-praetors-voice"


def test_slug_multiface_takes_front():
    assert commander_slug("Esika, God of the Tree // The Prismatic Bridge") == (
        "esika-god-of-the-tree"
    )


def _fixture_payload():
    return {
        "container": {
            "json_dict": {
                "cardlists": [
                    {
                        "tag": "highsynergycards",
                        "cardviews": [
                            {
                                "name": "Mystic Remora",
                                "synergy": 0.42,
                                "num_decks": 900,
                                "potential_decks": 1000,
                            },
                            {"name": "Unparseable Card"},  # missing stats tolerated
                        ],
                    },
                    {
                        "tag": "topcards",
                        "cardviews": [
                            {
                                "name": "Sol Ring",
                                "synergy": 0.01,
                                "num_decks": 990,
                                "potential_decks": 1000,
                            }
                        ],
                    },
                ]
            }
        }
    }


def test_parse_commander_page_flattens_lists():
    cards = parse_commander_page(_fixture_payload())
    names = {c.name for c in cards}
    assert names == {"Mystic Remora", "Unparseable Card", "Sol Ring"}
    remora = next(c for c in cards if c.name == "Mystic Remora")
    assert remora.category == "highsynergycards"
    assert remora.synergy == 0.42
    assert remora.inclusion_rate == 0.9


def test_parse_tolerates_empty_payload():
    assert parse_commander_page({}) == []
    assert parse_commander_page({"container": {}}) == []
