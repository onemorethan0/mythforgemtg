"""Tests for DeckBuilder's curve-aware flexible fill.

The builder drafts every slot EDHREC-best-first, a popularity ordering with no opinion
about mana cost, so a commander whose colours are rich in expensive staples came out
top-heavy. _draft_curve_aware biases only the FLEXIBLE fills (goodstuff, creature floor)
toward buckets that are short of target.

Measured on a real strict build from the Rakdos collection, total deviation from the
target curve fell from 11 to 2, with buckets 2/4/5/6/7 landing exactly.

No network: every test drives the helper directly or with a stub client.
"""
import deck_builder
from deck_builder import DeckBuilder


class _DeadClient:
    """Strict mode must never search; these tests never want a network call either."""
    def get_cards_collection(self, names):
        return {}

    def search_cards_paged(self, query, max_results=60):
        raise AssertionError("no search expected in these tests")

    def search_cards(self, query):
        raise AssertionError("no search expected in these tests")


def _card(name, mv, rank):
    return {"name": name, "cmc": mv, "type_line": "Creature — Human",
            "color_identity": [], "legalities": {"commander": "legal"},
            "edhrec_rank": rank}


def _builder(target):
    b = DeckBuilder(_DeadClient())
    b._deck, b._names = [], set()
    b._curve_target = target
    return b


def test_fills_under_full_buckets_before_better_ranked_cards():
    """A rank-1 six-drop loses to a rank-500 two-drop while the two-slot is short."""
    b = _builder({2: 2, 6: 0})
    candidates = [_card("Great Six", 6, 1), _card("Great Six B", 6, 2),
                  _card("Ok Two", 2, 500), _card("Ok Two B", 2, 501)]
    added = b._draft_curve_aware(candidates, 2)
    assert added == 2
    assert [c["name"] for c in b._deck] == ["Ok Two", "Ok Two B"]


def test_does_not_overshoot_a_short_bucket():
    """The bias is re-evaluated per card. A one-shot partition drafted every card from
    the same short bucket and overshot it by more than the gap it closed."""
    b = _builder({2: 1, 3: 1, 4: 1})
    candidates = ([_card(f"Two{i}", 2, 10 + i) for i in range(5)]
                  + [_card(f"Three{i}", 3, 20 + i) for i in range(5)]
                  + [_card(f"Four{i}", 4, 30 + i) for i in range(5)])
    b._draft_curve_aware(candidates, 3)
    got = sorted(int(c["cmc"]) for c in b._deck)
    assert got == [2, 3, 4], got


def test_falls_back_to_edhrec_order_when_every_bucket_is_met():
    b = _builder({2: 0, 6: 0})           # nothing is short
    candidates = [_card("Best", 6, 1), _card("Worse", 2, 900)]
    b._draft_curve_aware(candidates, 1)
    assert [c["name"] for c in b._deck] == ["Best"]


def test_no_target_means_plain_edhrec_order():
    """With no curve target the helper must behave exactly like the old fill."""
    b = _builder({})
    candidates = [_card("First", 7, 1), _card("Second", 1, 2)]
    added = b._draft_curve_aware(candidates, 2)
    assert added == 2
    assert [c["name"] for c in b._deck] == ["First", "Second"]


def test_respects_want_and_reports_what_it_added():
    b = _builder({1: 5})
    candidates = [_card(f"C{i}", 1, i) for i in range(10)]
    assert b._draft_curve_aware(candidates, 3) == 3
    assert len(b._deck) == 3


def test_want_zero_or_negative_is_a_noop():
    b = _builder({1: 5})
    assert b._draft_curve_aware([_card("X", 1, 1)], 0) == 0
    assert b._draft_curve_aware([_card("X", 1, 1)], -4) == 0
    assert b._deck == []


def test_seven_plus_share_one_bucket():
    """Bucket 7 is the 7+ bucket, so a nine-drop satisfies a shortfall at 7."""
    b = _builder({7: 1, 2: 0})
    candidates = [_card("Two", 2, 1), _card("Nine", 9, 900)]
    b._draft_curve_aware(candidates, 1)
    assert [c["name"] for c in b._deck] == ["Nine"]


def test_existing_deck_contents_seed_the_histogram():
    """Cards already drafted by the ROLE fills count toward the curve — the flexible
    fill tops up what the roles left short, it does not start from zero."""
    b = _builder({2: 1, 5: 1})
    b._deck = [_card("Already A Two", 2, 1)]
    b._names = {"Already A Two"}
    candidates = [_card("Another Two", 2, 2), _card("A Five", 5, 900)]
    b._draft_curve_aware(candidates, 1)
    assert [c["name"] for c in b._deck][-1] == "A Five"


def test_lands_in_the_deck_do_not_count_toward_the_curve():
    b = _builder({2: 1})
    b._deck = [{"name": "Mountain", "cmc": 0, "type_line": "Basic Land — Mountain"}]
    b._names = {"Mountain"}
    candidates = [_card("Six", 6, 1), _card("Two", 2, 900)]
    b._draft_curve_aware(candidates, 1)
    assert [c["name"] for c in b._deck][-1] == "Two"


def test_quality_block_is_attached_to_every_deck():
    """compute_stats carries it, so generate/rebuild/retheme/import all get it."""
    commander = {"name": "Cmdr", "mana_cost": "{5}{B}{R}", "cmc": 7,
                 "color_identity": ["B", "R"], "type_line": "Legendary Creature"}
    deck = [_card("A", 2, 1), _card("B", 3, 2),
            {"name": "Swamp", "type_line": "Basic Land — Swamp",
             "produced_mana": ["B"], "quantity": 20, "cmc": 0}]
    q = deck_builder.compute_stats(commander, deck)["quality"]
    assert q["curve"]["verdict"] in ("ok", "top-heavy", "too-flat")
    assert q["colors"]["sources"]["B"] == 20        # quantity-weighted
    assert "R" in q["colors"]["pips"]               # the commander's pips count


def test_quality_block_never_breaks_a_build():
    """It is advisory. A malformed card must not take the whole build down with it."""
    stats = deck_builder.compute_stats({"name": "C"}, [{"name": "junk"}])
    assert "quality" in stats
    assert stats["total_cards"] == 2
