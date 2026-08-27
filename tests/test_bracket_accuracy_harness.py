"""Regression coverage for scripts/bracket_accuracy.py's testable, offline pure logic.

`bracket_accuracy.py`'s own docstring marks the whole script "NOT CI-SAFE" because
`main()` needs `data/cards_slim.json` and a live semantics store -- but `real_combo_lookup`
is pure/mockable and was left with zero coverage when it was introduced, which is exactly
how its own bug (an un-throttled live request on a cache-file corner case) could have
shipped unnoticed. `scripts/` isn't a package pytest collects (see pytest.ini), so this
file inserts it onto `sys.path` itself, the same way `bracket_b5_gate.py` already does to
import from `bracket_accuracy` at runtime.

(The row-level "does this deck have a real combo" question used to be answered here by a
`has_combo_gate(reasons)` text-scrape over `BracketEstimate.reasons` -- it under-reported
for any deck that already had Game Changers, since bracket.py only appends a combo reason
when the gate actually changes the floor. That's now `BracketEstimate.has_verified_combo`,
computed structurally in `estimate_bracket` instead of grepped from prose; its tests live
in tests/engine/test_bracket.py alongside the rest of that dataclass's contract.)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bracket_accuracy  # noqa: E402


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
