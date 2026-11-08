"""Pod fit (D4): the four checks, their edges, and the sentences a pod hears."""
from __future__ import annotations

import pytest

from mythgauntlet.ratings.pod_fit import Seat, check


def _seat(name, bracket=2, denial="Low", pace="Typical", inev="Low", **kw):
    return Seat(name, bracket, denial, pace, inev, **kw)


def _status(fit, key):
    return next(c for c in fit.checks if c.key == key).status


def test_a_matched_pod_is_a_good_fit():
    fit = check([_seat("A"), _seat("B"), _seat("C", bracket=3), _seat("D")])
    assert fit.fun and fit.summary.startswith("A good fit")
    assert all(c.status == "ok" for c in fit.checks)


def test_power_gap_of_two_fails_and_names_both_decks():
    fit = check([_seat("Krenko", bracket=4), _seat("B"), _seat("C"), _seat("D")])
    assert not fit.fun and _status(fit, "power") == "fail"
    assert "Krenko measures Bracket 4 and B Bracket 2" in fit.checks[0].text


def test_pace_fast_with_long_fails_one_fast_warns():
    assert _status(check([_seat("A", pace="Fast"), _seat("B", pace="Long"), _seat("C")]),
                   "pace") == "fail"
    lone = check([_seat("A", pace="Fast"), _seat("B"), _seat("C"), _seat("D")])
    assert _status(lone, "pace") == "warn" and lone.fun


def test_one_heavy_denial_deck_at_a_quiet_table_fails():
    """The design's motivating case: a 'Bracket 2' counterspell wall among decks with none."""
    fit = check([_seat("Control", denial="High", denial_reasons=["11 counterspells"]),
                 _seat("B"), _seat("C"), _seat("D")])
    c = next(c for c in fit.checks if c.key == "denial")
    assert c.status == "fail" and "Control runs heavy denial (11 counterspells)" in c.text
    assert _status(check([_seat("A", denial="Medium"), _seat("B"), _seat("C")]), "denial") == "warn"
    # a table where everyone denies is a control mirror, not a mismatch
    assert _status(check([_seat(x, denial="High") for x in "ABCD"]), "denial") == "ok"


def test_inevitability_depends_on_the_table():
    two = [_seat("A", inev="High"), _seat("B", inev="High"), _seat("C"), _seat("D")]
    assert _status(check(two), "inevitability") == "fail"
    assert _status(check([_seat("A", inev="High"), _seat("B"), _seat("C")]),
                   "inevitability") == "warn"
    cedh = [_seat(x, bracket=5, inev="High") for x in "ABCD"]
    assert _status(check(cedh), "inevitability") == "ok"


def test_summary_counts_fails_and_warnings():
    fit = check([_seat("A", bracket=4, pace="Fast"), _seat("B"), _seat("C"), _seat("D")])
    assert fit.summary == "Likely a lopsided game: 1 mismatch and 1 thing to mention."


def test_a_pod_needs_two_decks():
    with pytest.raises(ValueError):
        check([_seat("A")])


def test_inevitability_warning_quotes_the_reason_without_nesting_parentheses():
    seat = _seat("Oloro", inev="High", inevitability_reasons=[
        "a combo wins before damage in 72% of games (most often A + B)"])
    c = next(c for c in check([seat, _seat("B"), _seat("C")]).checks if c.key == "inevitability")
    assert c.text == ("Oloro wins the same way most games: a combo wins before damage in 72% of "
                      "games (most often A + B). Tell the table what to watch for.")
