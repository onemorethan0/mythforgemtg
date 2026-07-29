"""Slim-record schema: raw Scryfall -> slim -> Card roundtrip (offline)."""

from mythgauntlet.data.scryfall import _card_from_slim, _slim


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
