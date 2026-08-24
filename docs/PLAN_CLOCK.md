# Plan — make the clock able to see a win (2026-08-21)

**Read this with [`HANDOFF.md`](HANDOFF.md) (what changed and what it measured) and
[`ROADMAP.md`](ROADMAP.md) (the shortfall map).** This file is forward-looking: it says what
to build next, why, in what order, and — just as importantly — **what not to rebuild**,
because several of the obvious moves have already been measured and rejected.

Every number here was measured against `corpus/decks` (297 bracket-labelled decks). Nothing is
an estimate unless it says so.

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
combat clock* — so it inherits Phase 1's blindness entirely, and it only models a wipe.

What is wanted is closer to: *how many pieces of interaction must the table spend to stop the
win?* A deck that folds to a single counterspell is not the deck that needs three. Sketch:
re-run the sim removing the 1st, 2nd, 3rd most important piece of the winning line and measure
the kill-turn delay per piece — a redundancy-of-wincon measure rather than a wipe-recovery
measure.

**Do Phase 1 first.** Measuring "what stops the win" is meaningless while the clock cannot see
the win.

### Phase 3 — re-fit placement, only after the Phase 1 gate passes

Use `scripts/bracket_boundary.py`. It already enforces the discipline: both sweep directions,
plateau-not-peak, and a printed majority-class baseline. Re-fit B1/B2 and attempt B2/B3.

**Target the right metric.** If B2/B3 remains unseparable even with a working clock, then
Phase 5's *"≥60% bracket-exact"* is partly unreachable by construction and **within-one
(91.6% → 95%) is the metric that can honestly move**. Exact-match rewards guessing the
annotator; within-one rewards not sending someone to the wrong table.

### Phase 4 — surface it honestly

The precedent is already shipped: `bracket.plays_up` renders as an amber line under the
bracket ("Sits on the Core / Upgraded line"), firing on **42% of the labelled corpus
(124/297)**, 30 of which their builders called Bracket 3. If a boundary stays unresolvable,
**say so in the UI rather than inventing precision** — and note that the flag existed,
API-returned and CLI-printed, for 24 days before anything rendered it. Check the UI actually
reads what the engine emits.

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
- Bracket **within-one ≥ 95%** on the 297 labelled decks; exact-match reported but not chased.
- Every claim in the UI traceable to a measured field — the `plays_up` precedent.
- `python -m pytest tests -q` green (1099 at the time of writing).
