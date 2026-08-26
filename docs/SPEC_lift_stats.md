# SPEC — `lift_stats.py` (app root)

"How far off the beaten path is this deck?" — four deck-level statistics derived from
EDHREC lift.

## Why this exists

Myth Forge already answers "how strong is this deck" (bracket + the simulation-grounded
strength engine). It does not answer the question a casual pod actually asks first: *is
this a stock list or a brew?* Those are different axes — a precon and a wild brew can rate
the same bracket.

Lift gives it directly. The measurements below are the ones
[recommander.cards](https://recommander.cards) surfaces (its author calls the unnamed
feature a "hipster meter"), reproduced here on data this app already fetches for
`edhrec_lift`.

**This is a measurement module. It measures and reports; it decides nothing** — same
contract as `deck_quality.py`.

## Verified behaviour (measured on `corpus/decks`, do not guess)

| commander | deck cards | measured | coverage | deck mean lift | page median lift | % positive |
|---|---|---|---|---|---|---|
| Shelob, Child of Ungoliant | 78 | 57 | 73.1% | +28.9 | +7.5 | 78.9% |
| Ghired, Conclave Exile | 88 | 55 | 62.5% | +15.5 | +7.3 | 76.4% |
| Atraxa, Praetors' Voice | 94 | 45 | 47.9% | +5.7 | +3.2 | 84.4% |
| The Pride of Hull Clade | 57 | 25 | 43.9% | +4.7 | +6.4 | 72.0% |
| Ashling the Pilgrim | 33 | 25 | 75.8% | +26.5 | +5.9 | 88.0% |
| Jegantha, the Wellspring | 70 | 11 | **15.7%** | −4.2 | +3.3 | 18.2% |

Two things this table settles:

1. **Coverage varies from 16% to 76%, so it must be reported, not hidden.** An EDHREC
   commander page lists ~250 cards; the rest of a deck is simply unmeasured. Presenting a
   mean over 11 of 70 cards as "your deck's synergy" would be a confident fabrication.
   Below `MIN_COVERAGE` the verdict is withheld entirely.
2. **The baseline must be the commander's own page median, not a constant.** Lift scale is
   commander-relative (see `docs/SPEC_edhrec_lift.md`: Kadena maxes at 0.908, Atraxa at
   0.273). Page medians here range +3.2 to +7.5. Comparing every deck to a fixed number
   would rate every Atraxa deck as unsynergistic and every Kadena deck as a masterpiece.

## Constants

```python
MIN_COVERAGE = 0.25     # below this, verdict is "insufficient-data"
```

## Public API

```python
@dataclass(frozen=True)
class LiftStats:
    synergy: float            # deck mean lift, in POINTS (x100), 1dp
    synergy_range: float      # top-quartile mean minus bottom-quartile mean, points, 1dp
    staples_pct: float        # % of MEASURED cards with lift > 0, 1dp
    anti_staples_pct: float   # % of MEASURED cards with lift <= 0, 1dp
    baseline: float           # the commander page's MEDIAN lift, points, 1dp
    baseline_range: float     # the page's own top-minus-bottom quartile spread, points
    measured: int             # cards found on the commander's page
    total: int                # cards considered (deck minus basic lands)
    coverage: float           # measured / total, 0..1, 3dp
    verdict: str              # see below
    theme_extra: int = 0      # (S4) cards measured ONLY via a theme sub-page — informational
    theme_tag: str | None = None   # which EDHREC tag supplied them, or None

def lift_stats(
    deck: list[dict], lifts: dict[str, float], *,
    extra: dict[str, float] | None = None, extra_tag: str | None = None,
) -> LiftStats | None
def stats_block(commander: dict, deck: list[dict], themes: list[str] | None = None) -> dict
```

### `lift_stats(deck, lifts)`

- `deck` is a list of Myth Forge card dicts (`{"name": ..., "type_line": ...}`); a
  `quantity` key may be present and is **ignored** — a second copy of a card says nothing
  about how off-meta the deck is.
- Skip **basic lands** (`"basic" in type_line.casefold() and "land" in type_line.casefold()`).
  They are never on a commander page and would only deflate coverage.
- Deduplicate by `edhrec_lift.normalize_name`.
- Returns `None` when `lifts` is empty or no non-basic cards remain — nothing measurable,
  so say nothing.
- Quartile means: sort the measured lifts; the top quartile is the last `max(1, n // 4)`
  values and the bottom quartile the first `max(1, n // 4)`. With n < 4 both collapse to
  the same single value and `synergy_range` is 0.0, which is correct — one card has no
  spread.

### Verdict

Compare the deck against the commander's own page, then map to the 2x2:

- `high = synergy > baseline`, `wide = synergy_range > baseline_range`
- `high and not wide` → `"on-rails"` — clustered in this commander's good pile; how
  precons and cycle decks behave
- `high and wide` → `"focused-with-spice"`
- `not high and wide` → `"brew"` — using the commander as a backbone for something else
- `not high and not wide` → `"off-plan"`
- `coverage < MIN_COVERAGE` → `"insufficient-data"` (checked FIRST, overrides all)

### `stats_block(commander, deck, themes=None)`

The `compute_stats` integration point, mirroring `deck_builder.deck_quality_block`:

- Reads the commander name from `commander.get("name")`; returns `{}` if absent.
- Calls `edhrec_lift.lift_map(name)` then `lift_stats`.
- Returns `{}` — never raises and never partially fills — on **any** exception, and `{}`
  when `lift_stats` returns `None`. These figures are advisory and must never fail a
  build. (`deck_quality_block` has exactly this contract.)
- Otherwise returns the `LiftStats` fields as a plain dict via `dataclasses.asdict`.

### Theme sub-page coverage widening (S4, 2026-08-26)

`themes` should be the deck's own detected archetypes (`deck_themes.detect_deck_themes`),
strongest first. `stats_block` resolves the first one with a known tag
(`edhrec_lift.tag_for_themes`), fetches that theme's sub-page
(`edhrec_lift.theme_lift_map`), and passes it to `lift_stats` as `extra`/`extra_tag`.

**This is informational ONLY** — see `edhrec_lift.theme_lift_map`'s docstring and
`docs/SPEC_edhrec_lift.md` for why: a sub-page's synergy was measured to be a
scale-mismatched statistic (same sign ~98% of the time, but a different magnitude,
worse the narrower the sub-tag is relative to the commander's whole population), and
`coverage`/`synergy`/`baseline`/`verdict` above were all calibrated against main-page-only
data. Folding sub-page values into them would silently invalidate that calibration.
`theme_extra`/`theme_tag` report what WOULD be newly measurable, without touching anything
the verdict thresholds actually consume.

Omitting `themes` (or passing only unmapped ones) is a no-op — no extra network call, and
the result is byte-identical to before this parameter existed.

**Measured impact**, 25 corpus decks with a mapped detected theme (`scratchpad/s4_sweep.py`):
18/25 (72%) gained newly-measurable cards; mean coverage delta +4.7 points, median +2.4,
max +25.9 (Eshki, Temur's Roar / `dragons`).

## Style requirements

- `from __future__ import annotations`, module docstring first.
- The module docstring carries the **measured table above**, per house convention
  (`collection_pool.py`, `deck_quality.py`, `theme_match.py` all do this).
- Imports: stdlib + `import edhrec_lift`. Nothing else. No engine imports, no network of
  its own (`edhrec_lift.lift_map` owns the fetch and its cache).
- Every public function documented with the reasoning, not the syntax.
- Pure and deterministic given `lifts`.
