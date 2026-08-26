# SPEC — `edhrec_lift.py` (app root)

Commander-conditioned card ordering for `deck_builder`, from EDHREC lift.

## Why this exists

`DeckBuilder` fills every role slot with a Scryfall query sorted by **global
`edhrec_rank`** — a pure popularity ordering with no opinion about the commander. The
consequence is the one [recommander.cards](https://recommander.cards) diagnoses: two decks
with the same commander (or even different commanders sharing a colour identity) get
recommendations that look the same, because the ordering never asks "does *this* commander
want this card?"

EDHREC publishes exactly that number per commander — **lift**: how much more often a card
appears in this commander's decks than in decks of its colour identity generally. The
engine already fetches and parses it (`mythgauntlet.data.edhrec.EdhrecCard.synergy`), but
nothing consumes it. This module makes it available to the app-root builder.

**This is an app-root module, not an engine one.** `deck_builder.py` cannot import
`mythgauntlet.*`: the engine runs as a separate process on :8020 and the Forge server is
launched without `src/` on the path. Cache goes under `app_path("cache", ...)` per
`app_paths.py` — never a bare relative `Path`.

## Verified data shape (fetched live, do not guess)

`GET https://json.edhrec.com/pages/commanders/{slug}.json` → 200, JSON:

```
payload["container"]["json_dict"]["cardlists"]  # list
  [i]["tag"]                                    # e.g. "highsynergycards", "creatures"
  [i]["cardviews"]                              # list
     [j] keys: id, name, num_decks, potential_decks, sanitized, slug, synergy,
               trend_zscore, url
```

`synergy` is a **signed fraction**, not a percentage: `0.908` means +90.8 points.
Measured on live pages:

| commander | rows | synergy min | max | median | negatives |
|---|---|---|---|---|---|
| Kadena, Slinking Sorcerer | 244 | -0.149 | 0.908 | 0.114 | 54 |
| Atraxa, Praetors' Voice | 292 | -0.164 | 0.273 | 0.032 | 59 |

**The scale is commander-relative and that is load-bearing.** Kadena is a focused commander
(max 0.908); Atraxa is a goodstuff pile (max 0.273). Any absolute cutoff would classify
almost every Atraxa card as "no synergy" while classifying half the Kadena page as
synergistic. **Use the zero-crossing**, which is scale-free and directly meaningful: above
zero = played more here than baseline.

Negative-lift cards are exactly the generic staples — Kadena's most negative are Swiftfoot
Boots, An Offer You Can't Refuse, Counterspell; Atraxa's are Mystic Remora, Force of Will,
Swan Song. That is the signal, not noise.

Slug rule (mirror `mythgauntlet.data.edhrec.commander_slug`): take the front face before
`" // "`, casefold, drop every character that is not `[a-z0-9 -]`, join whitespace runs
with `-`.

## Module contents — implement EXACTLY these public names

### `CACHE_MAX_AGE_DAYS: int = 14`

### `def commander_slug(name: str) -> str`
As above. `"Kadena, Slinking Sorcerer"` → `"kadena-slinking-sorcerer"`.

### `def lift_map(commander_name: str, *, max_age_days: int | None = None, force: bool = False) -> dict[str, float]`
`{normalized card name: synergy}` for one commander. Empty dict on **any** failure —
network error, non-200, malformed JSON, unknown commander. This is an ordering hint; a
build must never fail because EDHREC is down.

- Cache file: `app_path("cache", "edhrec", f"{slug}.json")`, storing the raw payload.
- **Age check**: a cache file whose mtime is older than `max_age_days` (default
  `CACHE_MAX_AGE_DAYS`) is refetched. A stale corpus only ever recommends old cards — this
  repo has already shipped that bug once with a 26-day-frozen Scryfall bulk. If the refetch
  fails, **fall back to the stale cache** rather than returning nothing.
- `force=True` always refetches.
- Atomic write: write `{slug}.json.part`, then `.replace()` the target.
- Normalize names with `normalize_name` (below) so lookups are case/spacing insensitive.
- Take the FRONT FACE of a card name (split on `" // "`) as the key, and when the same
  name appears in several cardlists keep the **first** synergy seen.
- Request header `User-Agent: MythForge/1.0 (+https://github.com/onemorethan0/mythforgemtg)`,
  `timeout=15`.

### `def normalize_name(name: str) -> str`
Front face before `" // "`, casefolded, whitespace collapsed. Pure.

### `def lift_order(candidates: list[dict], lifts: dict[str, float]) -> list[dict]`
Reorder Scryfall card dicts (each has a `"name"` key) so the commander's preferred cards
come first. **A stable three-tier partition**, mirroring `deck_builder._prefer_owned`:

1. `lift > 0` — cards this commander plays more than baseline, sorted by lift **descending**
2. **unknown** — not on the commander's page: original order preserved untouched
3. `lift <= 0` — cards this commander plays less than baseline: original order preserved

Rationale for tier 2 sitting above tier 3: an absent card is *unmeasured*, not *rejected* —
a card printed last week has no EDHREC history at all. Demoting it below a measured
negative would penalise every new release, which is the exact failure this whole change
exists to avoid.

Returns a **new list**; never mutates the input. `lifts == {}` returns the input order
unchanged (so a missing/failed EDHREC page is a no-op, byte for byte).

## Theme sub-pages (S4, 2026-08-26) — widen coverage, never touch the main baseline

`GET https://json.edhrec.com/pages/commanders/{slug}/{tag}.json` serves the same shape as
the main page, scoped to decks EDHREC tagged with that theme. Its own `panels.taglinks` on
the MAIN page lists every tag slug that page has a sub-page for — a full sample across four
commanders spanning different colour identities (Omo, Edgar Markov, Kaalia, Krenko) surfaced
the tags in `ARCHETYPE_EDHREC_TAGS` below.

**Measured, not assumed: a sub-page's `synergy` is a DIFFERENT statistic, not more data on
the same one.** Its `potential_decks` is the count of decks carrying that TAG, not every
deck running the commander (Atraxa main: 43,585; Atraxa `infect` sub-page: 4,331). Fetched
live and compared card-by-card:

| commander/tag | overlapping cards | sign agreement | example (main → sub) |
|---|---|---|---|
| Omo / `landfall` | 230 | 225/230 (97.8%) | Rhystic Study -0.056 → -0.048 |
| Atraxa / `infect` | 5 (spot check) | 5/5 | Rhystic Study -0.106 → -0.048 |

Sign agreement is high — the 5 Omo disagreements all sit within ±0.04 of zero on both sides
(noise at the boundary, not a reversal). **Magnitude is NOT interchangeable**: the same card
can differ by up to ~50% relative, and the gap is bigger the narrower the sub-tag is relative
to the commander's whole population (Atraxa/infect, ~10% of Atraxa decks, diverges more than
Omo/landfall, a much larger share of Omo's own decks). **Consequence: never union a
`theme_lift_map` result into a `lift_map` result for the same commander and treat it as one
population** — `lift_stats.lift_stats`'s `extra`/`extra_tag` parameters exist specifically so
a sub-page can widen `theme_extra` (an informational count) without ever entering `coverage`,
`synergy`, `baseline`, or `verdict`, all of which were calibrated against main-page-only data.

**Measured impact** (`scratchpad/s4_sweep.py`, not committed — offline-reproducible against
the engine's card db + live EDHREC): 25 corpus decks whose own detected theme
(`deck_themes.detect_deck_themes`, NOT the commander's unsupported claims) maps to a real
tag: **18/25 (72%) gained at least one newly-measured card**, mean coverage delta **+4.7
points**, median **+2.4**, max **+25.9** (Eshki, Temur's Roar / `dragons`: 70.6% → 96.5%).

### `ARCHETYPE_EDHREC_TAGS: dict[str, str]`
`commander_analysis.THEME_PATTERNS` key → EDHREC tag slug. Only entries with real evidence
(seen on a live page) are included — a wrong slug 404s silently to `{}`, indistinguishable
from "this deck has no theme", so a guessed entry would look wired while doing nothing.
`draw_matters` is deliberately OMITTED: its pattern is a payoff ("whenever you draw a card"),
EDHREC's `card-draw` tag is a shopping list of draw SOURCES — the sources-vs-payoffs trap
already caught once for `lifegain` and rejected for `big_mana`. `face_down` maps to `morph`
only (EDHREC has no combined morph/manifest/disguise tag — under-covers rather than
over-claims). `impulse` maps to the real tag `impulse-draw` (naming mismatch, not semantic).
`voltron` and `voltron_combat` both map to EDHREC's single `voltron` tag — safe, since this
only ever widens coverage, never overwrites.

### `def tag_for_themes(themes: list[str] | None) -> str | None`
First entry in `themes` (the caller's own priority order) with a known tag, else `None`.
Callers must pass the DECK's own detected themes, not `merge_themes`' output — the "deck's
plan, not the commander's unsupported claims" contract `redundancy.targets_for` already
documents; using the merged list would widen coverage toward a theme the deck isn't playing.

### `def theme_lift_map(commander_name, tag, *, max_age_days=None, force=False) -> dict[str, float]`
Same cache-then-fetch-then-degrade contract as `lift_map`, against `THEME_URL` and a
SEPARATE cache file (`app_path("cache", "edhrec", f"{slug}__{tag}.json")` — must not collide
with the main page's `{slug}.json`). `{}` when disabled, no tag, no commander, or on any
failure. Shares its HTTP/cache mechanics with `lift_map` via a private `_fetch_lifts` helper
so the two paths cannot silently diverge on staleness or atomic-write behaviour.

## Style requirements

- `from __future__ import annotations` first, then the module docstring rules below.
- Module docstring carries the **verified data-shape table above** (rows, min/max/median,
  negatives) — that measurement is why the zero-crossing rule is right, and a future reader
  must not have to re-derive it.
- Every public function documented with the reasoning, not the syntax.
- Only stdlib + `requests` + `from app_paths import app_path`. No engine imports.
- Pure/deterministic apart from the single cached HTTP call.
- No printing, no logging, no raising out of `lift_map`.
