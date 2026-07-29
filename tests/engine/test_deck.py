from mythgauntlet.data.scryfall import CardDb
from mythgauntlet.model.deck import Deck, resolve


def test_quantities_and_bare_names():
    deck = Deck.parse_text("1 Sol Ring\n2x Island\nLightning Bolt\n")
    assert [(e.name, e.count) for e in deck.entries] == [
        ("Sol Ring", 1),
        ("Island", 2),
        ("Lightning Bolt", 1),
    ]
    assert deck.total_cards == 4


def test_commander_section_and_headers():
    text = """
    Commander:
    1 Kess, Dissident Mage

    Deck:
    1 Sol Ring
    # a comment
    """
    deck = Deck.parse_text(text)
    assert deck.commanders == ["Kess, Dissident Mage"]
    assert [e.name for e in deck.entries] == ["Sol Ring"]


def test_cmdr_marker_and_set_suffix():
    deck = Deck.parse_text("1 Kess, Dissident Mage *CMDR*\n1 Lightning Bolt (M21) 161\n")
    assert deck.commanders == ["Kess, Dissident Mage"]
    assert deck.entries[0].name == "Lightning Bolt"


def test_sideboard_ignored():
    deck = Deck.parse_text("1 Sol Ring\nSideboard:\n1 Island\n")
    assert [e.name for e in deck.entries] == ["Sol Ring"]


def test_resolve_reports_missing(make_card):
    db = CardDb([make_card("Sol Ring", mana_cost="{1}", type_line="Artifact")])
    deck = Deck.parse_text("1 sol ring\n1 Not A Real Card\n")
    resolved = resolve(deck, db)
    assert [c.name for c, _ in resolved.cards] == ["Sol Ring"]  # case-insensitive lookup
    assert resolved.missing == ["Not A Real Card"]


def test_front_face_alias(make_card):
    db = CardDb([make_card("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki")])
    assert db.get("Fable of the Mirror-Breaker") is not None
