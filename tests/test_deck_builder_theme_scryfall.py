"""Tests for DeckBuilder._fetch_theme_synergy_list's SCRYFALL branch.

`tests/test_deck_builder_theme.py` covers the STRICT branch thoroughly — including that
`want` is split across the active themes with the remainder going to the lead. The
Scryfall branch, which is what every ordinary build actually runs, had no equivalent test,
and that is exactly where a bug survived:

    `slot` was computed per theme and never used. The draft loop broke on
    `added >= want`, so the FIRST theme consumed the entire package. A Krenko build
    (tribal_goblins + tokens) drafted 20 goblin cards and ZERO token cards, and a
    third theme was unreachable no matter what `resolve_themes` produced.

The strict path had the same shape and got it right, so the two branches disagreed on the
step's central promise. These tests hold the Scryfall branch to it.

No network: the stub client returns a distinct, plentiful pool per theme query, so the
distribution across themes is readable straight off the drafted names.
"""

from __future__ import annotations

import pytest

import deck_builder
from deck_builder import DeckBuilder

# Which theme a query is for, by a word only that theme's THEME_SYNERGY_QUERIES contains.
_TAGS = (("goblin", "GOB"), ("token", "TOK"), ("dragon", "DRG"), ("elf", "ELF"))


class _ThemeStub:
    """Returns 60 distinct candidates per theme; `dry` themes return nothing."""

    def __init__(self, dry: set[str] | None = None, pool: int = 60):
        self.dry = dry or set()
        self.pool = pool
        self.queries: list[str] = []

    def get_cards_collection(self, names):
        return {}

    def search_cards(self, query):
        return []

    def search_cards_paged(self, query, max_results=60):
        self.queries.append(query)
        q = query.lower()
        tag = next((t for word, t in _TAGS if word in q), "OTH")
        if tag in self.dry:
            return []
        return [
            {"name": f"{tag}-{i}", "type_line": "Creature — Human", "mana_cost": "{2}",
             "cmc": 2, "color_identity": [], "legalities": {"commander": "legal"},
             "edhrec_rank": i}
            for i in range(self.pool)
        ]


class _Profile:
    name = "Test Commander"
    color_identity = ["R"]
    color_id_str = "R"
    is_colorless = False
    mana_value = 3
    card = {"name": "Test Commander", "type_line": "Legendary Creature — Goblin",
            "mana_cost": "{2}{R}", "oracle_text": ""}


def _builder(stub):
    b = DeckBuilder(stub)
    b._deck, b._names = [], set()
    b._lifts, b._owned, b._owned_cards = {}, set(), []
    b._curve_target = {}
    b._bracket_filter = deck_builder.BracketFilter(3)
    assert not b._strict(), "fixture is wrong: these tests must exercise the Scryfall path"
    return b


def _dist(builder) -> dict[str, int]:
    out: dict[str, int] = {}
    for card in builder._deck:
        tag = card["name"].split("-")[0]
        out[tag] = out.get(tag, 0) + 1
    return out


# ── the regression ───────────────────────────────────────────────────────────────

def test_theme_slots_are_split_across_active_themes():
    """THE BUG. One theme must not eat the whole package.

    Weighted toward the LEAD theme rather than even — see `_theme_slot_split`, where
    the even split was measured against the benchmark and cost multi-theme commanders
    1.65 mean synergy.
    """
    b = _builder(_ThemeStub())
    added = b._fetch_theme_synergy_list(
        _Profile(), ["tribal_goblins", "tokens", "tribal_dragons"], 20)
    assert added == 20
    assert _dist(b) == {"GOB": 14, "TOK": 3, "DRG": 3}


def test_secondary_themes_always_get_representation():
    """The point of the fix: themes 2 and 3 must be REACHABLE, not merely smaller."""
    b = _builder(_ThemeStub())
    b._fetch_theme_synergy_list(
        _Profile(), ["tribal_goblins", "tokens", "tribal_dragons"], 20)
    d = _dist(b)
    assert d.get("TOK", 0) >= 1 and d.get("DRG", 0) >= 1


def test_two_themes_are_lead_weighted():
    b = _builder(_ThemeStub())
    b._fetch_theme_synergy_list(_Profile(), ["tribal_goblins", "tokens"], 10)
    assert _dist(b) == {"GOB": 7, "TOK": 3}


def test_a_single_theme_still_takes_the_whole_package():
    b = _builder(_ThemeStub())
    assert b._fetch_theme_synergy_list(_Profile(), ["tribal_goblins"], 20) == 20
    assert _dist(b) == {"GOB": 20}


# ── running dry ──────────────────────────────────────────────────────────────────

def test_a_dry_theme_does_not_waste_its_slots():
    """A theme with no results leaves slots unspent; the sweep redistributes them rather
    than shipping a short package."""
    b = _builder(_ThemeStub(dry={"GOB"}))
    added = b._fetch_theme_synergy_list(
        _Profile(), ["tribal_goblins", "tokens", "tribal_dragons"], 20)
    assert added == 20
    assert "GOB" not in _dist(b)
    assert sum(_dist(b).values()) == 20


@pytest.mark.parametrize("want,n,expected", [
    (20, 1, [20]), (20, 2, [14, 6]), (20, 3, [14, 3, 3]),
    (10, 3, [7, 2, 1]), (3, 3, [1, 1, 1]), (2, 3, [1, 1, 0]),
    (0, 2, []), (1, 3, [1, 0, 0]),
])
def test_slot_split_arithmetic(want, n, expected):
    """Always sums to `want`, never negative, never starves a theme it can feed."""
    got = deck_builder._theme_slot_split(want, n)
    assert got == expected
    assert sum(got) == max(0, want)


def test_a_short_pool_returns_what_exists_without_looping_forever():
    b = _builder(_ThemeStub(pool=3))
    added = b._fetch_theme_synergy_list(
        _Profile(), ["tribal_goblins", "tokens", "tribal_dragons"], 20)
    assert added == 9                      # 3 themes x 3 available
    assert len(b._deck) == 9


def test_every_theme_dry_adds_nothing():
    b = _builder(_ThemeStub(dry={"GOB", "TOK", "DRG"}))
    assert b._fetch_theme_synergy_list(
        _Profile(), ["tribal_goblins", "tokens", "tribal_dragons"], 20) == 0


# ── bounds ───────────────────────────────────────────────────────────────────────

def test_only_the_first_three_themes_are_active():
    b = _builder(_ThemeStub())
    b._fetch_theme_synergy_list(
        _Profile(), ["tribal_goblins", "tokens", "tribal_dragons", "tribal_elves"], 12)
    assert "ELF" not in _dist(b)


def test_never_exceeds_want():
    b = _builder(_ThemeStub())
    assert b._fetch_theme_synergy_list(_Profile(), ["tribal_goblins", "tokens"], 7) == 7
    assert len(b._deck) == 7


def test_no_duplicate_cards_across_the_sweep():
    """The dry-theme sweep re-queries themes already drafted from; `_add` must dedupe."""
    b = _builder(_ThemeStub(dry={"DRG"}))
    b._fetch_theme_synergy_list(
        _Profile(), ["tribal_goblins", "tokens", "tribal_dragons"], 20)
    names = [c["name"] for c in b._deck]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("want", [0, -1])
def test_non_positive_want_adds_nothing(want):
    b = _builder(_ThemeStub())
    assert b._fetch_theme_synergy_list(_Profile(), ["tribal_goblins"], want) == 0
