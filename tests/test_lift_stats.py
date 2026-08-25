"""Deck-level lift statistics. Written from docs/SPEC_lift_stats.md.

Offline: `lifts` is always supplied directly, so no EDHREC page is ever fetched.
"""

from __future__ import annotations

import pytest

import lift_stats
from lift_stats import LiftStats


def _deck(*names: str) -> list[dict]:
    return [{"name": n, "type_line": "Creature — Human"} for n in names]


def _page(**pairs: float) -> dict[str, float]:
    """A commander page as {normalized name: lift}."""
    return {k.replace("_", " "): v for k, v in pairs.items()}


# ── nothing measurable ──────────────────────────────────────────────────────────

def test_returns_none_without_a_page():
    assert lift_stats.lift_stats(_deck("A", "B"), {}) is None


def test_returns_none_when_no_card_is_on_the_page():
    assert lift_stats.lift_stats(_deck("Nobody"), {"someone else": 0.5}) is None


def test_returns_none_for_an_all_basics_deck():
    """Basics are never on a commander page; a deck of them has nothing to measure."""
    basics = [{"name": "Mountain", "type_line": "Basic Land — Mountain"}]
    assert lift_stats.lift_stats(basics, {"mountain": 0.1}) is None


# ── counting ────────────────────────────────────────────────────────────────────

def test_basics_are_excluded_from_the_denominator():
    """Counting basics would only deflate coverage — they can never be measured."""
    deck = _deck("Known") + [
        {"name": "Island", "type_line": "Basic Land — Island"},
        {"name": "Forest", "type_line": "Basic Land — Forest"},
    ]
    s = lift_stats.lift_stats(deck, {"known": 0.5})
    assert (s.total, s.measured, s.coverage) == (1, 1, 1.0)


def test_duplicates_are_counted_once_and_quantity_is_ignored():
    """A second copy says nothing about how off-meta the deck is."""
    deck = _deck("Same", "Same")
    deck[0]["quantity"] = 9
    s = lift_stats.lift_stats(deck, {"same": 0.5})
    assert (s.total, s.measured) == (1, 1)


def test_nonbasic_lands_still_count():
    """Command Tower and friends ARE on commander pages (utilitylands / lands)."""
    deck = [{"name": "Command Tower", "type_line": "Land"}]
    s = lift_stats.lift_stats(deck, {"command tower": 0.02})
    assert s.measured == 1


def test_a_card_without_a_name_is_skipped():
    s = lift_stats.lift_stats([{}, {"name": "Known", "type_line": ""}], {"known": 0.4})
    assert s.total == 1


# ── the figures ─────────────────────────────────────────────────────────────────

def test_synergy_and_staple_percentages():
    page = {"a": 0.40, "b": 0.20, "c": -0.10, "d": 0.00}
    s = lift_stats.lift_stats(_deck("A", "B", "C", "D"), page)
    assert s.synergy == pytest.approx(12.5)          # mean of .40 .20 -.10 .00 = .125
    assert s.staples_pct == pytest.approx(50.0)      # a, b are > 0
    assert s.anti_staples_pct == pytest.approx(50.0)  # c, d are <= 0 (zero is NOT a staple)
    assert s.staples_pct + s.anti_staples_pct == pytest.approx(100.0)


def test_baseline_is_the_pages_median_not_the_decks():
    """The whole page is the baseline — that is what makes it commander-relative."""
    page = {"a": 0.9, "b": 0.5, "c": 0.1, "tail1": 0.0, "tail2": -0.2}
    s = lift_stats.lift_stats(_deck("A", "B", "C"), page)
    assert s.baseline == pytest.approx(10.0)         # median of the FIVE page values
    assert s.synergy == pytest.approx(50.0)          # mean of the THREE deck values


def test_single_measured_card_has_no_spread():
    s = lift_stats.lift_stats(_deck("Only"), {"only": 0.5, "other": 0.1})
    assert s.synergy_range == 0.0


# ── verdicts ────────────────────────────────────────────────────────────────────

def test_low_coverage_still_reports_numbers_but_withholds_the_verdict():
    """Honesty channel: a mean over 11 of 70 cards is not 'your deck's synergy'.

    The numbers are still returned — the caller deserves to see them — but the verdict
    is withheld. Returning None here would delete the coverage figure entirely.
    """
    deck = _deck(*[f"Card {i}" for i in range(10)])
    s = lift_stats.lift_stats(deck, {"card 0": 0.9, "card 1": 0.9})
    assert s is not None
    assert s.coverage == pytest.approx(0.2)
    assert s.verdict == lift_stats.INSUFFICIENT
    assert s.synergy == pytest.approx(90.0)          # still reported


def test_coverage_at_the_threshold_is_sufficient():
    deck = _deck(*[f"Card {i}" for i in range(4)])
    s = lift_stats.lift_stats(deck, {"card 0": 0.9})
    assert s.coverage == pytest.approx(0.25)
    assert s.verdict != lift_stats.INSUFFICIENT


def _stats_for(deck_lifts: list[float]) -> LiftStats:
    """A deck of the given lifts against a page padded with a long flat tail.

    The tail is what a real commander page has and a deck does not: the rarely-played
    cards that drag the page median down.
    """
    page = {f"tail {i}": 0.0 for i in range(20)}
    page.update({f"d{i}": v for i, v in enumerate(deck_lifts)})
    return lift_stats.lift_stats(_deck(*[f"D{i}" for i in range(len(deck_lifts))]), page)


def test_verdict_uses_deltas_against_the_page_not_raw_comparison():
    """A deck barely above its page median is NOT 'high'.

    92.4% of corpus decks sit above their page median, so `synergy > baseline` sorted
    almost everything into one bucket. The cutoff is TYPICAL_SYNERGY_DELTA above it.
    """
    s = _stats_for([0.02, 0.02, 0.02, 0.02])
    assert s.synergy > s.baseline                                  # above the median...
    assert (s.synergy - s.baseline) < lift_stats.TYPICAL_SYNERGY_DELTA
    assert s.verdict in (lift_stats.BREW, lift_stats.OFF_PLAN)     # ...but not "high"


@pytest.mark.parametrize("deck_lifts,expected", [
    ([0.30, 0.30, 0.30, 0.30], lift_stats.ON_RAILS),            # high, narrow
    ([0.00, 0.20, 0.40, 0.90], lift_stats.FOCUSED_WITH_SPICE),  # high, wide
    ([-0.30, 0.00, 0.05, 0.35], lift_stats.BREW),               # low, wide
    ([0.02, 0.02, 0.02, 0.02], lift_stats.OFF_PLAN),            # low, narrow
])
def test_all_four_quadrants_are_reachable(deck_lifts, expected):
    """A classifier that can only emit two labels is not a classifier.

    Asserts the delta -> label MAPPING, deriving 'high'/'wide' from the returned figures
    rather than from hand-computed medians, so the test can't drift from the thresholds.
    """
    s = _stats_for(deck_lifts)
    high = (s.synergy - s.baseline) > lift_stats.TYPICAL_SYNERGY_DELTA
    wide = (s.synergy_range - s.baseline_range) > lift_stats.TYPICAL_RANGE_DELTA
    assert (high, wide) == {
        lift_stats.ON_RAILS: (True, False),
        lift_stats.FOCUSED_WITH_SPICE: (True, True),
        lift_stats.BREW: (False, True),
        lift_stats.OFF_PLAN: (False, False),
    }[expected]
    assert s.verdict == expected


# ── stats_block ─────────────────────────────────────────────────────────────────

def test_stats_block_returns_a_plain_dict(monkeypatch):
    monkeypatch.setattr(lift_stats.edhrec_lift, "lift_map", lambda n: {"known": 0.5})
    block = lift_stats.stats_block({"name": "Some Commander"}, _deck("Known"))
    assert isinstance(block, dict)
    assert set(block) == {f.name for f in __import__("dataclasses").fields(LiftStats)}
    assert block["measured"] == 1


@pytest.mark.parametrize("commander", [None, {}, {"name": ""}])
def test_stats_block_without_a_commander(commander, monkeypatch):
    monkeypatch.setattr(lift_stats.edhrec_lift, "lift_map",
                        lambda n: pytest.fail("should not fetch"))
    assert lift_stats.stats_block(commander, _deck("X")) == {}


def test_stats_block_swallows_every_failure(monkeypatch):
    """Advisory figures must never fail a build — the panel just doesn't appear."""
    def boom(_name):
        raise RuntimeError("EDHREC exploded")

    monkeypatch.setattr(lift_stats.edhrec_lift, "lift_map", boom)
    assert lift_stats.stats_block({"name": "C"}, _deck("X")) == {}


def test_stats_block_is_empty_when_nothing_is_measurable(monkeypatch):
    monkeypatch.setattr(lift_stats.edhrec_lift, "lift_map", lambda n: {})
    assert lift_stats.stats_block({"name": "C"}, _deck("X")) == {}


# ── the panel's wording is part of the contract ─────────────────────────────────

def _verdict_labels() -> dict[str, str]:
    """The `VERDICTS` map StepDeck.jsx renders, as {verdict: "label blurb"}.

    Label and blurb are joined because they are read as one sentence and either half can
    carry the claim — the original defect lived in BOTH ("Unfocused" / "few cards ...").

    Read out of the JSX rather than duplicated here, so this cannot drift into testing a
    copy of the wording instead of the wording that ships.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "frontend" / "src" / "components" / "StepDeck.jsx").read_text(encoding="utf-8")
    block = re.search(r"const VERDICTS = \{(.*?)\n\s*\};", src, re.S)
    assert block, "StepDeck.jsx no longer defines a VERDICTS map"
    q = r"(?:'([^']*)'|\"([^\"]*)\")"          # a JS string in either quote style
    out = {}
    for m in re.finditer(rf"'([a-z-]+)':\s*\[\s*{q}\s*,[^,]*,\s*{q}\s*\]", block.group(1)):
        label = m.group(2) if m.group(2) is not None else m.group(3)
        blurb = m.group(4) if m.group(4) is not None else m.group(5)
        out[m.group(1)] = f"{label} {blurb}"
    return out


def test_every_verdict_has_a_panel_entry():
    """A verdict with no `VERDICTS` entry renders as an em-dash with no explanation.

    Same lock-step failure as the theme taxonomy: two structures that must agree, and
    disagreement is silent — the panel still draws, it just says nothing.
    """
    emitted = {lift_stats.ON_RAILS, lift_stats.FOCUSED_WITH_SPICE, lift_stats.BREW,
               lift_stats.OFF_PLAN, lift_stats.INSUFFICIENT}
    assert emitted <= set(_verdict_labels()), (
        f"no StepDeck.jsx wording for: {sorted(emitted - set(_verdict_labels()))}")


# Median staples_pct per verdict, measured over the 238 corpus decks with a cached EDHREC
# page. The LOWEST bucket still has ~77% of its measured cards on positive lift, which is
# why no verdict may describe a deck as lacking synergy.
MEDIAN_STAPLES_PCT = {
    lift_stats.ON_RAILS: 98.4,
    lift_stats.FOCUSED_WITH_SPICE: 88.2,
    lift_stats.OFF_PLAN: 82.2,
    lift_stats.BREW: 77.0,
}

# Phrases that assert something ABSOLUTE about the deck. Every verdict is a quadrant of a 2x2
# cut at POPULATION medians, so all of them are comparative claims; wording that reads as an
# absolute one is false for most of the decks it fires on.
_ABSOLUTE_CLAIMS = ("few cards", "no synergy", "little synergy", "lacks", "unfocused",
                    "ignores", "not built around", "backbone for something else",
                    "random", "pile")


@pytest.mark.parametrize("verdict", sorted(MEDIAN_STAPLES_PCT))
def test_no_verdict_wording_claims_the_deck_lacks_synergy(verdict):
    """Table-driven over EVERY verdict, not just the one that was caught.

    `off-plan` shipped as "Unfocused - few cards lean on what this commander rewards" and was
    false for four of five decks it appeared on, at a quarter of all decks. `brew` shipped as
    "using the commander as a backbone for something else" while a median 77.0% of its measured
    cards are ones the commander wants. Both were the same mistake, found one at a time - so
    the guard now covers the whole table and a new verdict is covered the day it is added.
    """
    text = _verdict_labels()[verdict].casefold()
    for claim in _ABSOLUTE_CLAIMS:
        assert claim not in text, (
            f"{verdict!r} wording asserts {claim!r} absolutely, but a median "
            f"{MEDIAN_STAPLES_PCT[verdict]}% of its measured cards are on POSITIVE lift: {text!r}")


def test_the_staples_table_covers_every_judged_verdict():
    """A verdict absent from MEDIAN_STAPLES_PCT is silently unguarded above."""
    judged = {lift_stats.ON_RAILS, lift_stats.FOCUSED_WITH_SPICE,
              lift_stats.BREW, lift_stats.OFF_PLAN}
    assert judged == set(MEDIAN_STAPLES_PCT)


# ── confidence band ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("coverage,measured,expected", [
    (0.96, 70, lift_stats.CONFIDENCE_HIGH),
    (0.70, 38, lift_stats.CONFIDENCE_HIGH),      # exactly on both corpus cutoffs
    (0.69, 70, lift_stats.CONFIDENCE_MEDIUM),    # coverage just under
    (0.90, 30, lift_stats.CONFIDENCE_MEDIUM),    # plenty of coverage, thin SAMPLE
    (0.47, 25, lift_stats.CONFIDENCE_MEDIUM),
    (0.46, 90, lift_stats.CONFIDENCE_LOW),
    (0.27, 21, lift_stats.CONFIDENCE_LOW),
])
def test_confidence_needs_both_share_and_sample_size(coverage, measured, expected):
    """A share alone is not a sample size.

    40% of a 40-card list is a thinner reading than 40% of a 99-card one, so a high coverage
    with few measured cards must NOT read as high confidence. Bands are the corpus median and
    p25 on each axis (coverage 0.70 / 0.47, measured 38 / 25).
    """
    assert lift_stats._confidence(coverage, measured) == expected


def test_confidence_is_part_of_the_block():
    """The panel reads it off `stats.offmeta`, so it has to survive `dataclasses.asdict`."""
    block = lift_stats.stats_block({"name": "C"}, _deck("A"))  # no page -> {}
    assert block == {}
    s = _stats_for([0.30, 0.30, 0.30, 0.30])
    assert s.confidence in {lift_stats.CONFIDENCE_HIGH, lift_stats.CONFIDENCE_MEDIUM,
                            lift_stats.CONFIDENCE_LOW}


# ── The Core/Upgraded banner (bracket.plays_up) ──────────────────────────────────

def _sim_panel_source() -> str:
    from pathlib import Path
    p = (Path(__file__).resolve().parents[1]
         / "frontend" / "src" / "components" / "SimStrengthPanel.jsx")
    return p.read_text(encoding="utf-8")


def test_the_plays_up_banner_is_rendered_by_the_strength_panel():
    """The engine computed this for 24 days and the web app never showed it.

    `bracket.plays_up` marks a deck the Game Changer gate caps at Core while it sits on the
    Core/Upgraded edge — measured, 40% of decks their own authors call Upgraded also run zero
    Game Changers, so a zero-GC "Core" verdict cannot rule Upgraded out. The engine set the
    flag, `/analyze` returned it inside `power_profile`, and the CLI printed it; only the UI
    never read it, so the single most load-bearing number in the app shipped without its one
    honest caveat. It fires on 42% of the labelled corpus (124/297), 30 of which their
    builders called Bracket 3.

    Same silent lock-step class as `test_every_verdict_has_a_panel_entry`: a field the engine
    emits and the panel ignores fails without any symptom — the panel still draws.
    """
    source = _sim_panel_source()
    assert "bracket_plays_up" in source, (
        "SimStrengthPanel.jsx must read pp.bracket_plays_up — the engine has emitted it "
        "since 2026-07-28 and the panel ignored it")
    assert "Core / Upgraded" in source, "the banner must name the boundary it describes"


def test_the_banner_does_not_promise_a_bracket_it_cannot_measure():
    """It reports UNCERTAINTY, not a promotion.

    The wording must not read as "this deck is really a 3" — the whole finding is that the
    boundary is NOT resolvable from the card list, and two independent measurements (2026-07-28
    at n=87/33, 2026-08-21 at n=90/40) agree that nothing separates the two. A banner that
    quietly upgrades the deck would be the false precision the flag replaced.
    """
    source = _sim_panel_source()
    # 1400 -> 1900 (2026-08-24): the banner now covers TWO cases (Bracket 1 via a thin
    # manabase, Bracket 2 via the Core/Upgraded line — see bracket.plays_up), so the JSX
    # block covering both branches runs longer than the original single-case text.
    banner = source[source.index("bracket_plays_up"):][:1900]
    for promise in ("is Bracket 3", "is really a 3", "should be Bracket 3", "upgrade to 3"):
        assert promise not in banner, f"the banner must not promise a bracket: {promise!r}"
    assert "can" in banner and "settled" in banner, (
        "the banner must say the boundary cannot be settled from the card list")
