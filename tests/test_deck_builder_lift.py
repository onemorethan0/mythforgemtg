"""DeckBuilder's commander-conditioned candidate ordering (`_lift_sorted`).

The builder drafts every role window EDHREC-best-first — a GLOBAL popularity ordering with
no opinion about who is commanding the deck, which is why two decks in the same colours
draft so similarly. `_lift_sorted` reorders that window by this commander's EDHREC lift.

Verified live before these tests were written: the Sultai `card_draw` window is identical
for every Sultai commander (Mind Stone, Solemn Simulacrum, Skullclamp, Rhystic Study...),
and under lift it becomes Grim Haruspex / Beast Whisperer / Guardian Project for Kadena
(morph, creature-based draw), Mulldrifter / The Gitrog Monster / Baleful Strix for
Muldrotha (recursion), Nezahal / Veil of Summer / Windfall for Tasigur (spells).

No network: `_lifts` is set directly.
"""

import deck_builder
from deck_builder import DeckBuilder


class _DeadClient:
    """These tests never want a network call."""
    def get_cards_collection(self, names):
        return {}

    def search_cards_paged(self, query, max_results=60):
        raise AssertionError("no search expected in these tests")

    def search_cards(self, query):
        raise AssertionError("no search expected in these tests")


def _card(name, rank=None):
    return {"name": name, "cmc": 2, "type_line": "Creature — Human",
            "color_identity": [], "legalities": {"commander": "legal"},
            "edhrec_rank": rank}


def _builder(lifts=None, owned=None):
    b = DeckBuilder(_DeadClient())
    b._deck, b._names = [], set()
    b._lifts = lifts or {}
    b._owned = owned or set()
    b._owned_cards = []
    return b


def test_lift_sorted_is_a_noop_without_a_lift_map():
    """No EDHREC page / failed fetch / kill switch: the build must be byte-for-byte
    unchanged, so an empty map returns the SAME list object contents in order."""
    b = _builder()
    cands = [_card("A", 1), _card("B", 2), _card("C", 3)]
    assert [c["name"] for c in b._lift_sorted(cands)] == ["A", "B", "C"]


def test_lift_sorted_fronts_the_commanders_cards():
    b = _builder({"synergy piece": 0.8, "staple": -0.1})
    cands = [_card("Staple", 1), _card("Unmeasured", 2), _card("Synergy Piece", 900)]
    # Popularity would lead with Staple; lift leads with the commander's own card and
    # demotes the anti-synergistic staple below the unmeasured one.
    assert [c["name"] for c in b._lift_sorted(cands)] == [
        "Synergy Piece", "Unmeasured", "Staple",
    ]


def test_lift_composes_with_prefer_owned_and_c4_still_wins():
    """The C4 contract (owned cards get first claim) must survive lift ordering.

    Both passes are stable partitions and lift runs FIRST, so the result is
    owned-in-lift-order followed by unowned-in-lift-order — never an unowned card ahead
    of an owned one.
    """
    b = _builder(
        lifts={"owned low": 0.1, "owned high": 0.9, "unowned high": 0.95},
        owned={"owned low", "owned high"},
    )
    cands = [_card("Unowned High", 1), _card("Owned Low", 2), _card("Owned High", 3)]
    out = [c["name"] for c in b._prefer_owned(b._lift_sorted(cands))]
    # Unowned High has the highest lift of all and still sorts behind both owned cards.
    assert out == ["Owned High", "Owned Low", "Unowned High"]


def test_lift_ordering_differs_between_two_commanders_in_the_same_colours():
    """The whole point: same candidate window, different commander, different order."""
    window = [_card("Generic Staple", 1), _card("Morph Payoff", 800),
              _card("Recursion Payoff", 900)]
    kadena = _builder({"morph payoff": 0.9, "generic staple": -0.1})
    muldrotha = _builder({"recursion payoff": 0.8, "generic staple": -0.1})
    assert [c["name"] for c in kadena._lift_sorted(window)][0] == "Morph Payoff"
    assert [c["name"] for c in muldrotha._lift_sorted(window)][0] == "Recursion Payoff"


def test_build_tolerates_a_dead_edhrec(monkeypatch):
    """`build()` fetches lift once; an exception there must not escape into the build."""
    def boom(*a, **kw):
        raise OSError("EDHREC down")

    monkeypatch.setattr(deck_builder.edhrec_lift.requests, "get", boom)
    monkeypatch.setenv("MYTHFORGE_EDHREC_LIFT", "on")
    assert deck_builder.edhrec_lift.lift_map("Nobody At All") == {}
