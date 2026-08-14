"""Tests for the strict collection-building contract.

A review found this surface had NO regression net at all: zero test hits across the suite
for `_resolve_card_source`, `source_fallback`, `padded_with_basics`, `_POOL_ROLE`,
`_fetch_role` or `_build_lands`. The three claims most likely to regress silently were the
three with nothing pinning them:

  * `use_collection=True` derives to prefer_collection, NOT strict. Redefining that
    boolean would narrow the decks of everyone already using it.
  * an empty owned pool falls back to Scryfall rather than shipping 99 basic lands.
  * an exhausted pool records `padded_with_basics` instead of padding silently.

Every test here was mutation-checked: the behaviour it claims to pin was broken in a
scratch copy and the test was confirmed to fail. No `data/` directory, no network.
"""
import pytest

import collection_pool
import deck_builder
from deck_builder import (DeckBuilder, SOURCE_SCRYFALL, SOURCE_PREFER, SOURCE_COLLECTION)
from commander_analysis import build_commander_profile


class _NoSearch(AssertionError):
    """Raised if strict mode reaches for Scryfall search. Failing loudly is the point."""


class _DeadClient:
    """Resolution is allowed (owned names -> card data); SEARCH is not."""

    def __init__(self, owned=()):
        self._owned = list(owned)

    def get_cards_collection(self, names):
        return {c["name"]: c for c in self._owned}

    def search_cards_paged(self, query, max_results=60):
        raise _NoSearch(query)

    def search_cards(self, query):
        # Basic lands are fetched by exact name and ARE allowed — every deck may play
        # unlimited basics regardless of what the collection holds.
        name = query.strip('!"')
        if name in ("Mountain", "Swamp", "Plains", "Island", "Forest", "Wastes"):
            return {"data": [{"name": name, "type_line": f"Basic Land — {name}",
                              "mana_cost": "", "cmc": 0.0, "color_identity": [],
                              "oracle_text": "", "legalities": {"commander": "legal"}}]}
        raise _NoSearch(query)


def _spell(name, mv=3, rank=100, text="Draw two cards.", type_line="Sorcery", ci=("B",)):
    return {"name": name, "cmc": mv, "mana_cost": "{2}{B}", "type_line": type_line,
            "oracle_text": text, "color_identity": list(ci), "edhrec_rank": rank,
            "legalities": {"commander": "legal"}}


COMMANDER = {"name": "Test Commander", "cmc": 4, "mana_cost": "{2}{B}{R}",
             "type_line": "Legendary Creature — Zombie Dragon", "color_identity": ["B", "R"],
             "oracle_text": "Flying", "edhrec_rank": 500,
             "legalities": {"commander": "legal"}}


def _profile():
    return build_commander_profile(COMMANDER)


def _strict_builder(owned):
    b = DeckBuilder(_DeadClient(owned))
    b._deck, b._names = [], set()
    b._card_source = SOURCE_COLLECTION
    b._owned = {c["name"].casefold() for c in owned}
    b._owned_cards = list(owned)
    b._pool = collection_pool.build_pool(
        {"name": COMMANDER["name"], "color_identity": ["B", "R"]}, owned)
    return b


# ── _resolve_card_source: the back-compat rule ───────────────────────────────────

@pytest.mark.parametrize("card_source, use_collection, expected", [
    ("",                  False, SOURCE_SCRYFALL),
    ("",                  True,  SOURCE_PREFER),      # the load-bearing one
    ("scryfall",          True,  SOURCE_SCRYFALL),    # explicit beats the boolean
    ("prefer_collection", False, SOURCE_PREFER),
    ("collection",        False, SOURCE_COLLECTION),
    ("bogus",             True,  SOURCE_PREFER),      # unknown falls back, never raises
    ("bogus",             False, SOURCE_SCRYFALL),
    ("  COLLECTION  ",    False, SOURCE_COLLECTION),  # trimmed and lowercased
])
def test_resolve_card_source_back_compat(card_source, use_collection, expected):
    """use_collection=True has ALWAYS meant PREFER, never "owned only". Redefining it
    would silently narrow the decks of every caller predating the card_source field."""
    import server
    assert server._resolve_card_source(card_source, use_collection) == expected


# ── source_fallback: an empty owned pool must not ship 99 basics ─────────────────

def test_empty_owned_pool_falls_back_to_scryfall_and_says_so():
    b = DeckBuilder(_DeadClient())
    with pytest.raises(_NoSearch):
        # Falling back means it now SEARCHES — which the dead client refuses. That the
        # search is attempted at all is the proof the fallback fired.
        b.build(_profile(), card_source=SOURCE_COLLECTION, bracket=3, owned=set())
    assert b.source_fallback
    assert "colour identity" in b.source_fallback or "collection" in b.source_fallback.lower()


def test_source_fallback_is_readable_before_build_runs():
    """It is documented alongside builder.shortfall, so a caller may probe it the same
    way. shortfall was initialised in __init__ and source_fallback was not, which made
    the asymmetric one an AttributeError waiting to happen."""
    assert DeckBuilder(_DeadClient()).source_fallback == ""


def test_a_healthy_pool_sets_no_fallback():
    owned = [_spell(f"Card {i}", rank=i) for i in range(60)]
    b = _strict_builder(owned)
    b._fetch_role(_profile(), "card_draw", 5)
    assert b.source_fallback == ""


# ── _POOL_ROLE: a role with no mapping degrades, it does not crash ───────────────

def test_an_unmapped_role_is_skipped_and_recorded_not_raised():
    """ROLE_QUERIES has grown a role before (finisher). An unguarded subscript would
    turn the next such addition into a KeyError inside the build thread."""
    b = _strict_builder([_spell("A")])
    assert b._fetch_role(_profile(), "not_a_role", 4) == 0
    assert b.shortfall["not_a_role"] == 4


def test_every_role_query_has_a_pool_role_mapping():
    """The invariant that keeps the strict and Scryfall branches drafting the same roles.
    A role added to one and not the other silently empties that slot in strict mode."""
    assert set(deck_builder.ROLE_QUERIES) == set(deck_builder._POOL_ROLE)


# ── _fetch_role in strict mode ───────────────────────────────────────────────────

def test_strict_role_fetch_never_searches():
    owned = [_spell(f"Draw {i}", rank=i) for i in range(10)]
    b = _strict_builder(owned)
    assert b._fetch_role(_profile(), "card_draw", 4) == 4   # would raise _NoSearch


def test_strict_role_fetch_records_only_the_real_deficit():
    owned = [_spell(f"Draw {i}", rank=i) for i in range(3)]
    b = _strict_builder(owned)
    assert b._fetch_role(_profile(), "card_draw", 10) == 3
    assert b.shortfall["card_draw"] == 7


def test_strict_role_fetch_records_nothing_when_covered():
    owned = [_spell(f"Draw {i}", rank=i) for i in range(10)]
    b = _strict_builder(owned)
    b._fetch_role(_profile(), "card_draw", 4)
    assert "card_draw" not in b.shortfall


# ── _build_lands in strict mode ──────────────────────────────────────────────────

def _land(name, text, tl="Land", ci=("B",)):
    return {"name": name, "type_line": tl, "oracle_text": text, "mana_cost": "",
            "cmc": 0.0, "color_identity": list(ci), "edhrec_rank": 50,
            "legalities": {"commander": "legal"}}


FETCH = _land("Bloodstained Mire",
              "{T}, Pay 1 life, Sacrifice this land: Search your library for a Swamp or "
              "Mountain card, put it onto the battlefield, then shuffle.", ci=())
TOWER = _land("Command Tower",
              "{T}: Add one mana of any color in your commander's color identity.", ci=())


def test_strict_lands_honour_the_bracket_land_power_cap():
    """Without this a Bracket 1 collection deck kept every fetch and shock the user
    owned, while the same bracket built from Scryfall excluded them — the same bracket
    meaning different things depending on card source."""
    b1 = _strict_builder([FETCH, TOWER])
    b1._bracket_filter = deck_builder.BracketFilter(1)
    b1._build_lands(_profile(), 10)
    names = {c["name"] for c in b1._deck}
    assert "Command Tower" in names
    assert "Bloodstained Mire" not in names        # tier 'fetch' is not allowed at B1

    b3 = _strict_builder([FETCH, TOWER])
    b3._bracket_filter = deck_builder.BracketFilter(3)
    b3._build_lands(_profile(), 10)
    assert "Bloodstained Mire" in {c["name"] for c in b3._deck}   # allowed at B3


def test_strict_lands_fill_the_remainder_with_basics():
    """Basics are always available regardless of what the collection holds, so the land
    count is met even when the owned nonbasics run out."""
    b = _strict_builder([TOWER])
    added = b._build_lands(_profile(), 12)
    assert added == 12
    assert sum(1 for c in b._deck if "Basic Land" in c["type_line"]) == 11


# ── padded_with_basics: an exhausted pool must not pad silently ──────────────────

def test_an_exhausted_pool_records_padded_with_basics():
    """A small collection used to yield a deck that was mostly Mountains while shortfall
    named only the roles — half-keeping build()'s promise to report what it could not
    cover."""
    owned = [_spell(f"Card {i}", rank=i) for i in range(6)]
    b = DeckBuilder(_DeadClient(owned))
    deck = b.build(_profile(), card_source=SOURCE_COLLECTION, bracket=3,
                   owned={c["name"].casefold() for c in owned})
    assert len(deck) == 99
    assert b.shortfall.get("padded_with_basics", 0) > 0


def test_a_covering_pool_records_no_padding():
    owned = ([_spell(f"Card {i}", rank=i) for i in range(120)]
             + [_land(f"Land {i}", "{T}: Add {B}.") for i in range(20)])
    b = DeckBuilder(_DeadClient(owned))
    b.build(_profile(), card_source=SOURCE_COLLECTION, bracket=3,
            owned={c["name"].casefold() for c in owned})
    assert "padded_with_basics" not in b.shortfall


# ── unrecognised themes are recorded, not silently dropped ───────────────────────

def test_an_unknown_theme_mixed_with_a_known_one_is_recorded():
    """['tribal_dragons', 'typo_theme'] used to yield an all-dragons package with nothing
    telling the caller the second theme never applied."""
    owned = [_spell(f"Card {i}", rank=i) for i in range(20)]
    b = _strict_builder(owned)
    b._fetch_theme_synergy_list(_profile(), ["tribal_dragons", "typo_theme"], 4)
    assert b.shortfall.get("unrecognised_themes") == 1
