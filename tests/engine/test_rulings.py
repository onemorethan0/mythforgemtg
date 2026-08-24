"""Comprehensive Rules parser -- pure functions, no network (docs/SPEC_deck_mentor.md
Phase 0). The live document runs ~3,500 rules / ~1,000 glossary terms, so these use a
small hand-built fixture that mirrors its real structure (verified against the live
2026-08-19 document while writing the parser) rather than the real size."""

import pytest

from mythgauntlet.data import rulings


# A minimal document with the same STRUCTURE as the real one: intro sentence with the
# "effective as of" marker, a table of contents (bare "Glossary"/"Credits" lines +
# short-number category dividers), a body with a section header / subrule / lettered
# subrule / an unmarked "Example:" continuation line, then the real Glossary and a
# final Credits marker.
_FIXTURE = """\
Magic: The Gathering Comprehensive Rules

These rules are effective as of August 7, 2026.

Contents

1. Game Concepts
100. General
101. The Magic Golden Rules

Glossary
Credits

1. Game Concepts

100. General

100.1. These Magic rules apply to any Magic game with two or more players.

100.1a A two-player game is a game that begins with only two players.

100.1b A multiplayer game is a game that begins with more than two players.
Example: A three-player game is a multiplayer game.

101. The Magic Golden Rules

101.1. Whenever a card's text directly contradicts these rules, the card takes precedence.

Glossary

Ability
1. Text on an object that explains what that object does or can do.
See rule 113, "Abilities."

Ability Word
An italicized word with no rules meaning that ties together abilities on different cards.

Credits
Lead Developer: Someone
"""


def test_split_sections_isolates_body_and_glossary():
    body, glossary = rulings._split_sections(_FIXTURE)
    body_text = "\n".join(body)
    glossary_text = "\n".join(glossary)
    assert "100.1. These Magic rules" in body_text
    assert "Ability Word" not in body_text  # glossary content must not leak into the body
    assert "Ability" in glossary_text
    assert "100.1." not in glossary_text  # and vice versa
    # The table of contents (everything up through the first bare "Credits" line)
    # must not survive into the body.
    assert "Contents" not in body_text


def test_split_sections_raises_on_missing_markers():
    broken = "Magic: The Gathering Comprehensive Rules\n\n100.1. A rule.\n"
    with pytest.raises(RuntimeError, match="structure changed"):
        rulings._split_sections(broken)


def test_parse_rule_body_basic():
    body, _ = rulings._split_sections(_FIXTURE)
    rules = rulings._parse_rule_body(body)
    by_number = {r["number"]: r["text"] for r in rules}
    assert by_number["100"] == "General"
    assert by_number["100.1"] == "These Magic rules apply to any Magic game with two or more players."
    assert by_number["100.1a"] == "A two-player game is a game that begins with only two players."
    assert by_number["101"] == "The Magic Golden Rules"
    assert by_number["101.1"].startswith("Whenever a card's text")


def test_parse_rule_body_appends_continuation_lines():
    """The unmarked 'Example:' line after 100.1b belongs to that rule's text, not a
    separate entry, and the '1. Game Concepts' category divider is dropped entirely."""
    body, _ = rulings._split_sections(_FIXTURE)
    rules = rulings._parse_rule_body(body)
    by_number = {r["number"]: r["text"] for r in rules}
    assert "Example: A three-player game is a multiplayer game." in by_number["100.1b"]
    assert "1" not in by_number  # no rule number "1" was ever created from the divider
    assert not any(r["text"] == "Game Concepts" for r in rules)


def test_parse_glossary_basic():
    _, glossary_lines = rulings._split_sections(_FIXTURE)
    entries = rulings._parse_glossary(glossary_lines)
    by_term = {e["term"]: e["text"] for e in entries}
    assert by_term["Ability"] == (
        '1. Text on an object that explains what that object does or can do. '
        'See rule 113, "Abilities."'
    )
    assert "ties together abilities" in by_term["Ability Word"]


def test_effective_date_extracted():
    m = rulings._EFFECTIVE_DATE_RE.search(_FIXTURE)
    assert m and m.group(1) == "August 7, 2026"


def test_parse_comprehensive_rules_raises_when_corpus_looks_incomplete():
    """The real document parses to ~3,500 rules / ~1,000 glossary terms; this fixture
    has 5 and 2. The floor check exists so a format drift downgrades to a loud error,
    not a corpus that's quietly missing 99% of itself."""
    with pytest.raises(RuntimeError, match="looks incomplete"):
        rulings.parse_comprehensive_rules(_FIXTURE)


# ── ComprehensiveRules + search, built directly (no file I/O) ──────────────────────

def _make_cr():
    return rulings.ComprehensiveRules(
        effective_date="August 7, 2026",
        source_url="https://example.invalid/cr.txt",
        rules={
            "704.5c": "If a creature has toughness 0 or less, it's put into its owner's graveyard.",
            "702.19b": "Trample only matters if the creature would assign enough damage to destroy "
                       "all creatures blocking it.",
        },
        glossary={
            "trample": "A keyword ability. See rule 702.19, \"Trample.\"",
        },
    )


def test_comprehensive_rules_get_rule():
    cr = _make_cr()
    assert cr.get_rule("704.5c").startswith("If a creature has toughness 0")
    assert cr.get_rule("999.9z") is None


def test_comprehensive_rules_get_glossary_term_case_insensitive():
    cr = _make_cr()
    assert cr.get_glossary_term("Trample") == cr.get_glossary_term("trample")
    assert cr.get_glossary_term("Not A Term") is None


def test_rules_search_index_ranks_relevant_rule_first():
    index = rulings.RulesSearchIndex(_make_cr())
    results = index.search("toughness 0 graveyard", k=3)
    assert results, "expected at least one match"
    assert results[0].kind == "rule"
    assert results[0].ref == "704.5c"


def test_rules_search_index_finds_glossary_terms_too():
    index = rulings.RulesSearchIndex(_make_cr())
    results = index.search("trample keyword", k=3)
    assert any(r.kind == "glossary" and r.ref == "trample" for r in results)


def test_rules_search_index_no_crash_on_unrelated_query():
    index = rulings.RulesSearchIndex(_make_cr())
    assert index.search("xyzzy nonexistent quokka", k=3) == []
