"""Regression coverage for scripts/bracket_accuracy.py's testable, offline pure logic.

`bracket_accuracy.py`'s own docstring marks the whole script "NOT CI-SAFE" because
`main()` needs `data/cards_slim.json` and a live semantics store -- but `has_combo_gate`
and `real_combo_lookup` are pure/mockable and were left with zero coverage when they were
introduced/fixed, which is exactly how their own bugs (a substring collision with the
storm/go-off heuristic; an un-throttled live request on a cache-file corner case) could
have shipped unnoticed. `scripts/` isn't a package pytest collects (see pytest.ini), so
this file inserts it onto `sys.path` itself, the same way `bracket_b5_gate.py` already
does to import from `bracket_accuracy` at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bracket_accuracy  # noqa: E402


# --- has_combo_gate: real combo vs. the unrelated storm/go-off heuristic -----------

def test_has_combo_gate_true_for_the_ungraded_real_combo_reason():
    reasons = ["0 Game Changers -> Brackets 1-2",
              "1 in-deck game-ending combo(s) (1 two-card) -> min Bracket 3"]
    assert bracket_accuracy.has_combo_gate(reasons) is True


def test_has_combo_gate_true_for_the_graded_real_combo_reason():
    # spellbook.ComboAssessment.gate_reason()'s actual shape.
    reasons = ["0 Game Changers -> Brackets 1-2",
              "1 in-deck game-ending combo(s) (1 fast 2-card terminal) -> min Bracket 3"]
    assert bracket_accuracy.has_combo_gate(reasons) is True


def test_has_combo_gate_false_for_the_go_off_heuristic_alone():
    """The bug this pins: the go-off reason ALSO ends in "-> min Bracket 3" but is an
    unverified nut-draw heuristic, not a Spellbook-confirmed combo, and must not be
    counted as "impossible under the rules" by a B1/B2 rule-consistency filter."""
    reasons = ["0 Game Changers -> Brackets 1-2",
              "storm/spellslinger go-off (nut-draw kill) -> min Bracket 3"]
    assert bracket_accuracy.has_combo_gate(reasons) is False


def test_has_combo_gate_false_with_no_qualifying_reason():
    reasons = ["0 Game Changers -> Brackets 1-2"]
    assert bracket_accuracy.has_combo_gate(reasons) is False


# --- real_combo_lookup: cache-aware politeness throttle ----------------------------

class _StubCard:
    def __init__(self, name):
        self.name = name


class _StubResolved:
    def __init__(self, card_names, commander_names):
        self.cards = [(_StubCard(n), 1) for n in card_names]
        self.commanders = [_StubCard(n) for n in commander_names]


def _patch_spellbook(monkeypatch, *, cached, combo_report=None, raises=None):
    from mythgauntlet.data import spellbook

    monkeypatch.setattr(spellbook, "is_cached", lambda *a, **kw: cached)

    def _fake_find_combos(*_a, **_kw):
        if raises is not None:
            raise raises
        return combo_report
    monkeypatch.setattr(spellbook, "find_combos", _fake_find_combos)


def test_real_combo_lookup_skips_the_throttle_on_a_cache_hit(monkeypatch):
    slept = []
    monkeypatch.setattr(bracket_accuracy.time, "sleep", lambda s: slept.append(s))
    _patch_spellbook(monkeypatch, cached=True, combo_report="report")

    resolved = _StubResolved(["Sol Ring"], ["Selvala, Heart of the Wilds"])
    combo_report, failed = bracket_accuracy.real_combo_lookup(resolved, "test")

    assert combo_report == "report"
    assert failed is False
    assert slept == [], "a cache hit must not pay the politeness throttle"


def test_real_combo_lookup_throttles_on_a_cache_miss(monkeypatch):
    slept = []
    monkeypatch.setattr(bracket_accuracy.time, "sleep", lambda s: slept.append(s))
    _patch_spellbook(monkeypatch, cached=False, combo_report="report")

    resolved = _StubResolved(["Sol Ring"], ["Selvala, Heart of the Wilds"])
    combo_report, failed = bracket_accuracy.real_combo_lookup(resolved, "test")

    assert combo_report == "report"
    assert failed is False
    assert slept == [0.2], "a live request must pay the default politeness throttle"


def test_real_combo_lookup_still_throttles_after_a_failed_lookup(monkeypatch):
    """A cache miss that then fails over the network is STILL a live request that just
    hit an error -- it must not skip the throttle any more than a successful one would."""
    import requests

    slept = []
    monkeypatch.setattr(bracket_accuracy.time, "sleep", lambda s: slept.append(s))
    _patch_spellbook(monkeypatch, cached=False, raises=requests.RequestException("boom"))

    resolved = _StubResolved(["Sol Ring"], ["Selvala, Heart of the Wilds"])
    combo_report, failed = bracket_accuracy.real_combo_lookup(resolved, "test")

    assert combo_report is None
    assert failed is True
    assert slept == [0.2]
