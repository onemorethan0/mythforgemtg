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

### Phase 1 — teach the clock to see a non-combat win  ⟵ **in progress, see 1a below**

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

**1b. Burn and direct damage.** The `EffectVector` already carries `scaling_burn`,
`cast_damage`, `magecraft_damage` and `ritual_mana`. The semantics layer can see non-combat
damage; the clock throws it away. Feed it into the same damage accumulator that line 348
tests.

**1b. Burn and direct damage.** The `EffectVector` already carries `scaling_burn`,
`cast_damage`, `magecraft_damage` and `ritual_mana`. The semantics layer can see non-combat
damage; the clock throws it away. Feed it into the same damage accumulator that line 348
tests.

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
