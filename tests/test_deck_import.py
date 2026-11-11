

def test_a_commander_header_ends_at_the_blank_line_not_at_the_end_of_the_list():
    """Archidekt/Moxfield text: '// COMMANDER', the commander, a blank line, then the maindeck with
    NO header. The commander section used to stay open, so all ~100 cards were read as partner
    commanders and the deck could not be edited (2026-11-11, Locutus of Borg)."""
    from deck_import import _parse_text
    raw = _parse_text("// COMMANDER\n1 Locutus of Borg (TRC) 97\n\n1 Sol Ring (TRC) 499\n"
                      "1 Island (TRK) 308\n1 Swamp (TRK) 314\n")
    assert raw.commander_names == ["Locutus of Borg"]
    assert [n for n, _ in raw.card_entries] == ["Sol Ring", "Island", "Swamp"]


def test_a_blank_line_straight_after_the_header_does_not_end_it():
    from deck_import import _parse_text
    raw = _parse_text("Commander\n\n1 Atraxa, Praetors' Voice\n\nDeck\n1 Sol Ring\n")
    assert raw.commander_names == ["Atraxa, Praetors' Voice"]
    assert [n for n, _ in raw.card_entries] == ["Sol Ring"]


def test_two_partner_commanders_under_one_header_both_stay_commanders():
    from deck_import import _parse_text
    raw = _parse_text("Commander\n1 Tymna the Weaver\n1 Thrasios, Triton Hero\n\n1 Sol Ring\n")
    assert raw.commander_names == ["Tymna the Weaver", "Thrasios, Triton Hero"]
    assert [n for n, _ in raw.card_entries] == ["Sol Ring"]
