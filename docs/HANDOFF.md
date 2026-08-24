# Handoff — recommendation & measurement work (2026-08-14)

Written to be the **first thing a new session reads** before touching the builder, the
advisor, or the theme taxonomy. `CLAUDE.md` remains the engineering map (and is gitignored,
so it is local-only); this file is the committed record of what changed, what was measured,
and what is still open.

Baseline for every number here is commit `c6ddd79`. Suite went **576 → 956 tests**.

> **NEXT SESSION START HERE: [`PLAN_CLOCK.md`](PLAN_CLOCK.md).** The bracket estimate — the one
> output the casual-gauging goal actually rests on — is capped by a single measurable fact:
> the goldfish clock is **bracket-invariant**. Every bracket's best draw lands on turn ~8.5,
> cEDH included, because `kill_turn` is set from cumulative **combat** damage alone
> (`sim/tier0.py:348`). No threshold-fitting moves the number while that holds. The plan says
> what to build, in what order, and which four obvious moves have already been measured and
> rejected. **2026-08-24: Phase 1a+1b both landed** (storm/overrun wired into `kill_turn` per
> run, then real burn/magecraft/ritual-mana damage modeled directly in the T0 sim). Together
> they fixed the specific inversion (B5's nut-draw kill is now faster than B3's, was slower)
> and the bracket-accuracy headline is unchanged as expected (nothing consumes the speed
> signal for placement yet) — but the B2/B3 |d|>=0.5 gate was still not met, and 1b barely
> moved it. **DECIDED (with user sign-off): B2/B3 exact-match via the clock is closed** — two
> independently-wired non-combat-kill mechanisms both failed to separate B2 from B3, which is
> evidence, not a coin flip. Do not restart 1c hoping to fix this specific gate (see
> PLAN_CLOCK.md's Phase 1 "DECIDED" note for the reasoning). **Target within-one (91.6% → 95%)
> going forward, not bracket-exact at B2/B3.** Phase 3's B1/B2 refit is untouched by this and
> may still proceed — it's a different boundary that doesn't depend on the speed axis.

---

## 1. Where this came from

A YouTube video — [*I Built My Own EDHREC… and It Actually Works*](https://www.youtube.com/watch?v=omYfGzrsTRc)
by GamesfreakSA ([recommander.cards](https://recommander.cards)) — argues that EDHREC's deck
recommender keys on the **commander**, not on your **deck**, so a precon and a wild brew get
near-identical suggestions. The author demos it on a Kadena manifest brew.

Myth Forge had the same defect in a stronger form: every role window was ordered by *global*
`edhrec_rank`. The work below started there and kept going wherever measurement led.

---

## 2. What the builder now does differently

| change | commit | measured effect |
|---|---|---|
| Role windows ordered by **commander lift**, not global popularity | `182cafc` | see §3 |
| Theme package lift-ordered too, **lead-weighted** split | `f420c8b`, `df143ac` | fixed a bug where theme 1 ate all 20 slots |
| **Strict/collection** pool lift-ordered | `3153cc8` | strict synergy **4.39 → 13.44** |
| Basics re-split to real pips **after** drafting | `90f2b3e` | colours 8 → 9 |
| **Rainbow land tier** (3+ colours only) | `d8d0028` | colours 9 → 19 |
| Dead fetchlands filtered; fetches counted as sources | `45235c0` | colours 19 → **20/20** |
| Three themes added: `face_down`, `sagas`, `impulse` | `7f146f9` | zero-theme commanders 21.6% → 18.8% |
| Five dead `theme_match` rules revived | `53c330a` | `landfall` matched **1** card in 34,846 |
| Partner colour identity = **union** of the zone | `081ddb7` | 16 of 29 partner decks flipped to castable |

Plus, on the analysis side: the **off-meta read** (`lift_stats`), **deck-context archetypes**
(`deck_themes`), and **redundancy-based cut candidates** (`redundancy`) replacing "cut the
least-played card".

---

## 3. The measurement infrastructure — use it

Three harnesses now exist. **Nothing in this area should be changed without running them.**

    # Builder, Scryfall path (what an ordinary build runs). ~6 min.
    python scripts/builder_bench.py --out docs/bench/run.json --pause 6 --rate-delay 0.5
    python scripts/builder_bench.py --compare docs/bench/baseline-c6ddd79.json docs/bench/run.json

    # Builder, strict/collection path — exercises theme_match, which the above never touches.
    python scripts/builder_bench.py --out docs/bench/strict.json --strict --pause 3

    # Upgrade advisor. ALWAYS multi-seed (see section 5).
    python scripts/advisor_bench.py --decks 20            # 4 seeds by default
    python scripts/advisor_bench.py --decks 10 --show-cuts

Calibration tables are regenerated, never hand-edited:

    python scripts/theme_base_rates.py --check   # deck_themes.BASE_RATE
    python scripts/role_targets.py --check       # redundancy.ROLE_TARGETS

Committed reference runs live in `docs/bench/`. Neither harness is CI-safe — they need
`data/cards_slim.json`, a semantics store (`MYTHGAUNTLET_STORE`), and the network.

### Builder state vs baseline

| metric | `c6ddd79` | now |
|---|---|---|
| mean synergy | 5.66 | **15.85** |
| median synergy | 4.35 | 15.2 |
| above EDHREC baseline | 7/20 | 17/20 |
| **colours castable** | 10/20 | **20/20** |
| on-theme cards | 11.75 | 16.9 |
| curve deviation | 15.40 | 15.5 |

---

## 4. Method that worked, and should be continued

Every substantive find came from **measuring an assumption**, usually one already written
down as fact. That is the method, not an anecdote:

- *"The theme package is why Kadena rates off-plan"* → **wrong**; after lift-ordering it,
  Kadena's numbers were byte-identical. The real cause was a taxonomy with no morph entry.
- *"An even theme split is obviously correct"* → **measurably worse** than lead-weighted
  (cost multi-theme commanders 1.65 synergy and broke two decks' colours).
- *"The owned pool is small enough that its own ordering dominates"* → **8.6 points of
  headroom** left on the table; lift-ordering it tripled strict synergy.
- *"`oversupply * within_role` is a defect, not an approximation"* → **indistinguishable**
  from the shipped shape, and its Magic argument is arguably better (see section 5).
- *"The counterspell target is probably too low"* → **backwards**; the median deck runs zero.

Three specific traps worth knowing:

1. **A raw count is not evidence.** `voltron_combat` scores STRONG on **19.35%** of every
   card in Magic, so a "3 matching cards = this theme" rule fired on **100%** of *randomly
   drawn* 60-card piles. Always compare against a base rate (`deck_themes.BASE_RATE`).
2. **The builder's plan is not the population.** `ROLE_TARGETS` came from
   `playstyle.DEFAULT_SLOTS` — what the app intends to *build* — and using it to judge decks
   people already own made draw+ramp 83% of every cut suggestion.
3. **A degraded run looks like a clean one.** `ScryfallClient._get` returns `None` after four
   retries, indistinguishable from an empty result, so a throttled role query silently
   contributes zero cards. `builder_bench` captures the builder's own
   `"Padding N missing slots"` log rather than guessing.

---

## 5. Read these caveats before quoting any number

- **Advisor seed variance exceeds the effects being measured.** The same strategy on the
  same 20 decks scores **79 to 231** depending only on the sim seed. An earlier commit in
  this series quoted `237.92 vs 209.38` from one seed as a clean +13.6% win; across four
  seeds the honest claim is *"better on 3 of 4 seeds by roughly 8%, and a single seed can
  reverse it."* `advisor_bench` is multi-seed by default now — keep it that way.
- **The axis-delta metric cannot see advice quality.** `advise` tests every add against the
  whole cut pool and keeps the best-measuring pairing, so the simulation partly rescues a bad
  pool. Redundancy vs popularity is near-tied on delta, but `--show-cuts` shows popularity
  recommending **Shelob cut "Eaten by Spiders"** and **Sefris cut "Living End"** — the deck's
  own theme. The redundancy pool is justified on advice quality, *not* on delta.
- **Two constants are NOT calibratable and are labelled as such**: `redundancy`'s score shape
  and `deck_themes.WEAK_WEIGHT`. Both were measured; neither has ground truth. Do not "tune"
  them without a new source of truth.

---

## 6. Recurring bug classes in this codebase

Worth grepping for when touching anything nearby:

- **A top-level `OR` in a Scryfall query un-filters its first branch.** `DeckBuilder` appends
  `id<=…`, `legal:commander`, `-type:land`, and Scryfall's `OR` binds *looser* than implicit
  AND. Three of 49 queries had it; a Shelob (BG) deck drafted Professional Face-Breaker
  `{2}{R}`. Pinned by `tests/test_theme_taxonomy.py`.
- **An `otag:` alternative has no local equivalent.** `theme_match` reproduces the Scryfall
  queries for strict mode, but an oracle tag cannot be reproduced, so the rule silently falls
  back to a literal that may match nothing. Five rules were dead this way. Guarded by
  `test_no_theme_rule_is_dead`.
- **Empty `color_identity` is not "colourless-safe".** Fetchlands have `ci=[]` and produce no
  mana, so `id<=WB` admits every fetch in Magic.
- **Two structures that must agree, only one of which is tested.** The strict theme branch was
  tested and correct; the Scryfall branch had no test and carried a dead `slot` variable.
- **`x or DEFAULT` instead of `x is None`** — has bitten this repo repeatedly (rank 0,
  `targets={}`, `max_age_days=0`).

---

## 7. Open, in rough priority order

1. ~~**Verify the two UI panels visually.**~~ **Done 2026-08-18** — end to end, against a
   real saved import (Silverquill, job `b98bc2fbe6924e7e`, the only deck on disk carrying
   these stats): both panels render with live figures. Still **no screenshot** — the Browser
   pane would not composite again, so the evidence is the rendered DOM text, not an image.
   Neither panel is backfilled on load (deliberate: it would make deck-page loads wait on
   EDHREC), so they appear on newly built/imported decks only — confirmed, 0 of the 168
   pre-existing decks show them. Verifying this is what turned up the labelling defect in §9.
2. **Partner decks cannot be BUILT, only analysed.** `BuildRequest.commander_name` is a
   single name and there is no second-commander UI. 6.6% of corpus decks are partner decks.
3. **~94 commanders (18.8%) still detect no theme.** Mostly partners and value piles
   (Progenitus, Karona, Nin) that genuinely have no archetype — deck-context themes is the
   right answer there, not more patterns. Widening existing patterns was measured at only
   ~5 more commanders.
4. **`etb` and `chaos` local rules are newly written** and less battle-tested than the rest.
   `chaos` is the one theme whose *Scryfall query* is also weak (no `otag:` to lean on).
5. **Curve deviation is +0.10 vs baseline** — effectively closed, but the theme and role
   paths are still deliberately not curve-aware. Reasoning is in `_draft_slot`.
6. **The strict arm's roster under-represents the revived themes** — only 2 of 20 commanders
   touch one, so `mean_weakest_theme_cards` understates their effect. Extending the roster
   invalidates the committed baseline, so it needs a fresh baseline pair.

---

## 8. Operational notes

- Local LLM offload: `python scripts/offload.py docs/SPEC_x.md out.py --model qwen3:14b`
  against llama-swap on `127.0.0.1:8010`. **Every draft in this series carried real bugs** —
  an invented `theme_match` API, a docstring placed after `from __future__` (four times),
  `from typing import list, dict`, a stubbed-out central statistic. Specs live in
  `docs/SPEC_*.md`; tests are written **from the spec**, never from the draft.
- If llama-swap is down: `E:\llama\start-llama-swap.bat`. **Tear down anything you start** —
  it holds GPU memory.
- Scryfall throttles hard under a sweep. `builder_bench` defaults `--rate-delay 0.35`; raise
  it and `--pause` if you see `[rate limit]` lines, and check `padded_slots` is 0 before
  trusting a run.
- `CLAUDE.md` is **gitignored** — edits to it stay on this machine.

---

## 9. The verdict labels were describing a different statistic (2026-08-18)

Found while closing §7.1, by the §4 method: the panel asserted something, so it got measured.

`lift_stats` classifies a deck on a 2x2 of (synergy delta, spread delta), both cut at
**population medians** — so every verdict is *relative to other decks*, and none of them is
an absolute statement. `off-plan` is the residual quadrant (below the median on both axes),
and StepDeck rendered it as **"Unfocused · few cards lean on what this commander rewards"**.

Measured over the **238 corpus decks with a cached EDHREC page** (offline — a deck with no
cached page is skipped, so no fetch can distort the run):

| verdict | n | share | median staples% | median synergy | median Δsyn |
|---|---|---|---|---|---|
| focused-with-spice | 62 | 26.1% | 88.2 | 24.5 | 16.4 |
| **off-plan** | **59** | **24.8%** | **82.2** | 10.6 | 4.8 |
| brew | 46 | 19.3% | 77.0 | 15.3 | 8.9 |
| on-rails | 41 | 17.2% | 98.4 | 32.1 | 20.1 |
| insufficient-data | 30 | 12.6% | 78.2 | 6.2 | −2.2 |

Of the 59 decks labelled "few cards lean on what this commander rewards", **80% sit ABOVE
their commander's page median on synergy** and **80% have ≥70% of their measured cards on
positive lift**. Its median `staples_pct` of 82.2 is *higher* than `brew`'s 77.0. The panel
also contradicted itself two lines apart — "few cards lean on what this commander rewards"
sat directly above "**81.2% on-theme**" on the verification deck.

**The classifier was right both before and after.** Nothing about the maths, the thresholds
or the calibration changed, and `off-plan` stays as the internal name (it is accurate as a
*relative* term — including in the standing "generated decks still mostly rate off-plan"
finding, which means "less commander-leaning than a typical human list" and still holds).
Only the user-facing wording moved: **"Relaxed build · evenly on-theme, leaning on the
commander less than most decks do."**

Guarded by two new tests in `test_lift_stats.py`, which parse the `VERDICTS` map out of
`StepDeck.jsx` rather than restating it:
- `test_every_verdict_has_a_panel_entry` — the same silent lock-step failure as the theme
  taxonomy; a verdict with no entry renders as a bare em-dash and the panel still draws.
- `test_off_plan_wording_does_not_claim_the_deck_lacks_synergy` — a phrasing test, because
  here the *wording* was the defect.

**The general trap: a label on a population-relative bucket reads as an absolute claim.**
`brew`'s "using the commander as a backbone for something else" (median 77% on-theme) is the
next-weakest and was left alone; it is defensible, but it is the same shape.

---

## 10. The manabase was never measured for SIZE (2026-08-18)

Found by running the seven decks in the user's own Archidekt folder through `compute_stats`.
One (Simic, Vorel) came back with **27 lands** — which looked like a fault and was not: it
runs 11 ramp sources, so 38 total. Checking that is what exposed the gap.

`deck_quality` measured the curve and whether the mana is the right **colours**. Nothing
measured whether there is **enough mana at all**. A 27-land deck with 11 ramp and a 27-land
deck with **zero** ramp produced identical `quality` blocks — and the second one cannot
function.

`assess_mana_base(deck)` → `{lands, ramp, sources, verdict, ok, notes}`, hung off
`deck_quality_block` so every path gets it from one place. `ramp_count` delegates to
`collection_pool.classify` rather than re-deriving "what is ramp" — a second definition
drifting from the first is this repo's most-repeated bug (`tags.py` vs `profile.py`, the two
theme branches), and that classifier is already net-mana-aware, so a `{1},{T}: Add {B}`
filter correctly counts zero.

**Calibrated over 459 corpus decks** (95–101 cards, ≥95% of names resolved, excluding **4
rows the corpus fetched without their manabase** — a landless 102-card "deck" is a bad
scrape, not a bad deck, and leaving them in dragged the low tail):

| | p05 | p10 | p25 | median | p95 |
|---|---|---|---|---|---|
| lands | 30 | **32** | 34 | 36 | 40 |
| ramp | 2 | 5 | 8 | 11 | 21 |
| sources | **38** | 40 | 44 | 47 | 61 |

`LOW_LANDS = 32` (p10), `MIN_SOURCES = 38` (p05).

**BOTH halves must fail before a deck is called short, and getting that wrong was the bug
this shipped with.** Testing `sources` alone looks equivalent; it flagged a **35-land** deck
as short because it runs 2 ramp, and 35 lands is the *25th percentile* — an ordinary
manabase attached to a deck that simply does not ramp, which is a playstyle. The measured
justification for the third verdict: **10.9% of real decks run under 33 lands and 68% of
those clear 40 sources**, so a low land count is usually a choice ramp pays for. Those are
reported as `ramp-dependent` — a description of how the deck plays, styled amber, not red.

Firing rate over the corpus: **ok 91.3% · ramp-dependent 5.7% · short 3.1%** (14 decks, e.g.
30 lands + 4 ramp). On the user's seven: five `ok`, Vorel `ramp-dependent`, Kaalia `short`
(31 lands + 6 ramp at average MV 3.63).

### `_backfill_quality` treated an incomplete block as a finished one

Same load-bearing gap as §9's lock-step: it early-returned on any truthy `stats.quality`, so
a deck built after `curve`/`colors` landed but before `mana` kept its old block forever and
the new row silently never rendered — only decks with NO block at all were backfilled. It
now recomputes unless every key in `_QUALITY_KEYS` is present. Only 1 deck on disk was in
that cohort today (168 have no block and backfill fully), but the class bites on every future
key. Pinned by `test_a_stale_stored_quality_block_is_recomputed_on_load`.

Suite 958 → 966.

---

## 11. The cut pool: four defects in the same 260 lines (2026-08-19 → 08-20)

`ratings/redundancy.py` decides which cards the advisor offers to CUT. Four things were
wrong with it at once, and they are worth reading together because three of them are the
same *shape*: a claim the measurement did not support.

### 11.1 The calibration checker could only agree with itself

`scripts/role_targets.py --check` had always said "ROLE_TARGETS is current". It could not
say anything else: `measure()` stopped after `DECKS = 120` corpus decks, so the checker
re-measured the constant against the same sample the constant was generated from.

The corpus is now 499. Over all of them exactly one role moves — **`tutor` 2 → 4**, confirmed
a population fact by three disjoint thirds each independently giving 4.0. Tutors were judged
against half their real target: **13.8% → 10.6%** of every cut suggestion, pool changing on
**16%** of decks. `DECKS = None` now means all of them, and `--limit` is deliberately not the
default, because the default is what the checker runs.

> **General lesson.** A calibration checker has to be *able* to disagree with the baked value.
> If it re-derives under the same sample, cap, seed or filter that produced the constant, it
> is a tautology wearing a test's clothes.

### 11.2 S10 — `ROLE_TARGETS` judged every deck against one population

A deck that plays to a role as its PLAN read as over-supplied in exactly the thing it was
trying to do. `counterspell`'s population target is **3 supply units — the weight of a single
card**, because the median corpus deck runs zero; the 24 corpus decks that actually ARE
spellslinger decks supply a p60 of **12** (individuals at 6, 12, 15, 27). So each was scored
3x–9x over and its interaction became the cut pool. That is how a Prismari deck was told to
cut **Flusterstorm and Mental Misstep**.

`ARCHETYPE_ROLE_TARGETS` measures the same p60 per archetype
(`scripts/archetype_role_targets.py`; `--check` diffs, `--audit` prints every candidate cell
and the gate that rejected it). Three gates, all load-bearing:

| gate | rejects |
|---|---|
| ≥20 decks carry the theme | tribal_dragons/elves/warriors cells whose halves disagree by 8.5–9.0 |
| **both halves** independently clear the population target | `draw_matters` draw (27/14), `chaos` counterspell (6/0), `theft` wipe (0/6) |
| margin of ≥3 supply units | `counters` ramp (15 vs 14), `tokens` finisher (4 vs 2) |

Split-half disagreement by sample size — this is what picked 20:

    n >= 30      18 cells   mean |A-B| 1.86   max  4.5
    20 <= n < 30 24 cells   mean |A-B| 3.04   max 13.0
    12 <= n < 20 29 cells   mean |A-B| 3.84   max  9.0
    n < 12       28 cells   mean |A-B| 4.45   max 34.0

Gate 2 is per **(theme, ROLE)**, not per theme: `draw_matters` is unstable on `draw` and
rock-steady on `counterspell` (9/9), and a theme-level gate would throw the good cell away
with the bad one.

**Measured at k=6 over the 106 corpus decks carrying an overridden archetype:** cut pool
changes on **52 (49%)**, own-plan cut slots **64.0% → 33.8%**, removal 7% → 16%.

**The residual 33.8% is correct and must not be driven to zero** — a deck running 27
counterspells against a target of 12 IS over-served. Pinned by a test.

**The contract is plain strings, because the detector is in the other process.**
`deck_themes` lives in Forge; the engine runs on :8020 without Forge on its path. So
`targets_for` is *told* the archetypes and ignores unknown names. Only
`scripts/archetype_role_targets.py` imports both, offline, to emit a table of strings.

### 11.3 S11 — `card_impact` never moved off the popularity rule

`assess_card` kept calling `advisor._weakest_cuts` for six days after the advisor stopped, so
the one route a user reaches interactively answered by displacing the deck's most obscure
card. On the corpus Shelob deck that pool is *Supper for Spiders / Gloomwidow's Feast / Eaten
by Spiders*.

Measured over 40 (deck, card) cases, full-fidelity store, `cut_pool=3`, `runs=200`:
**recommended cut changes 95%, final verdict changes 30%.**

Its reason line also said *"the weakest slot it beat"* — never what was measured, since the
pool was least-played. `_cut_sentence` now names the actual over-supplied role, **and says so
when there is none** rather than dressing the tiebreak up as redundancy.

### 11.4 S12 (OPEN) — the score is silent on 9% of decks, and the obvious fix is wrong

`oversupply / (1 + within_role)` scores every card **0.0** when a deck over-supplies nothing,
so ordering falls entirely through to the tiebreak — least-played first, the rule the module
exists to replace. (Roleless cards are still protected, so it is "least-played card carrying
a role", not pure popularity.) **45/499 decks (9.0%)**, 40 with all six slots at 0.0, and
**14.4% of all cut slots corpus-wide**.

It is a **compounding regression from two changes that each measured well**, because raising
a target is exactly what makes "nothing is over-supplied" more likely:

    original builder-slot targets      19  (3.8%)
    p60 population      (2026-08-14)   38  (7.6%)
    + archetype         (2026-08-19)   45  (9.0%)

**Prototyped and rejected — do not retry blind.** Un-clamping `max(0.0, supply - target)` and
ranking by raw headroom is surgical and moves 38/45 degenerate decks, but (1) targets are
integers and supply is usually integral, so roles sit *exactly* at target and headroom ties at
0.0 anyway (four-way on Shelob), and (2) the order then falls to `within_role`, which
**inverts** as a cuttability proxy: low `within_role` means a hybrid doing other work, which
at-target means the deck's THEME card. It promoted two spiders in the spider deck. Inverting
only in the degenerate case makes the ordering discontinuous at zero.

The likely real answer: the **caller** must be told there is no redundancy signal and change
what it does. `card_impact._cut_sentence` does that for one consumer.

### 11.5 S13 (OPEN) — a fixed per-card role strength makes targets granular

`card_roles` returns a flat **3.0** for `counterspell` and `wipe`, so supply moves in
whole-card steps and the target can only sit on a card boundary. `counterspell`'s target of 3
literally means "one card", so any deck with two counterspells is 3.0 over — outranking a role
that is modestly but genuinely over-served. Landfall deck `archidekt-13708248` has draw 0.5
over and counterspell 3.0 over, so it is offered *Flusterstorm*. S10's table fixes this only
where the archetype is in it.

**Suite 1047 → 1064.**
