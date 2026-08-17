"""Post-draft basic-land rebalancing (`DeckBuilder._rebalance_basics`).

`_build_lands` runs FIRST and splits basics evenly across the colour identity, because at
that point no spell has been drafted and there is nothing to measure. Ordering candidates
by commander lift made that cost real: the builder benchmark measured colour-castable decks
falling from 10/20 to 8/20 across the roster.

Basics are fungible, so re-splitting them once the deck exists is the cheapest correction
available. No network: basics are stubbed into the module cache.
"""

from __future__ import annotations

import pytest

import deck_builder
from deck_builder import BASIC_LAND, DeckBuilder


class _DeadClient:
    def get_cards_collection(self, names):
        return {}

    def search_cards_paged(self, query, max_results=60):
        raise AssertionError("no search expected in these tests")

    def search_cards(self, query):
        raise AssertionError("no search expected in these tests")


_MANA = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}


@pytest.fixture(autouse=True)
def stub_basics():
    """Populate the module's basic-land cache so _basic_card never hits the network."""
    saved = dict(deck_builder._BASIC_LAND_CACHE)
    for name, sym in _MANA.items():
        deck_builder._BASIC_LAND_CACHE[name] = {
            "name": name, "type_line": f"Basic Land — {name}", "mana_cost": "", "cmc": 0.0,
            "oracle_text": f"({{T}}: Add {{{sym}}}.)", "colors": [],
            "color_identity": [sym], "produced_mana": [sym], "rarity": "common",
        }
    yield
    deck_builder._BASIC_LAND_CACHE.clear()
    deck_builder._BASIC_LAND_CACHE.update(saved)


class _Profile:
    def __init__(self, colors, commander_cost="{1}"):
        self.color_identity = list(colors)
        self.card = {"name": "Cmdr", "type_line": "Legendary Creature — Human",
                     "mana_cost": commander_cost, "oracle_text": "", "cmc": 1}


def _spell(name, cost):
    return {"name": name, "type_line": "Creature — Human", "mana_cost": cost,
            "oracle_text": "", "cmc": 2}


def _builder(deck):
    b = DeckBuilder(_DeadClient())
    b._deck = list(deck)
    b._names = {c["name"] for c in deck}
    return b


def _basics(deck):
    counts = {}
    for c in deck:
        if c["name"] in _MANA:
            counts[_MANA[c["name"]]] = counts.get(_MANA[c["name"]], 0) + 1
    return counts


def _even(colors, n):
    """What _build_lands produces: an even split, decided before any spell exists."""
    out = []
    for i in range(n):
        out.append(deck_builder._BASIC_LAND_CACHE[BASIC_LAND[colors[i % len(colors)]]])
    return out


def test_basics_follow_the_pips_the_deck_actually_demands():
    """The regression this exists for: an even split under a lopsided deck."""
    deck = _even(["W", "B"], 20) + [_spell(f"Black {i}", "{B}{B}") for i in range(15)]
    b = _builder(deck)
    assert _basics(b._deck) == {"W": 10, "B": 10}      # even, as drafted
    b._rebalance_basics(_Profile(["W", "B"]))
    after = _basics(b._deck)
    assert after["B"] > after["W"]
    assert sum(after.values()) == 20                   # land count preserved exactly


def test_every_colour_keeps_at_least_one_basic():
    """A splash you cannot cast at all is worse than one you cast late, and pip_counts
    cannot see activated abilities or a colour only a nonbasic references."""
    deck = _even(["W", "B"], 20) + [_spell(f"Black {i}", "{B}{B}") for i in range(40)]
    b = _builder(deck)
    b._rebalance_basics(_Profile(["W", "B"]))
    after = _basics(b._deck)
    assert after["W"] >= 1
    assert sum(after.values()) == 20


def test_total_is_preserved_across_three_colours():
    deck = _even(["W", "U", "B"], 21) + [
        _spell("A", "{U}{U}{U}"), _spell("B", "{U}{B}"), _spell("C", "{W}")]
    b = _builder(deck)
    b._rebalance_basics(_Profile(["W", "U", "B"]))
    after = _basics(b._deck)
    assert sum(after.values()) == 21
    assert set(after) == {"W", "U", "B"}
    assert after["U"] == max(after.values())


def test_commander_pips_count():
    """You have to be able to cast the commander — it is the one card you always draw."""
    deck = _even(["W", "B"], 20) + [_spell("Neutral", "{2}")]
    b = _builder(deck)
    b._rebalance_basics(_Profile(["W", "B"], commander_cost="{B}{B}{B}"))
    after = _basics(b._deck)
    assert after["B"] > after["W"]


def test_nonbasic_lands_are_never_touched():
    dual = {"name": "Watery Grave", "type_line": "Land — Island Swamp", "mana_cost": "",
            "oracle_text": "", "cmc": 0, "produced_mana": ["U", "B"]}
    deck = _even(["U", "B"], 10) + [dual] + [_spell(f"B{i}", "{B}{B}") for i in range(9)]
    b = _builder(deck)
    b._rebalance_basics(_Profile(["U", "B"]))
    assert sum(1 for c in b._deck if c["name"] == "Watery Grave") == 1
    assert len(b._deck) == 20


def test_mono_and_colourless_are_left_alone():
    for colors in ([], ["G"]):
        deck = (_even(["G"], 8) if colors else []) + [_spell("X", "{2}")]
        b = _builder(deck)
        assert b._rebalance_basics(_Profile(colors)) == {}


def test_noop_when_the_split_already_matches():
    deck = _even(["W", "B"], 20) + [_spell("W1", "{W}"), _spell("B1", "{B}")]
    b = _builder(deck)
    assert b._rebalance_basics(_Profile(["W", "B"])) == {}


def test_deck_with_no_pips_at_all_is_left_alone():
    deck = _even(["W", "B"], 20) + [_spell("Colourless", "{4}")]
    b = _builder(deck)
    assert b._rebalance_basics(_Profile(["W", "B"])) == {}


def test_missing_basic_card_aborts_without_losing_lands():
    """All-or-nothing: a Scryfall miss must not remove basics it cannot put back, or the
    deck lands under 99 and is illegal."""
    deck = _even(["W", "B"], 20) + [_spell(f"B{i}", "{B}{B}") for i in range(9)]
    b = _builder(deck)
    del deck_builder._BASIC_LAND_CACHE["Plains"]

    def _fail(name):
        return None if name == "Plains" else deck_builder._BASIC_LAND_CACHE.get(name)

    b._basic_card = _fail
    assert b._rebalance_basics(_Profile(["W", "B"])) == {}
    assert sum(_basics(b._deck).values()) == 20        # nothing was removed


def test_rebalance_is_deterministic():
    deck = _even(["W", "U", "B"], 18) + [_spell("A", "{U}{B}"), _spell("B", "{W}")]
    a, c = _builder(deck), _builder(deck)
    assert a._rebalance_basics(_Profile(["W", "U", "B"])) == \
           c._rebalance_basics(_Profile(["W", "U", "B"]))
