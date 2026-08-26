"""How far off the beaten path is this deck? (spec: docs/SPEC_lift_stats.md)

Myth Forge already answers "how strong is this deck" — bracket, plus the simulation-grounded
strength engine. It does not answer the question a casual pod asks first: is this a stock
list or a brew? Those are different axes; a precon and a wild brew can rate the same bracket.

EDHREC lift answers it directly, from data `edhrec_lift` already fetches. This module
MEASURES AND REPORTS; it decides nothing — same contract as `deck_quality.py`.

Measured on corpus/decks (verified, not assumed):

| commander                  | cards | measured | coverage | deck mean | page median | pos%  |
|----------------------------|-------|----------|----------|-----------|-------------|-------|
| Shelob, Child of Ungoliant |  78   |    57    |  73.1%   |   +28.9   |    +7.5     | 78.9% |
| Ghired, Conclave Exile     |  88   |    55    |  62.5%   |   +15.5   |    +7.3     | 76.4% |
| Atraxa, Praetors' Voice    |  94   |    45    |  47.9%   |    +5.7   |    +3.2     | 84.4% |
| The Pride of Hull Clade    |  57   |    25    |  43.9%   |    +4.7   |    +6.4     | 72.0% |
| Ashling the Pilgrim        |  33   |    25    |  75.8%   |   +26.5   |    +5.9     | 88.0% |
| Jegantha, the Wellspring   |  70   |    11    |  15.7%   |    -4.2   |    +3.3     | 18.2% |

Two things that table settles:

1. COVERAGE VARIES 16%-76%, SO IT IS REPORTED, NEVER HIDDEN. An EDHREC page lists ~250
   cards; the rest of a deck is simply unmeasured. Presenting a mean over 11 of 70 cards as
   "your deck's synergy" would be a confident fabrication. Below MIN_COVERAGE the numbers
   are still returned — the caller deserves to see them — but the verdict is withheld.
2. THE BASELINE IS THE COMMANDER'S OWN PAGE MEDIAN, NOT A CONSTANT. Lift scale is
   commander-relative (docs/SPEC_edhrec_lift.md: Kadena maxes at 0.908, Atraxa at 0.273),
   and the page medians above span +3.2 to +7.5. A fixed threshold would rate every Atraxa
   deck unsynergistic and every Kadena deck a masterpiece.

The VERDICT thresholds are calibrated, not guessed. Over 160 sampled corpus decks (144 with
coverage >= 25%, median coverage 0.740):

    synergy - page median : median +11.65   p25  +7.60   p75 +17.40   (92.4% above zero)
    spread  - page spread : median  +8.95   p25  +1.30   p75 +14.80   (78.5% above zero)

Those "above zero" shares are why the obvious rule is wrong. A deck plays a commander's
GOOD cards while the page median includes the long tail of rarely-played ones, so "above
the page median" is true of nearly every deck and sorts almost all of them into one bucket.
TYPICAL_SYNERGY_DELTA / TYPICAL_RANGE_DELTA are the population medians of those two deltas,
which splits each axis near 50/50 and gives four populated quadrants.
"""

from __future__ import annotations

import dataclasses
import statistics
from dataclasses import dataclass

import edhrec_lift

# Below this share of the deck measured, the numbers are reported but the verdict is not.
# 144 of the 160 sampled corpus decks clear it (median coverage 0.740), so it excludes the
# genuinely unmeasurable without discarding ordinary decks.
MIN_COVERAGE = 0.25

# How much weight a reading deserves, from the corpus distribution of coverage over the 244
# decks with a cached page: p10 0.22 · p25 0.47 · median 0.70 · p75 0.88, and measured-card
# counts p10 20 · p25 38 · median 58.
#
# Coverage alone is not enough: 40% of a 40-card list is a smaller sample than 40% of a
# 99-card one, so both the SHARE and the absolute COUNT have to clear their bar. A percentage
# shown without any signal of its own reliability invites the reader to treat a 26% reading
# and a 96% one as the same claim — which is the fabrication this module already refuses to
# make with `insufficient-data`, just one step further up the scale.
CONF_HIGH_COVERAGE = 0.70     # corpus median
CONF_MED_COVERAGE = 0.47      # corpus p25
CONF_HIGH_MEASURED = 38       # corpus p25 of measured-card count
CONF_MED_MEASURED = 25

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


def _confidence(coverage: float, measured: int) -> str:
    """Weight for a reading, from BOTH the share measured and the absolute sample size."""
    if coverage >= CONF_HIGH_COVERAGE and measured >= CONF_HIGH_MEASURED:
        return CONFIDENCE_HIGH
    if coverage >= CONF_MED_COVERAGE and measured >= CONF_MED_MEASURED:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW

# Verdict thresholds, CALIBRATED over 144 corpus decks (see the module docstring). They are
# applied to the deck's figures MINUS this commander's page figures, so the comparison stays
# commander-relative while the cutoff is an empirical population constant.
#
# Why not simply "above the page median": a real deck plays a commander's GOOD cards, while
# the page median includes the long tail of rarely-played ones. Measured, 92.4% of decks sit
# above their page median on synergy and 78.5% above it on spread — so that test put nearly
# every deck in one bucket and told the user nothing. These are the population medians of
# the two deltas, which splits each axis near 50/50 and gives four populated quadrants.
TYPICAL_SYNERGY_DELTA = 11.6   # points above the commander's page median
TYPICAL_RANGE_DELTA = 8.9      # points above the commander's page spread

# Verdicts, from the 2x2 of (deck vs page median) x (deck spread vs page spread).
#
# Every one of these is RELATIVE TO THE POPULATION, because both cutoffs are population
# medians. Read absolutely they are all wrong, and OFF_PLAN is the one that tempts a
# reader into doing so — it is the residual quadrant, so "below the median delta on both
# axes" reads like "this deck ignores its commander". Measured over the 238 corpus decks
# with a cached page: OFF_PLAN fires on 24.8% of them, and of those, 80% sit ABOVE their
# commander's page median on synergy and 80% have >=70% of their measured cards on
# positive lift (median staples_pct 82.2 — HIGHER than BREW's 77.0). It means "leans on
# the commander less than most decks do", never "few cards lean on the commander".
# Any user-facing wording for these lives in StepDeck.jsx and must respect that.
ON_RAILS = "on-rails"                    # high synergy, narrow spread: precon/cycle-deck shape
FOCUSED_WITH_SPICE = "focused-with-spice"
BREW = "brew"                            # commander as a backbone for something else
OFF_PLAN = "off-plan"                    # residual quadrant: BOTH deltas below the median
INSUFFICIENT = "insufficient-data"


@dataclass(frozen=True)
class LiftStats:
    """All figures in POINTS (lift x 100), the unit EDHREC itself displays."""

    synergy: float            # deck mean lift
    synergy_range: float      # deck top-quartile mean minus bottom-quartile mean
    staples_pct: float        # % of MEASURED cards with lift > 0
    anti_staples_pct: float   # % of MEASURED cards with lift <= 0
    baseline: float           # the commander page's median lift
    baseline_range: float     # the page's own quartile spread
    measured: int
    total: int                # cards considered (deck minus basic lands, deduped)
    coverage: float           # measured / total, 0..1
    confidence: str           # how much weight this reading deserves — see CONFIDENCE_*
    verdict: str
    # Cards found ONLY on a theme sub-page (absent from the main page), and which tag
    # supplied them — informational, never folded into coverage/synergy/verdict/confidence
    # above. See `lift_stats`'s docstring for why: a sub-page's synergy is a scale-mismatched
    # statistic (S4, 2026-08-26), and every threshold above was calibrated against
    # main-page-only figures.
    theme_extra: int = 0
    theme_tag: str | None = None


def _is_basic_land(card: dict) -> bool:
    """Basics are never on a commander page; counting them would only deflate coverage."""
    tl = (card.get("type_line") or "").casefold()
    return "basic" in tl and "land" in tl


def _quartile_spread(sorted_values: list[float]) -> float:
    """Mean of the top quarter minus mean of the bottom quarter.

    "The gulf between your higher-lift and lower-lift cards" — more robust than a raw
    max-minus-min, which one pet card would dominate. With fewer than 4 values both
    quarters collapse onto the same element and the spread is 0.0, which is correct: one
    card has no spread.
    """
    n = len(sorted_values)
    if n < 2:
        return 0.0
    q = max(1, n // 4)
    return statistics.fmean(sorted_values[-q:]) - statistics.fmean(sorted_values[:q])


def lift_stats(
    deck: list[dict],
    lifts: dict[str, float],
    *,
    extra: dict[str, float] | None = None,
    extra_tag: str | None = None,
) -> LiftStats | None:
    """Deck-level lift statistics, or None when there is nothing measurable to say.

    `lifts` is the WHOLE commander page (as returned by `edhrec_lift.lift_map`), not just
    the deck's cards — that is what makes the page median available as a baseline.

    `extra` is an OPTIONAL theme sub-page (`edhrec_lift.theme_lift_map`), used ONLY to
    count cards this deck plays that `lifts` has nothing to say about — `theme_extra` on
    the result. It never touches `coverage`, `synergy`, `baseline`, `verdict` or
    `confidence`: a sub-page's synergy is measured to be a DIFFERENT, scale-mismatched
    statistic (see `edhrec_lift.theme_lift_map`'s docstring), and every threshold this
    module uses was calibrated against main-page-only figures. Folding it in would corrupt
    a calibrated number to report an uncalibrated one as if it were the same kind of thing.

    `quantity` is deliberately ignored: a second copy of a card says nothing about how
    off-meta the deck is, and counting basics by quantity would swamp everything else.
    """
    if not lifts:
        return None

    seen: set[str] = set()
    names: list[str] = []
    for card in deck:
        if _is_basic_land(card):
            continue
        key = edhrec_lift.normalize_name(card.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(key)

    total = len(names)
    if total == 0:
        return None

    measured_lifts = sorted(lifts[n] for n in names if n in lifts)
    measured = len(measured_lifts)
    coverage = measured / total
    if measured == 0:
        return None

    extra = extra or {}
    theme_extra = sum(1 for n in names if n not in lifts and n in extra)

    page = sorted(lifts.values())
    baseline = statistics.median(page)
    baseline_range = _quartile_spread(page)

    synergy = statistics.fmean(measured_lifts)
    synergy_range = _quartile_spread(measured_lifts)
    positive = sum(1 for v in measured_lifts if v > 0)

    if coverage < MIN_COVERAGE:
        verdict = INSUFFICIENT      # checked first: it overrides the 2x2
    else:
        # Deltas against THIS commander's page keep the comparison commander-relative;
        # the cutoffs are corpus-calibrated population constants (see above).
        high = (synergy - baseline) * 100 > TYPICAL_SYNERGY_DELTA
        wide = (synergy_range - baseline_range) * 100 > TYPICAL_RANGE_DELTA
        verdict = (FOCUSED_WITH_SPICE if high and wide
                   else ON_RAILS if high
                   else BREW if wide
                   else OFF_PLAN)

    return LiftStats(
        synergy=round(synergy * 100, 1),
        synergy_range=round(synergy_range * 100, 1),
        staples_pct=round(positive / measured * 100, 1),
        anti_staples_pct=round((measured - positive) / measured * 100, 1),
        baseline=round(baseline * 100, 1),
        baseline_range=round(baseline_range * 100, 1),
        measured=measured,
        total=total,
        coverage=round(coverage, 3),
        confidence=_confidence(coverage, measured),
        verdict=verdict,
        theme_extra=theme_extra,
        theme_tag=extra_tag if theme_extra else None,
    )


def stats_block(commander: dict, deck: list[dict], themes: list[str] | None = None) -> dict:
    """The `compute_stats` integration point, mirroring `deck_builder.deck_quality_block`.

    `themes` should be the DECK's own detected themes (`deck_themes.detect_deck_themes`),
    not `merge_themes`' output — the same "the deck's own plan, not the commander's
    unsupported claims" contract `redundancy.targets_for` documents. Used only to pick a
    theme sub-page to widen coverage with (`theme_extra` on the block); omitting it (or
    passing themes with no known EDHREC tag) is a no-op, byte-identical to before this
    parameter existed.

    Returns `{}` on anything at all — no commander, no EDHREC page, an unofficial API that
    changed shape, a network failure. These figures are advisory and must never fail a
    build, so the failure mode is "the panel doesn't appear", never an exception.
    """
    try:
        name = (commander or {}).get("name")
        if not name:
            return {}
        extra: dict[str, float] = {}
        tag = edhrec_lift.tag_for_themes(themes)
        if tag:
            extra = edhrec_lift.theme_lift_map(name, tag)
        stats = lift_stats(deck or [], edhrec_lift.lift_map(name), extra=extra, extra_tag=tag)
        return dataclasses.asdict(stats) if stats is not None else {}
    except Exception:      # noqa: BLE001 - advisory measurement, never fails a build
        return {}
