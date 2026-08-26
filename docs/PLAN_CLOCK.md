# Plan — make the clock able to see a win (2026-08-21)

**Read this with [`HANDOFF.md`](HANDOFF.md) (what changed and what it measured) and
[`ROADMAP.md`](ROADMAP.md) (the shortfall map).** This file is forward-looking: it says what
to build next, why, in what order, and — just as importantly — **what not to rebuild**,
because several of the obvious moves have already been measured and rejected.

Every number here was measured against `corpus/decks` (297 bracket-labelled decks, unless a
later dated note says otherwise — **grown to 546 as of 2026-08-26**, see §1.1 and Phase 3's
re-sweep note; historical numbers below are left as measured at the time, not rewritten).
Nothing is an estimate unless it says so.

---

## 1. The goal, and the one number that serves it

The project's goal is **casual bracket 1–3 gauging: "is this deck fun and on-level for my
pod"**. The output that answers it is the bracket estimate. Its current state, measured at the
app's real horizon (`scripts/bracket_accuracy.py`, runs=120, turns=12, no combo gate):

| metric | now | accept (Phase 5) | best constant |
|---|---|---|---|
| bracket-exact, all 297 | **53.2%** | ≥60% | 32.7% |
| within-one, all 297 | **91.6%** | ≥95% | — |
| **B1–3 exact** (the goal band, 269 decks) | **56.1%** | — | 36.1% |
| B1–3 within-one | **91.1%** | — | — |
| signed bias | **−0.09** | — | — |

Confusion — rows are the builder's own label, columns the engine's estimate:

```
         1     2     3     4     5     n   recall
  B1    35    31     7     6     0    79   44.3%
  B2    27    62     3     1     0    93   66.7%
  B3    10    29    54     4     0    97   55.7%
  B4     0     1     9     7     0    17   41.2%
  B5     0     0     0    11     0    11    0.0%
```

The estimator is doing real work — roughly +20 points over the best constant, with essentially
zero bias. It is also short of its own accept bar, and **Section 2 explains why more
threshold-fitting will not close the gap.**

### 1.1 — the within-one shortfall is measurably label noise, not an engine gap (2026-08-26)

Re-ran the harness fresh (nothing had moved it since the number above — still 272/297, 91.6%
exactly) and, instead of re-litigating the already-closed B2/B3 boundary, read the two
`--json`-dumped miss classes that actually make up the within-one gap: **B3 labels the engine
puts at B1** (10 decks) and **B1 labels the engine puts at B3/B4** (13 decks).

**All 10 of the B3→B1 misses already carry `bracket_plays_up: true`.** Every one has 0 Game
Changers and a thin manabase (68-80% colour consistency) — exactly the honestly-flagged
Exhibition/Core boundary this project decided, with evidence, is unresolvable from the card
list alone. Nothing new here; it confirms the existing decision rather than reopening it.

**The B1→B3/B4 misses are a different, previously-unconnected finding.** 10 of the 13 hold at
least one Game Changer (`game_changers >= 1`) and the engine's ONLY reason is
`"N Game Changer(s) -> Bracket 3/4"`. Verified against the live-resolved cards, not assumed —
every flagged card is a genuine, WotC-listed Game Changer (Rhystic Study, Gaea's Cradle, The
Tabernacle at Pendrell Vale, Field of the Dead, Bolas's Citadel, Farewell, Seedborn Muse — no
false positives, the same check `STATUS.md` already ran once on Ancestral Recall/Dockside/
Jeweled Lotus and found clean). **Per the official bracket rules, holding any Game Changer at
all makes Bracket 1 or 2 impossible** — so a `# bracket: 1` label on a deck running Rhystic
Study is not a disagreement with the engine, it is a label that contradicts its own bracket's
published definition. This is the same "author labels are ~6% noisy" defect `STATUS.md`
already found on a smaller anchor set (4/37 B1 + 1/47 B2 anchors carrying a Game Changer) —
what's new is connecting it directly to THIS harness and measuring what it costs.

**Filtering out exactly those 13 self-contradictory labels — a filter that never looks at what
the engine predicted, only at whether the label is even possible under the bracket system's
own rules — moves within-one from 91.6% (284 decks short of the bar) to 95.1% on the remaining
284.** `scripts/bracket_accuracy.py` now reports both numbers automatically (the "excluding …
label(s) impossible under the rules" line). No engine code changed — this is a measurement,
not a fix, in the same spirit as `bracket.plays_up`: report what's actually true rather than
letting either an over-confident 91.6% headline or an artificially-depressed one stand
unexplained. **The accept bar (`≥95% within-one`, Section 7) is met on the internally-valid
label subset** — the remaining shortfall against the raw label set is now attributable to a
specific, named, mechanically-detectable class of label noise, not to an unmeasured engine
defect.

What this does NOT mean: it does not mean the corpus should be silently pruned of these 13
decks everywhere (`ratings.axis_separation`/calibration tables/etc. all still use the raw
label set on purpose — a deck's OTHER measured axes are unaffected by a stale bracket
self-label). It also does not close off future work on the two miss classes' own
substance — a genuinely thin-manabase B1/B2 deck that later gets more Game-Changer-style
signal, or a corpus refresh that catches labels drifting further out of date with the rules,
would still be worth re-measuring. It closes the specific question this section opened with:
whether anything was silently sitting unclaimed after S18/S21 landed. Nothing was; the ceiling
was already this close, and now it is measured rather than assumed.

### 1.2 — re-run on the grown corpus (546 decks): the 95% read was a little lucky, not wrong (2026-08-26)

The corpus grew from 297 to 546 labelled decks the same session (§Phase 3's re-sweep note) —
re-running `bracket_accuracy.py` on the full new set is the honest thing to do before trusting
§1.1's 95.1% figure going forward, rather than letting a smaller-sample number stand
unchecked just because it happened to clear the bar.

| metric | 297 decks | 546 decks | change |
|---|---|---|---|
| bracket-exact | 53.9% | 49.5% | **−4.4 pts** |
| within-one | 91.6% | 91.4% | −0.2 pts (noise-level) |
| signed bias | −0.08 | −0.16 | more negative |
| within-one, rule-consistent subset only | 95.1% (13 excluded) | **94.8%** (25 excluded) | −0.3 pts |
| B4 recall | 41.2% (7/17) | **53.2%** (33/62) | **+12 pts** |
| B5 recall | 0.0% (0/11) | 0.0% (0/55) | unchanged, now 5× the sample |

**Read this plainly, not defensively.** §1.1's "clears the bar on the rule-consistent subset"
finding does NOT survive unchanged — 94.8% is a hair under 95%, not over it. The honest
correction: the 297-deck read was real but was sitting close enough to the line that a
different, larger sample landed just the other side of it. Both numbers are true statements
about their own sample; neither is "the" number to quote going forward without a sample size
attached. The underlying MECHANISM §1.1 found (13→25 labels holding a verified real Game
Changer while self-labelling B1/B2, impossible under the rules) is unchanged and still the
right lens — it is the magnitude of "does filtering it close the gap" that moved from
"clears the bar" to "gets very close, not quite there."

**Two things did NOT move in the direction growing the corpus was meant to test, and one did,
for real.** Bracket-exact fell 4.4 points — the newly-harvested decks (found via
`-createdAt`/`-updatedAt` rather than the original `-viewCount` ordering that likely built
most of the first 297) may simply be a harder or differently-labelled population; not
diagnosed further this session, flagged for whoever next touches corpus composition. B2
recall fell from 68.8% to 61.1% over the same growth. Against that: **B4 recall rose 12
points** on 3.6× the B4 sample (17→62), which is a genuine, welcome signal that the B4 read
generalizes rather than being an artifact of a small anchor set. **B5 recall is still exactly
0%** — the engine has never once placed a real cEDH-labelled deck at Bracket 5 across 55 of
them now (was 11) — "engine usually says B4" fires on 96% of B5-labelled decks. This was
already known qualitatively (see the T2 duel meta-rating cEDH inversion documented
elsewhere), but this is the first time it's been confirmed at n=55 specifically against the
*static rule-based bracket estimate* rather than the T2 simulation layer — a real, now
well-evidenced gap, not touched by this session's other work.

**What this changes going forward:** keep citing within-one (not exact-match) as the metric
that matters, per §1's original reasoning — that conclusion is untouched. Do not claim the
≥95% accept bar is durably met; say "≈95% on labels that are even internally possible, close
enough to call it met within noise, not comfortably over the line." B5 recall is now the
best-evidenced remaining shortfall in this whole area and, unlike B2/B3, has NOT been swept
for a discriminating signal yet — a reasonable next target if this area gets picked up again,
though not attempted this session (this session's scope was corpus growth + verification, not
a new gate).

---

## 2. The blocking finding: the goldfish clock is bracket-invariant

A player described the B2/B3 line the way the format actually works:

> *A 2 takes seven or more turns to win unimpeded. A 3 accelerates — under perfect conditions
> it may win on turn 4–5, but it won't do so consistently.*

That is a claim about the **relationship** between the best draw and the typical one. The
calibration harness had swept `ceiling`, `kill_turn` and `consistency` *separately* — each came
back weak — and never tested the relationship. Tested now, over the 291 labelled decks that
resolve (horizon 14, runs 150):

| | B1 | B2 | B3 | B4 | B5 (cEDH) |
|---|---|---|---|---|---|
| **nut-draw kill turn** (mean of fastest decile) | 8.64 | 8.44 | 8.46 | 8.72 | **8.69** |
| average kill turn | 10.68 | 10.56 | 10.61 | 10.74 | 11.10 |
| kill rate inside horizon | 0.80 | 0.92 | 0.87 | 0.81 | 0.77 |

- **Every bracket's best draw lands on turn ~8.5, cEDH included.** A B5 deck holding **22 Game
  Changers** nut-draws at **8.92** — slower than the B1 mean. Real cEDH wins turn 2–4.
- Spread of the five bracket means: **0.28 turns**. Typical within-bracket stdev: **1.12
  turns**. The between-bracket signal is **four times smaller than the noise**.
- **0 of 291 decks nut-draw by turn 5.** The fastest in the whole corpus is **5.60**. Only
  **6.5%** get inside turn 7. The region the player's model describes is one the simulator
  never enters.
- Re-running the accuracy harness at 12 turns instead of 8 moves bracket-exact **52.9% →
  53.2%**. Doubling the simulated horizon changes one deck in three hundred.

### 2.1 The mechanism, and it is a single line

`RunStats.kill_turn` is assigned in exactly one place:

```python
# src/mythgauntlet/sim/tier0.py:348
if stats.kill_turn is None and damage >= cfg.goldfish_life:
    stats.kill_turn = turn
```

`damage` there is **cumulative combat damage** (the module docstring says so at line 16). So
every speed figure the engine produces — `avg_kill_turn`, `fast_kill_turn`,
`goldfish_kill_rate`, `nut_kill_rate`, and the Ceiling axis that reads them — is **combat
only**.

`sim/storm.py` and `sim/overrun.py` already model two non-combat kill shapes, but they feed
the **Ceiling score** through separate components (`go_off_component`, the overrun term). They
**do not set `kill_turn`.** So a storm deck that goes off on turn 4 still reports a nut-draw
kill turn of ~8.5.

Combos are worse: `two_card_combos` is an **input** the caller supplies from an external
Spellbook lookup. The engine never detects or executes a combo, so a deck that wins on turn 3
with a two-card loop is, to the clock, a pile of creatures that attacks slowly.

### 2.2 Why this reframes a recorded conclusion

`docs/engine/STATUS.md` concluded (2026-07-28, re-confirmed 2026-08-21 at larger n) that B2
and B3 are not separable, and attributed that to the **labels** — the author's intent and pod
context rather than a property of the 99 cards.

That attribution is no longer the best-supported reading. **A measurement that cannot separate
cEDH from Exhibition on speed is not entitled to conclude anything about B2 versus B3.** The
honest form is *"unresolvable **by this simulator**"* — a different and far more actionable
claim. The property may well be in the cards, exactly as the player describes.

---

## 3. What NOT to rebuild

Each of these was measured and rejected. Re-deriving them costs a session.

| idea | why not | evidence |
|---|---|---|
| Lift the `gc == 0` cap from 2 to 3 | The gate IS a rules misreading (Bracket 3 permits *up to* 3 Game Changers, it does not require any) — but placement branches on `floor == 1 and cap == 2` **exactly**, so widening the cap makes that branch stop matching and every zero-GC deck falls to `bracket = floor` — **Bracket 1 for everything**. The cap is not the binding constraint; the missing discriminator is. | `scripts/bracket_boundary.py` |
| Fit a B2-vs-B3 rule on current signals | Baseline "always say B2" **69.2%**; best single-threshold rule **70.0%** at 2–5% B3 recall; best two-signal rule **70.8%**. Every candidate is the majority class wearing a threshold. | n=130 (90 B2 / 40 B3) |
| Use `edhrec_log_rank` to place B1 vs B2 | It **works** — 76.1% against 64.8% for the shipped `manabase_P` rule, broad plateau, better balanced. **Invariant 4 bars it**: popularity is a prior, never a verdict, because a popularity-driven verdict recreates the static-calculator failure mode this engine exists to replace. It would rate a budget pile of staples up, an expensive brew down, and every card from a new set down regardless of power. | `scripts/bracket_boundary.py` |
| Un-clamp `oversupply` in `redundancy` (S12) | Prototyped; surgical; moves 38/45 degenerate decks — and makes the canonical case **worse**. Targets are integers so headroom ties at 0.0 anyway, and the order then falls to `within_role`, which *inverts* as a cuttability proxy at target. | ROADMAP S12 |

---

## 4. The work

### Phase 1 — teach the clock to see a non-combat win  ⟵ **1a+1b landed; B2/B3 via the clock closed 2026-08-24, target within-one instead**

This is the lever. Nothing downstream can move while the clock is flat.

**1a. Wire the existing go-off into `kill_turn` — LANDED 2026-08-24.** `sim/storm.py`'s
`go_off.earliest_turn` and `sim/overrun.py`'s alpha-strike detection used to only lift the
Ceiling *score* via a flat deck-level bonus; `RunStats.kill_turn` itself stayed combat-only.
New `sim/clock.apply_nut_kills(runs, cards, turns)` now lowers a run's `kill_turn` whenever
either detector fires earlier, evaluated **per run against that run's own mana/board curve**
(`RunStats.mana_available_by_turn`, and two new per-turn fields, `board_power_by_turn` /
`board_creatures_by_turn`, added to `RunStats` in `tier0.py` for this) rather than a single
deck-level average — a run's own draw quality decides how early its own engine could
plausibly come online, the same nut-draw philosophy `estimate_go_off`/`estimate_overrun`
already used, just resolved per run. Wired into the one shared pipeline
(`ratings/analysis.analyze_deck`, both the main `runs` and the pod-horizon `pod_runs`) and
into the acceptance-gate harness itself (`scripts/axis_separation.py`) — the two must not
drift, so the harness imports the same `apply_nut_kills` the app calls. `damage_by_turn` is
deliberately untouched (a non-combat kill is a different event the combat curve was never
modeling; rewriting it would invent combat damage that didn't happen). 1099/1099 tests green.

**Measured effect (corpus, `axis_separation.py --runs 150`, matching the plan's own
methodology):**

| | B1 | B2 | B3 | B4 | B5 |
|---|---|---|---|---|---|
| `nut_draw_turn` before | 8.64 | 8.44 | 8.46 | 8.72 | 8.69 |
| `nut_draw_turn` after | 8.90 | 8.29 | 8.38 | 8.67 | **8.26** |

**The specific inversion Section 2 flagged is fixed: B5 (8.26) is now faster than B3 (8.38.)**
It was slower before (8.69 vs 8.46). That's real movement, not noise — it survived both a
60-run and a 150-run pass at the same relative gap. **The gate is still not met**, though:
`nut_draw_turn`/`speed_gap` don't crack the top 4 signals by |d| at the B2/B3 boundary (both
sit under `tutor_density`'s 0.24), nowhere near the required 0.5. Expected — the plan called
1a "the cheapest possible first step," and only a minority of the zero-Game-Changer B2/B3
population runs a storm or overrun engine at all, so this pass can only move the decks that
have one. **1b (burn/direct damage) is very likely necessary before B2/B3 separation is
possible**, since it's the shape that reaches ordinary (non-combo) casual decks, not just
engine pieces.

**Also measured, and expected to be unchanged: `scripts/bracket_accuracy.py --runs 120
--turns 12` is byte-identical to the pre-1a baseline** (53.2% exact / 91.6% within-one / bias
-0.09, same confusion matrix). This is correct, not a bug: `ratings.bracket.estimate_bracket`
does not consume `nut_draw_turn`/`speed_gap`/`ceiling.score` as a B2-vs-B3 discriminator today
— that's precisely why Phase 3 (re-fit placement) is gated behind this section's acceptance
test in the first place. Fixing the signal without the gate passing, and without wiring it
into placement, should leave placement untouched. It does.

**1b. Burn and direct damage — LANDED 2026-08-24.** Unlike 1a (which only re-reads existing
best-case estimators per run), this reaches into `tier0._run_one` itself so an ORDINARY
(non-engine, non-combo) deck's real burn spells count, not just decks with a full storm
engine. Three additions, gated the same way `engine_active`/`engine_pending` already are
(one-turn delay after the payoff resolves — a documented rung-1 simplification, not a new
standard invented for burn specifically):
- `magecraft_damage`/`cast_damage` payoffs (Guttersnipe/Storm-Kiln class): new
  `dmg_engine_active`/`dmg_engine_pending` counters; every instant/sorcery cast while a payoff
  is active adds `dmg_engine_active` direct damage.
- `ritual_mana` (Dark Ritual class): now actually spendable — resolving one adds temporary
  ready `_Source`s (the same `temp` flag `sim/tier2.py` already used for this, now wired into
  T0's own turn loop too) that expire at the next untap, mirroring `game.py:412`'s exact
  pattern.
- `scaling_burn` (Fireball class): held OUT of the main greedy-cast loop (casting it the
  instant it's affordable would lock in X=0, per the documented "X spells are cast for X=0"
  policy) and given its own pass after every other spell has had first claim on the turn's
  mana — it then spends whatever mana is left over as X, the way a player actually plays one.

Verified by hand before trusting the corpus number: a dense synthetic deck (20 Mountains / 20
Guttersnipes / 20 Shocks) reliably kills by turn 6-8 via non-combat damage alone; the realistic
99-card version of the same test (1 Guttersnipe) mostly shows no burn damage at all, which
turned out to be pure draw variance (~17% chance of ever drawing a single copy across a game),
not a bug — worth recording since it looked exactly like a wiring failure at first glance.
1099/1099 tests still green.

**Measured effect (`axis_separation.py --runs 150`, 1a+1b together):**

| | B1 | B2 | B3 | B4 | B5 |
|---|---|---|---|---|---|
| `nut_draw_turn` (1a only) | 8.90 | 8.29 | 8.38 | 8.67 | 8.26 |
| `nut_draw_turn` (1a+1b) | 8.90 | 8.27 | 8.34 | 8.56 | **8.20** |

**The B5<B3 ordering fix from 1a holds and widened slightly (0.14 turns).** But **the B2/B3
gate is still not met, and 1b barely moved it**: `nut_draw_turn`/`speed_gap` still sit outside
the top 4 signals by |d| at B2/B3 (`game_changers` +1.19, `edhrec_log_rank` -0.54, `kill_rate`
-0.29, `tutor_density` +0.24 — unchanged from the 1a-only measurement to two decimal places).
**This is itself a real finding, not a null result to shrug off**: two independent, cheap,
correctly-wired non-combat-kill mechanisms (engine go-off + ordinary burn) both fail to
separate B2 from B3. The honest reading is that the zero-Game-Changer B2/B3 population in this
corpus mostly doesn't run either shape — B2-vs-B3 in practice looks less like "does this deck
have a faster non-combat kill" and more like the card-quality/tutor-density/interaction
signals already ranking above it. **1c (the combo question) remains open but should not be
assumed to close this gap either** — combos gate bracket placement directly already
(`can_go_off`/`combo_profile`) rather than needing a kill-turn route, and B2/B3 by construction
mostly excludes real combo decks (those push to B3+ regardless). Before investing in 1c's
larger integration cost (it needs real per-corpus-deck combo detection wired into the harness,
which `axis_separation.py` does not do today), it is worth weighing the plan's own §4 Phase 3
fallback now: **if B2/B3 does not separate with a working clock, within-one (already 91.6%,
target 95%) is the metric that can honestly move, and exact-match at that boundary may not be
reachable by construction.**

**1c. Decide the combo question explicitly.** Today `two_card_combos` is an input and the
bracket gate uses it. Options, in increasing cost: (i) leave it a gate and accept that the
clock never sees combo kills; (ii) let a supplied combo count *seed a kill turn* so speed
metrics reflect it; (iii) detect and execute combos in-sim. **Do not start at (iii).** Note
the honest-uncertainty invariant: a combo count the caller did not verify must not silently
become a fast kill turn — the engine already docks confidence for `combos and not
combos_checked`, and that must survive.

**1d. Alt-win cards** (Thassa's Oracle, Approach, Lab Man class). No `EffectVector` field
exists. Lowest priority — it is a small card population and a new semantics field is the
expensive kind of change.

**Acceptance gate — do not skip this.** The repo's own rule is that *no axis may influence a
bracket verdict until it demonstrates separation on the labelled anchors*
(`scripts/axis_separation.py`). Phase 1 is done when:

- `nut_draw_turn` separates the ladder at all — concretely, **B5's mean nut-draw must fall
  below B3's**, which it does not today (8.69 vs 8.46);
- **|Cohen's d| ≥ 0.5 at the B2/B3 boundary** on `nut_draw_turn` or `speed_gap`, measured on
  zero-GC decks (n≈130). Below that, do not proceed to Phase 3.

`nut_draw_turn`, `kill_rate` and `speed_gap` are already permanent signals in
`axis_separation`, so this re-tests for free.

**DECIDED 2026-08-24 — B2/B3 exact-match via the clock is closed for now; target within-one.**
1a and 1b both landed and are real, tested improvements (the B5<B3 inversion is fixed), but the
gate above is not met and two independent non-combat-kill mechanisms both failed to move it —
that is enough evidence, not a coin flip, so this is a decision, not an unmeasured guess:

- **Do not restart 1c hoping it fixes B2/B3.** The reasoning in the 1b write-up above still
  holds (combos already gate placement directly; B2/B3 mostly excludes real combo decks by
  construction). If 1c is picked up later, it should be justified on its own merits (an honest
  combo-aware kill_turn is a real gap regardless of B2/B3), not as another attempt at this gate.
- **Phase 3's B2/B3 attempt is shelved**, per the repo's own invariant that no axis drives a
  verdict without demonstrated separation — `nut_draw_turn`/`speed_gap` haven't earned a place
  in B2/B3 placement and should not be wired in.
- **Phase 3's B1/B2 refit is NOT blocked by this** — a different boundary, already separates
  well on signals that don't depend on the speed axis (`manabase_P` ships at d=+0.55;
  `edhrec_log_rank` works at d=-1.02 but stays barred by invariant 4). Untouched by today's
  finding either way.
- **Going forward, `within-one` (91.6% → target 95%) is the metric to chase, not bracket-exact
  at B2/B3.** Bracket-exact stays reported (it's an honest number), but a B2 deck estimated as
  B3 is a rounding error inside the casual band this project serves, not the failure mode that
  matters — sending someone to the wrong TABLE is. Any future work aimed at moving the accept
  bar should target within-one directly rather than re-attempting B2/B3 separation.

### Phase 2 — "how much interaction does it take to stop them"

The player's third axis, and the one the engine models least well. Today `resilience` is
`sim/tier1.compute_resilience`: **one board wipe at a fixed turn**, measured *through the
combat clock*.

What is wanted is closer to: *how many pieces of interaction must the table spend to stop the
win?* A deck that folds to a single counterspell is not the deck that needs three.

**Do Phase 1 first.** Measuring "what stops the win" is meaningless while the clock cannot see
the win.

**A diagnosed instance of exactly that blindness was fixed 2026-08-25, before the redesign
above.** `compute_resilience` called `sim.tier0.simulate()` directly and never received Phase
1a/1b's `apply_nut_kills` fix — the ONE place `ratings.analysis.analyze_deck`'s main `runs`/
`pod_runs` batches get taught to see a non-combat kill. So even after Phase 1 landed, a storm/
burn/overrun deck's resilience score was STILL measured against a combat-only `kill_turn`
that doesn't reflect how the deck actually wins: a synthetic storm-engine deck (granter +
burn payoff + ramp, no real attackers) reported **zero kills at any turn** — `clean_kill_rate:
0.0` — because the axis had no notion of its non-combat win at all, wipe or no wipe.

**Fixed**: `compute_resilience` now takes an optional `all_cards` (mirroring `analyze_deck`'s
own `sim_cards` + lead-commander shape) and calls `apply_nut_kills` on both the clean and
wiped run batches, exactly like the main pipeline. Verified live on the same synthetic
storm deck: `clean_kill_rate: 0.82`, `clean_avg_kill_turn: 8.21` (previously `None` /
undefined) — and, correctly, `wiped_avg_kill_turn` comes back **identical** to the clean
figure (`kill_delay_turns: 0.0`), because a board wipe destroys creatures, not a storm
engine's spells and mana. A wipe that cannot stop a combo must not read as having delayed
it, and now it doesn't. New tests: `tests/engine/test_clock.py` (`apply_nut_kills` had NO
direct tests before this — only indirect coverage via `analyze_deck`'s own integration path)
and two additions to `tests/engine/test_tier1.py`. 1248/1248 tests green.

**What that fix did NOT do**: it did not build the redundancy-of-wincon ablation measure
this section calls for. `resilience` still only models one disruption class (a board wipe) at
one fixed turn — the fix made that EXISTING measurement honest about non-combat wins; it did
not add the new "how many pieces of interaction" measurement below.

**The redundancy-of-wincon measure itself — BUILT 2026-08-25.** Full design in
`docs/SPEC_wincon_redundancy.md`; summary here.

Rather than a single "most important piece" ranking (the original sketch's own wording),
the real design question turned out to be that the deck's four non-combat kill mechanisms
(the same ones `apply_nut_kills` reads: storm granter, magecraft/cast-damage burn payoffs,
the overrun finisher, a scaling-burn finisher) **combine cards under three DIFFERENT rules**
— OR, capped-sum, and max — and a uniform "rank cards, remove the top N" approach silently
misreports three of the four. `sim/wincon_redundancy.analyze_wincon_redundancy` instead
re-runs the real `estimate_go_off`/`estimate_overrun` after each candidate removal and lets
the estimator itself decide, which is what makes the OR-combination case (two storm granters
— removing one is a complete no-op) come out right without special-casing it.

Cheap by construction: it reuses the SAME nut-draw mana curve and nut board `analyze_deck`
already computes for the Ceiling axis's own `go_off`/`overrun` figures — no new simulation
pass, just a handful more deterministic calls. Informational only, like `resilience_score`
— it does not feed `estimate_bracket` or `compute_ceiling`, so it did not need to clear
`axis_separation.py`'s Cohen's-d gate (that gate exists to keep an unproven signal out of a
VERDICT; this doesn't touch one).

**Verified two ways.** Nine synthetic tests (`tests/engine/test_wincon_redundancy.py`) pin
the exact combination-rule behaviour, including two non-obvious findings caught only by
actually running the module rather than hand-deriving expected numbers (a spec-writing
lesson worth naming): a lone cast-damage payoff can report `pieces_to_disable: None` when a
separate scaling-burn finisher is independently sufficient without it, and a SOLE granter
with no payoff at all can flip from "irrelevant" to "the whole plan" depending on whether a
scaling finisher's damage needs the storm copy multiplier to reach lethal. Then a full,
unmodified sweep of all **499 corpus decks** through the real `analyze_deck` pipeline: **zero
exceptions, zero out-of-range values** (a `pieces_to_disable` can never legitimately exceed
its own candidate count or fall below 1 — checked on every hit), and **79 decks (15.8%)**
have an applicable non-combat wincon — consistent in magnitude with Phase 1b's own finding
that only a minority of the population runs these mechanisms at all. Spot-checked by hand
against 8 individual real decks (`mythgauntlet analyze <corpus deck> --runs 100`), including
a genuinely useful real finding: one deck runs eight named overrun-class finishers but only
needs its single BEST one removed to stop the alpha strike on that board width — the other
seven are backup that never independently mattered.

**A real bug caught in that spot-check, not in the synthetic tests**: `cli.py`'s first
attempt printed `f"wincon redundancy [{role.role}]: ..."`, and Rich's `Console.print`
interprets a literal `[word]` as a markup tag — an unrecognised one is silently swallowed
with no error at all, so the live output read as "wincon redundancy : 1 of 1 piece(s)...",
the role name vanishing without a trace. Caught only by reading the actual terminal output
against real corpus decks; no synthetic unit test would have caught it, since none of them
render through `Console.print`. Fixed by using parentheses instead of brackets.

**Still genuinely open, and deliberately not attempted**: a `ritual_mana` role (Dark Ritual
class) is out of scope by design — ablating a mana-producing card would invalidate the
cached mana curve this module holds fixed, and modeling that correctly needs a fresh
`tier0.simulate()` per candidate, not a deterministic re-check. This reports a CARD COUNT,
not a turn delay — "3 pieces stop the fast plan" does not say what the deck's fallback clock
looks like after those 3 are gone; translating "goes_off flips False" into a turn figure
the way `kill_delay_turns` does would need knowing what the residual clock actually is, which
is real, separate follow-on work. Neither gap blocks what shipped: both are named in
`docs/SPEC_wincon_redundancy.md`'s own pitfalls section rather than silently approximated.

### Phase 3 — re-fit placement · ALREADY RUN, and the answer is recorded, not open

**Correction, 2026-08-25: this phase reads as "not blocked, ready to pick up" and that framing
is stale.** `scripts/bracket_boundary.py` has already been run and its own docstring is a
completed post-mortem, not a live tool waiting for a first attempt:

- **B1/B2**: a single threshold on `edhrec_log_rank` scores **76.1%** against the shipped
  `manabase_P` rule's **64.8%** — 11 points, on a broad plateau, better-balanced recall. **Not
  shipped, on principle, not for lack of trying**: Invariant 4 bars any popularity-driven
  verdict, because that recreates the static-calculator failure mode this engine exists to
  replace. The correction that DID land from this run is documentary, not code: a prior claim
  that "popularity wouldn't have helped" was false, and now says so.
- **B2/B3, zero Game Changers** (n=130, 90/40): every candidate rule measured is "always say B2"
  wearing a threshold — best two-signal rule reaches 70.8% against a 69.2% baseline, with B3
  recall in the 2-5% range. This independently reconfirms the same conclusion this file's own
  §2 already reached from the clock-invariance angle: **the B2/B3 boundary is not resolvable
  from the 99 cards**, full stop, by two unrelated measurements now.
- **A separate, real finding the same script surfaced**: `bracket.estimate_bracket`'s
  `gc == 0 -> floor 1, cap 2` gate IS a misreading in isolation — Bracket 3 permits *up to* 3
  Game Changers, it does not require any, so the gate turns a ceiling into a floor, and 40 of
  97 real Bracket-3-labelled decks hold zero Game Changers and get capped at 2. **But lifting
  the cap alone makes it WORSE** (the placement code branches on `floor == 1 and cap == 2`
  exactly, so widening the cap makes every zero-GC deck fall through to `bracket = floor` —
  Bracket 1 for everything). Confirmed still the current shipped behaviour
  (`ratings/bracket.py:196-197`) as of 2026-08-25, and correctly so: the cap was never the
  binding constraint, a working discriminator for WHERE in [1,3] a zero-GC deck sits is, and
  none has been found. This is exactly what `plays_up` (Phase 4) exists to communicate honestly
  instead of guessing.

**Nothing here is open work waiting for a next session.** If a future attempt wants to revisit
B2/B3, it needs a genuinely new signal not yet swept — re-running the existing sweep will
reproduce the same "always say B2" result, not a new one.

**RE-SWEPT AT 60% MORE STATISTICAL POWER, 2026-08-26 — the null result gets STRONGER, not
weaker.** The standing caveat on this whole section was always "a moderate effect (d≥0.5)
would have surfaced at n=130; a small one cannot be ruled out." That caveat is now closed by
data, not by more reasoning: the corpus was grown specifically to test it (Archidekt's
`edhBracket` server-side filter, `fetch-decks --bracket N --order=-createdAt/-updatedAt`,
297→546 labelled decks, +84%; B4 17→62, B5 11→55 — the two brackets with the thinnest
evidence before). Re-running `bracket_boundary.py` on the larger corpus:

- **B2/B3, zero Game Changers is now n=209 (161 B2 / 48 B3), up from n=130.** The baseline
  ("always say B2") is **77.0%**. The best SINGLE-threshold rule (`low_curve_share ≥ 0.762`)
  reaches 77.5% — a fraction of a point. Every two-signal rule tops out at EXACTLY 77.0%,
  matching the baseline to the decimal, not beating it at all. More data made the effect
  SMALLER, not larger — the opposite of what a real-but-underpowered signal would do.
- **B1/B2 reproduces almost exactly**, which is itself a useful check on measurement
  stability: `edhrec_log_rank` scores 75.5% now vs 76.1% at n=84 (barred by Invariant 4,
  unchanged); the shipped `manabase_P` scores 63.9% now vs 64.8% before (essentially the same
  rule, same conclusion, still shipped). Two new candidates surface this time — `consistency`
  (63.9%) and `low_curve_share` (62.1%) — both barely above the 59.9% baseline, not close to
  the b1/b2 discriminators that matter; noted, not pursued.

**Consequence: B2/B3 is not "underpowered," it is measured twice at two different sample
sizes with the same answer both times.** This was the one open thread PLAN_CLOCK's own
Section 1 caveat left genuinely unresolved-by-data (as opposed to unresolved-by-effort); it
no longer is. Do not revisit B2/B3 on the strength of "maybe a bigger corpus would help" —
the bigger corpus is the thing that was tried, and it didn't.

**Target the right metric, which was already the conclusion above independently reached from
Phase 2's own angle.** Exact-match rewards guessing the annotator; **within-one (91.6% → 95%)**
is the metric that can honestly move, and stays the accept bar going forward.

### Phase 4 — surface it honestly

The precedent is already shipped: `bracket.plays_up` renders as an amber line under the
bracket ("Sits on the Core / Upgraded line"), firing on **42% of the labelled corpus
(124/297)**, 30 of which their builders called Bracket 3. If a boundary stays unresolvable,
**say so in the UI rather than inventing precision** — and note that the flag existed,
API-returned and CLI-printed, for 24 days before anything rendered it. Check the UI actually
reads what the engine emits.

**Audited 2026-08-26.** `SimStrengthPanel.jsx` — the panel this precedent was actually about
— already reads essentially every `power_profile` field the engine emits (checked by
enumerating all ~37 keys against the component's own references): consistency, resilience
+ its wipe/kill-rate detail, interaction + its removal/counter/wipe breakdown, ceiling, pod
+ its close-turn/close-rate/via-finisher detail, speed, semantics coverage, go-off,
overrun-alpha, wincon-redundancy, all four bracket fields including `plays_up`, game changer
names, bracket reasons, and the combos/insight blocks. Nothing there was missing.

**One real gap found on a DIFFERENT surface the precedent never covered: the compact "⚡ Bn"
measured-bracket badges on History and RecentDecks tiles read `bracket_estimate`/
`bracket_label` from the same cached `power_profile` but silently dropped `bracket_plays_up`
— so a deck the engine itself flags as sitting on an unresolvable boundary could show a bare
"B2" on those tiles with no honesty marker at all, the exact failure this phase exists to
catch, just one layer removed from where the precedent was checked before.** Fixed:
`/api/decks` now includes `measured_plays_up` (server.py); both badges append a small amber
`↗` and extend their tooltip with the same "sits on a bracket boundary..." wording the main
panel uses, so a user hovering either surface gets the same honesty, not a stripped-down one.
Verified live against a real on-disk deck already flagged `bracket_plays_up: true`
(Kaalia of the Vast, job `a95811cc95974372`) — the History tile shows `⚡ B2↗` distinct from
ordinary `⚡ B3` tiles elsewhere in the same list, tooltip text confirmed via DOM read.
3 new tests in `tests/test_deck_list_route.py` (a route neither History nor RecentDecks had
any prior test coverage for at all).

---

## 5. The harnesses

| script | what it answers | notes |
|---|---|---|
| `scripts/bracket_accuracy.py` | Does the estimate match the builder's label? | `--turns` defaults to the app's `DEFAULT_ANALYZE_TURNS`. `--combos N` **declares** combos; it is an input, not a detector — passing a value fabricates combos on every deck. |
| `scripts/axis_separation.py` | Which signals separate adjacent brackets? | Spearman rho + Cohen's d per pair. The standing calibration gate. |
| `scripts/bracket_boundary.py` | What threshold rule places a zero-GC deck? | Sweeps both directions, reports plateaus and the majority baseline. |
| `scripts/builder_bench.py` | Does the builder make good decks? | Two arms (Scryfall / `--strict`). |
| `scripts/advisor_bench.py` | Does the advisor improve decks? | Note: the sim's axis delta **cannot see** cut-pool quality defects. |

Corpus: **297 of 499 decks carry `# bracket: N`** (79/93/97/17/11), self-reported by their
builders on Archidekt. Noisy but the right target — the pod is made of people who label decks
that way.

---

## 6. Traps specific to this repo

1. **Invariant 4 — popularity is a prior, never a verdict.** It will keep looking like the
   best available signal. It is barred on principle, not because it is weak.
2. **`X or 0` on an optional number.** Fixed three times now (`edhrec_rank or 10**9`,
   `avg_kill_turn or 0.0`). A missing measurement is not zero — zero is usually the *best*
   value, so the failures read as the strongest decks.
3. **A calibration checker must be able to disagree with the constant it checks.**
   `role_targets.py --check` re-measured under the same 120-deck cap the constant came from
   and could only ever agree with itself.
4. **Harness fidelity.** `bracket_accuracy` scored `turns=8` while the app runs 12. Match the
   app's configuration or the number is about nothing.
5. **Sweep direction.** Signals do not share a sign. A one-direction sweep reports every
   rising signal as a degenerate "always say the majority" rule.
6. **Bash heredocs mangle backslashes** (`\1` → 0x01, `\b` → 0x08) and the damaged file still
   parses. Write Python with the Write tool; verify with a control-byte scan.
7. **Read the real output.** The faithfulness gate had **seven** false positives, every one
   found by reading what the model actually wrote, none predicted from the design.

---

## 7. Definition of done

- `nut_draw_turn` orders the ladder monotonically, and B5 is faster than B3.
- |d| ≥ 0.5 at B2/B3 on a speed signal, or a recorded decision that it is unreachable and the
  `plays_up` banner is the final answer.
- Bracket **within-one ≥ 95%** on the labelled decks; exact-match reported but not chased.
  **CLOSE, not comfortably met — re-measured 2026-08-26 on the grown 546-deck corpus (§1.2)
  after §1.1 first reported 95.1% at n=297.** Filtering to labels that don't contradict their
  own bracket's rules (no B1/B2 label holding a Game Changer) gives 94.8% on 521 decks at the
  larger, more trustworthy sample — a hair under the bar, not over it. The gap is still a
  NAMED, measured, mechanically-detected class of label noise rather than an unexplained
  engine shortfall (that finding survives), but do not describe the accept bar as "met."
  On the raw label set (no filtering) it's 91.4%, essentially unchanged from 91.6% at n=297.
  B5 recall is 0% at n=55 (was 0% at n=11) — the best-evidenced remaining shortfall in this
  area, not yet swept for a discriminating signal.
- Every claim in the UI traceable to a measured field — the `plays_up` precedent. **Audited
  2026-08-26** (PLAN_CLOCK Phase 4): `SimStrengthPanel.jsx` already covers essentially every
  `power_profile` field; found and fixed one real gap on a different surface (History/
  RecentDecks measured-bracket badges silently dropped `bracket_plays_up`).
- `python -m pytest tests -q` green (1099 at the time of writing).
- Phase 2's redundancy-of-wincon measure — done informationally (not a bracket-placement
  metric, so no accept bar applies): `sim/wincon_redundancy.py`, `docs/SPEC_wincon_redundancy.md`,
  9 tests, corpus-wide sweep clean on all 499 decks (2026-08-25).
