"""mentor.tools -- offline where possible (no network, uses `empty_store` per
conftest's own documented reason: a bare SemanticsStore() reads a real ~31k-file corpus
on a dev machine and tests the wrong thing). assess_card still runs a real simulation."""

from mythgauntlet.data.scryfall import CardDb
from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.mentor.tools import (
    MentorContext, ToolResult, call_tool,
    _numbers_in, _rule_numbers_in, _to_jsonable,
)
from mythgauntlet.sim.tier0 import SimConfig


# ── extraction helpers ──────────────────────────────────────────────────────────────

def test_numbers_in_walks_nested_structures_and_strings():
    data = {"a": 1, "b": {"c": [2.5, "costs {3} mana"]}, "flag": True}
    nums = _numbers_in(data)
    assert nums == {1.0, 2.5, 3.0}


def test_numbers_in_skips_bare_booleans():
    """A bool is an int subclass in Python (True == 1); without an explicit guard a
    True-only dict would wrongly contribute 1.0 to the budget."""
    assert _numbers_in({"flag": True, "other": False}) == set()


def test_rule_numbers_in_finds_cr_shaped_citations_in_text():
    data = {"text": "See rule 704.5f and also 100.1a for background."}
    rules = _rule_numbers_in(data)
    assert rules == {"704.5f", "100.1a"}


def test_to_jsonable_handles_dataclasses_and_sets():
    from dataclasses import dataclass

    @dataclass
    class Inner:
        x: int

    @dataclass
    class Outer:
        inner: Inner
        tags: frozenset

    out = _to_jsonable(Outer(inner=Inner(x=1), tags=frozenset({"b", "a"})))
    assert out == {"inner": {"x": 1}, "tags": ["a", "b"]}


def test_tool_result_numbers_and_rule_numbers_properties():
    r = ToolResult(data={"number": "704.5f", "text": "toughness 0 or less"},
                    rule_numbers=frozenset({"704.5f"}))
    assert 704.5 in r.numbers
    assert 0.0 in r.numbers
    assert r.all_rule_numbers == frozenset({"704.5f"})


# ── tool functions, with a small synthetic deck ─────────────────────────────────────

def _ctx(make_card, empty_store):
    commander = make_card("Test Commander", type_line="Legendary Creature — Human",
                           mana_cost="{2}{G}", color_identity=("G",))
    ramp = make_card("Rock of Ramping", type_line="Artifact",
                      oracle_text="{T}: Add {G}.", produced_mana=("G",), mana_cost="{2}")
    forest = make_card("Forest", type_line="Basic Land — Forest",
                        produced_mana=("G",), color_identity=("G",))
    db = CardDb([commander, ramp, forest])
    resolved = ResolvedDeck(
        deck=Deck(name="test"), commanders=[commander],
        cards=[(ramp, 1), (forest, 35)], missing=[],
    )
    return MentorContext(
        card_db=db, cr=_fake_cr(), rulings_db={}, resolved=resolved,
        cfg=SimConfig(turns=5, runs=10, seed=1), store=empty_store,
    )


def _fake_cr():
    """A few distinct rules, not one -- BM25's IDF degenerates on a near-single-document
    corpus (a term in exactly half of 2 documents scores IDF=0), which is a fixture-size
    artifact, not something the real ~4,000-document corpus exhibits (verified live)."""
    from mythgauntlet.data.rulings import ComprehensiveRules
    return ComprehensiveRules(
        effective_date="August 7, 2026", source_url="https://example.invalid",
        rules={
            "704.5f": "If a creature has toughness 0 or less, it's put into its owner's graveyard.",
            "104.3a": "A player still in the game loses the game as a state-based action.",
            "702.19b": "The controller of an attacking creature with trample first assigns damage.",
            "121.1": "A player draws a card by putting the top card of their library into their hand.",
        },
        glossary={"trample": "A keyword ability. See rule 702.19, \"Trample.\""},
    )


def test_lookup_card_found(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "lookup_card", {"name": "Rock of Ramping"})
    assert result.data["found"] is True
    assert result.data["oracle_text"] == "{T}: Add {G}."
    assert result.card_names == frozenset({"Rock of Ramping"})


def test_lookup_card_not_found_grants_nothing(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "lookup_card", {"name": "Zzyzx Prism Wyrm"})
    assert result.data["found"] is False
    assert result.card_names == frozenset()


def test_search_rules_returns_rule_kind_results(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "search_rules", {"query": "toughness 0 graveyard", "k": 3})
    assert result.data["results"]
    assert "704.5f" in result.rule_numbers


def test_get_rule_found_and_not_found(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    found = call_tool(ctx, "get_rule", {"number": "704.5f"})
    assert found.data["found"] is True
    assert found.rule_numbers == frozenset({"704.5f"})

    missing = call_tool(ctx, "get_rule", {"number": "999.9z"})
    assert missing.data["found"] is False
    assert missing.rule_numbers == frozenset()


def test_get_deck_stats_reports_curve_and_roles(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "get_deck_stats", {})
    assert "curve" in result.data
    assert "manabase" in result.data
    assert "roles" in result.data
    assert result.data["curve"]["nonland_count"] == 1  # Forest is a land, excluded


def test_deck_card_names_includes_commander_and_nonland_cards(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    names = ctx.deck_card_names
    assert "Test Commander" in names
    assert "Rock of Ramping" in names
    assert "Forest" in names


def test_call_tool_unknown_name(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "not_a_real_tool", {})
    assert result.data["found"] is False


def test_call_tool_bad_arguments(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "lookup_card", {"wrong_kwarg": "x"})
    assert result.data["found"] is False


def test_assess_card_already_in_deck(make_card, empty_store):
    ctx = _ctx(make_card, empty_store)
    result = call_tool(ctx, "assess_card", {"name": "Rock of Ramping"})
    assert result.data["found"] is True
    assert result.data["already_in_deck"] is True
    assert "Rock of Ramping" in result.card_names
