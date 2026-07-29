"""Pip-to-source assignment must be exact (augmenting paths), not greedy."""

from mythgauntlet.model.card import ManaCost
from mythgauntlet.sim.tier0 import _can_pay, _Source


def _sources(*color_sets):
    return [_Source(frozenset(cs)) for cs in color_sets]


def test_flexible_source_reassigned_when_needed():
    # Greedy would pay {W} with the W/U source and strand {U}. Matching must reassign.
    sources = _sources({"W", "U"}, {"W", "G"})
    payment = _can_pay(sources, ManaCost.parse("{W}{U}"))
    assert payment is not None
    assert sorted(payment) == [0, 1]


def test_unpayable_color_is_rejected():
    sources = _sources({"B"}, {"B"})
    assert _can_pay(sources, ManaCost.parse("{G}")) is None


def test_generic_paid_from_leftovers():
    sources = _sources({"G"}, {"B"}, {"B"})
    payment = _can_pay(sources, ManaCost.parse("{2}{G}"))
    assert payment is not None and len(payment) == 3


def test_insufficient_total_mana():
    sources = _sources({"G"}, {"G"})
    assert _can_pay(sources, ManaCost.parse("{2}{G}")) is None


def test_tapped_sources_dont_count():
    sources = _sources({"G"}, {"G"})
    sources[0].ready = False
    assert _can_pay(sources, ManaCost.parse("{G}{G}")) is None
    assert _can_pay(sources, ManaCost.parse("{G}")) == [1]


def test_hybrid_pip_uses_either_color():
    sources = _sources({"U"})
    assert _can_pay(sources, ManaCost.parse("{G/U}")) == [0]
