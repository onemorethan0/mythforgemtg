# MythGauntlet — Status & Implementation Report

*As of 2026-07-22. Version 0.2.0. Private repo `onemorethan0/mythgauntlet`.*

> **2026-07-22 — Ops + casual-accuracy pass.** (1) The nightly training scheduled task had
> been DEAD since 2026-07-09 (a one-time `TimeTrigger`, `NextRunTime` empty; every run since
> was a manual `.bat` launch) — re-armed to a true daily 02:00 trigger (`DaysInterval=1`),
> now genuinely nightly. (2) **B2/B3 boundary banner (`bracket.plays_up`):** a measured
> finding on the labeled B1-3 corpus is that the goldfish axes do NOT cleanly separate Core
> from Upgraded (distributions overlap), so 4/6 labeled-B3 decks were snapping to a flat
> "Bracket 2". Rather than overfit a threshold to 10 noisy labels, a Core-capped deck (0 GC,
> no combo) showing upper-Core tuning now reports "plays up toward 3 (Upgraded)" — honest
> uncertainty, no false B3, bracket int unchanged (no API break; `bracket_plays_up` added).
> (3) **Goldfish horizon 8 -> 12 for `analyze`/`advise`** (`DEFAULT_ANALYZE_TURNS`): casual
> (B1-3) decks land their clock turns 10-14, so an 8-turn goldfish read Speed/Ceiling ~0 and
> mislabeled real B2/B3 decks as Exhibition (Bracket 1). Measured on the labeled corpus:
> 8->12 lifted B1-3 bracket agreement 5/10 -> 8/10; three decks moved off a wrong Bracket 1.
> (4) **`insight.pod_read`** -- a plain-English "which pod does this belong in?" line in the
> report + `/analyze` insight block. 454 tests, ruff clean.

## Executive summary

MythGauntlet measures Commander deck strength by **simulating games** rather than scanning a
decklist for known-good cards. The thesis — "deck strength is empirical; you measure it by
playing" — is now realized end to end:

- **All six Power Profile axes are measured** (Speed, Consistency, Resilience, Interaction,
  Ceiling, Meta strength) and mapped onto the official WotC 1–5 Commander Brackets with a
  confidence interval and human-readable reasons.
- Three simulation tiers work: **T0** goldfish consistency, **T1** paired-seed resilience,
  **T2** adversarial 1v1 with combos, activated abilities, and death triggers.
- The **card-semantics compiler** — the novel subsystem — has produced **14,089 cards with
  executable semantics** (14 hand-authored + 14,075 LLM-compiled and gate-validated; ~7%
  quarantine floor = the hand-authoring worklist).
- The **Ceiling axis models nut-draw finishers the combat clock can't see** (2026-07-18):
  a **storm/spellslinger go-off estimator** (`sim/storm.py` — commander-as-engine: Prismari
  storm grant + magecraft payoffs split cast-vs-copy + rituals + a copied burn finisher; drives
  Ceiling and a min-Bracket-3 gate) and a **go-wide overrun alpha-strike estimator**
  (`sim/overrun.py` — one-shot team pump on a wide board; lifts Ceiling only, since it's a fair
  wincon). Both corpus-swept for over-fire with precision guards (player-reachable burn,
  "until end of turn"); a real Prismari list went Ceiling 0→28, Bracket 2→3.
- **Graded combos** (2026-07-20, combo-quality Layer 1): the bracket combo-gate no longer
  treats every game-ending combo identically ("any -> min B3"). `spellbook.classify_combo`
  grades each winning combo from Spellbook metadata it used to discard (piece count, mana
  value, `notablePrerequisites`, commander-dependence, `bracketTag`) into `fast-win` /
  `strong` / `slow`, splitting **terminal** wins (lose-the-game / infinite damage/mill/turns)
  from **advantage** loops (infinite mana/tokens/ETB — need an outlet). The gate shows the
  breakdown as its reason and only a *fast terminal 2-card* combo drives the B5 escalation;
  floors are unchanged so counts-only callers/tests are byte-identical.
- **Combo determinism** (2026-07-20, combo-quality Layer 2): `semantics/combo_rules.py`
  judges whether an assembled combo is a GUARANTEED win by scanning the pieces' Oracle text
  (= Scryfall errata) + the Spellbook loop description for the crisp non-deterministic
  qualifiers the Comprehensive Rules turn on -- `at random`, `flip a coin`, dice, `opponent
  chooses`, `vote` (CR 720: a loop whose result depends on chance or an opponent's choice
  can't be forced to a win; an optional loop can be stopped at the winning iteration). The
  verdict is injected into `assess_combos` via a `determinism_fn` (DI, so the data layer
  never imports semantics), caps a chance-based win's reliability out of fast/strong (no
  cEDH escalation), and surfaces in the combo panel + gate reason with its CR citation.
  Conservative text heuristic: it flags markers, it does not prove determinism.
  The strength API `/analyze` exposes all of this behind an opt-in `combos: true` flag
  (cached Spellbook lookup, graceful on outage) as a structured `combos` block; MythForge's
  import-preview panel consumes it, so graded/deterministic combos now show in the app.
- MythGauntlet is a **standalone tool** (CLI + a local HTTP API). It optionally reads a
  collection file for ownership/upgrade features and serves its measurements over HTTP so any
  client can consume them; those integration seams still work but are no longer the headline
  (see "Integrations" below).
- The **upgrade advisor** (`advise`) ranks owned-card swaps by measured axis improvement
  (ablation re-simulation, not popularity), and the **CCM interpreter** now executes CCM
  cards' resolution effects AND event triggers in the T2 engine (per-effect, board-aware
  "for each" scaling; cast/attack/upkeep/landfall/combat-damage/end-step fired at the event).
- **Phase 7 has begun (this milestone):** the Tier-2 turn loop is now an **action-based state
  machine** an Agent drives (`sim/game.py`), with a behavior-preserving **GreedyAgent** (a
  golden-master test pins it bit-for-bit) and a new **ISMCTSAgent** — single-observer Information
  Set MCTS with determinization. It makes the planning move the greedy value function can't:
  deliberately holding mana up for a counter (proven by test). The **strength ladder is monotone**
  (`ladder`): on a control mirror, mcts:100 and mcts:1000 each beat greedy 94% and mcts:1000 beats
  mcts:100 81% (MCTS-1k > MCTS-100 > Greedy, the Phase-7 accept gate). `gauntlet --agent` /
  `duel --agent-a/-b` tag ratings *at* an agent level.
- **Parallel + cached gauntlet orchestrator** (`ratings/orchestrator.py`; `gauntlet --jobs/--cache`)
  makes an ISMCTS gauntlet affordable — matchups run across processes (parallel == serial
  bit-for-bit; ~4x on uneven mcts jobs, more on a full run), cached by semantics version for
  resume-for-free. The overnight pipeline now runs an **agent-contrast gauntlet** (greedy vs
  mcts at equal scope) so the morning report shows whether a stronger agent moves the bracket
  picture. *(GPU note: a lockstep vectorized env was measured and rejected — ~3,900x throughput
  but it deletes colors + card semantics; the 3090's role stays the LLM compiler + a future
  learned evaluator. `spikes/GPU_VECTORIZATION_FINDINGS.md`.)*

**Health:** 445 tests (offline, deterministic), ruff clean. 34,128-card offline store.
122-deck corpus (33 bracket-labeled). Phases 0–5 complete; Phase 6 (T2) a strong MVP; **Phase 7
(agents) has its first rung shipped** — ISMCTS + strength ladder, and **4-player pod games
(stage 3)** now run (`play_table`: rotation/elimination/win + multi-opponent "each" effect
scaling + aristocrat death drains + cast-taxer fan-out), with a **pod win-share meta-rating**
(`pod` / `analyze --pod` / `/pod`); pod reactions + politics remain. Headline meta-strength
remains. Phase 8's advisor has an MVP.

---

## At a glance

| Subsystem | Status | Notes |
|---|---|---|
| Tier-0 goldfish engine | **Done** | consistency + speed; ~2.2k games/s/core (5k target deferred) |
| Tier-1 resilience | **Done** | paired-seed clean-vs-wiped delta; board wipe injection |
| Tier-2 adversarial (1v1 + pod) | **MVP; 4-player stage 3** | combos, activated + death triggers, subject-scoped attack triggers; CCM resolution + event triggers via the interpreter; searched reactions (1v1). **N-player pod games** (`play_table`): living-seat rotation, elimination, last-standing/adjudicated win, threat-focus combat, **multi-opponent "each" effect scaling** (drains/draw/mass-damage/wipes hit the whole table), **aristocrat death drains + cast-taxer fan-out scale across the pod** — 1v1 byte-identical. Remaining: board-wipe/activated death drains primary-only, reactions 1v1-only, focus-fire combat, no politics model |
| Agents / search (Phase 7) | **ISMCTS + searched reactions** | action-based engine (`sim/game.py`); GreedyAgent (behavior-preserving, golden-master pinned) + ISMCTSAgent (SO-ISMCTS + determinization); reactions (counter-war/instant removal) are now `COUNTER_WINDOW`/`INSTANT_WINDOW` decision nodes ISMCTS searches — counters a spell greedy's gate would let resolve; `ladder`/`gauntlet --agent`/`duel --agent-*` |
| CCM interpreter | **Sole CCM resolution source** | `semantics/interpreter.py`; on-resolution flattening RETIRED — `profile_from_ccm` now folds interpreter effects into the valuation/reactive prior (no parallel walk). X-basis schema still open |
| Card semantics (CCM) | **Done (MVP+)** | 14,089 executable; ~7% quarantine floor |
| Upgrade advisor | **v2 (per-swap cut)** | `advise`: owned-card swaps ranked by measured axis gain (ablation); cut chosen per candidate from the `--cut-pool` weakest (default 3) |
| Power Profile (6 axes) | **Done** | all measured, each tagged with tier + coverage |
| Deck insight (report) | **Done** | `ratings/insight.py`: turns the scores into a deck-SPECIFIC narrative -- archetype + gameplan line, named cards behind each role (interaction/ramp/draw/finishers), a "why" per axis, and a strengths/weaknesses verdict. In the `analyze` report + the `/analyze` API `insight` block |
| Pod (multiplayer closing) | **First rung** | `axes.compute_pod`: can the deck reach TABLE-lethal (opponents x 40) unopposed, + a game-ending combo that closes the table? A 4-player-aware capacity proxy from a longer goldfish; shows the duel-vs-pod close gap. Full 4-player adversarial engine is the larger follow-on |
| Ceiling nut-draw finishers | **Done** | storm go-off (`sim/storm.py`, gates min-B3) + go-wide overrun (`sim/overrun.py`, Ceiling only); corpus-swept over-fire guards |
| Bracket estimate | **Done (rule-based)** | official WotC gates; learned calibration pending |
| Gauntlet ratings | **Done** | Bradley-Terry over T2 games |
| Pod meta-rating | **MVP** | `pod DECK.txt` / `ratings.pod.pod_winrate`: a deck's WIN SHARE in 4-player games vs the corpus field (seat rotated), against the 1/N even-pod baseline. Runs the multiplayer T2 engine; same stage limits |
| Data + corpus | **Done** | Scryfall bulk, EDHREC, Spellbook, Archidekt; 77 decks |
| Strength API (`serve`) | **Done** | :8020, /health /analyze /advise /duel /pod; pickle-cached store (/pod caches the corpus opponent field lazily) |
| CLI toolbox / UX | **Done** | dashboard, menu, doctor, decks, completion, --plain |
| Integrations (optional) | **Done** | reads a collection file for ownership/upgrade features; serves measurements over the HTTP API; `edhplay` can pull MythForge art. All optional — MythGauntlet stands alone |
| EDHPlay custom-art export | **Done** | `edhplay`: gets MythForge AI card art onto EDHPlay via a generated Tampermonkey userscript (rewrites card `<img>` by Scryfall printing UUID; verified live). Also emits Bulk-Import text/API body + printing selection. `default_cards` printings store; art sources mythforge/dir/manifest (`docs/EDHPLAY_EXPORT.md`) |

---

## The Power Profile (the flagship deliverable)

Not one number — six measured axes, each stamped with the simulation tier and semantics
coverage that produced it:

| Axis | Question | How measured | Tier | Status |
|---|---|---|---|---|
| **Speed** | How fast unopposed? | goldfish win-turn distribution | T0 | Done |
| **Consistency** | Does it do its thing? | mulligans, land drops, curve efficiency | T0 | Done |
| **Resilience** | Fold to a wipe? | outcome delta under injected disruption | T1 | Done |
| **Interaction** | Can it stop opponents? | castability-weighted answer density × breadth | semantics | Done |
| **Ceiling** | Nut-draw potential? | top-percentile T0 runs + combo boost | T0 | Done* |
| **Meta strength** | Does it actually win? | Bradley-Terry rating vs the gauntlet | T2 | Done |

\* Interaction now weights each answer by castability (2026-07-21: cheaper + instant-speed +
color-supported answers count more; raw counts still reported). Ceiling's finisher modeling is a
documented refinement (it reads low when a payoff like Overrun isn't compiled yet).

`analyze` prints the five single-deck axes plus the bracket estimate in one report;
`gauntlet` produces Meta strength across the corpus.

---

## Simulation engine

- **Tier-0 (goldfish, done & hardened):** mulligan policy → land drops → exact color-pip
  matching (Kuhn augmenting-path) → greedy casting → combat clock vs 40 life. Deterministic
  (all RNG via `sim/rng.SeededRng`), ~2.2k games/s/core. Distinguishes ramp types, one-shot
  vs repeatable draw, tap-lands, and commander cast timing.
- **Tier-1 (resilience, done):** injects a board wipe at turn *W* and compares clean vs wiped
  runs **at identical seeds** (variance cancels by construction) → a 0–100 retained-output
  score, kill-rate drop, and kill delay. Verified: noncreature ramp ~100, glass-cannon
  creature decks far lower.
- **Tier-2 (adversarial 1v1, MVP):** zones, combat with winning trades and lethal
  chump-blocks, commander tax, decking, turn-cap adjudication. Card behavior via
  **PlayProfiles** (CCM rung-2/3 flattened to executable effects; rung-1 EffectVector
  fallback). Executes activated abilities (mana/tap outlets), self-death triggers
  (aristocrat drains), **assembled combo win-conditions** (Commander Spellbook lethal combos
  as data), a **stack + instant-timing MVP**: the non-active player can counter
  a spell (LIFO counter-war) or cast held-up instant removal pre-combat, so counterspells and
  instant answers are no longer inert (reactions fire opportunistically — the greedy agent
  holds only surplus mana), and — new (2026-07-15) — **event-trigger execution**: CCM
  permanents' cast/attack/upkeep/landfall/combat-damage/end-step triggers fire AT their event
  through the interpreter, so non-draw trigger payoffs (aristocrat cast-drains, attack
  pingers, landfall token-makers) finally change games instead of flattening to draw-only
  `engine_draw` (docs/SIMULATION.md "Event-trigger execution"). Known gaps below.

---

## Card semantics — the "never existed before" part

A three-rung ladder so **every deck is simulatable on day one and precision only rises**:

- **Rung 3 (authored):** 13 hand-written exemplar CCMs (also the compiler's few-shot set).
- **Rung 2 (compiled):** **29,382** LLM-compiled CCMs (qwen3:14b via the local llama-swap
  gateway, temp 0), each passing three validation gates (schema / Scryfall-lint /
  bidirectional rung-1 cross-check) with a committed ledger + quarantine loop.
- **Rung 1 (heuristic):** Oracle-text effect vectors for everything not yet compiled.

**The new-card pool is EXHAUSTED (2026-07-28).** The ledger holds 31,658 of the 31,675
EDHREC-ranked non-basic cards in the Scryfall bulk; the other 17 are the hand-authored
rung-3 set. 29,382 accepted / 2,276 quarantined (~7%) is the floor — the residue is
genuinely hard (unsafe-to-auto-repair JSON, complex modal/conditional cards), and all but
one is already at the current prompt version, so the quarantine loop is correctly idle
until `PROMPT_VERSION` advances.

**Prompt v9 + a gate fix re-open the quarantine backlog (2026-07-28).** A failure histogram
over all 2,276 quarantined cards found the residue was not "genuinely hard cards" — it was
two fixable causes:
- **Shape errors the prompt never stated (939 first-errors, 41%):** the closed activated-cost
  key set (428 — v8 showed the shape by example, never said the set was closed, and never
  mentioned `other`, so the model invented keys like `discard`), empty `effects` lists on
  non-static abilities (281), and riders smuggled into mana abilities (230). v9 states all
  three outright.
- **A gate false-positive class (155 of the 240 hallucination errors):** gate 3 strips
  parentheticals, so "Cycling {2} ({2}, Discard this card: Draw a card.)" becomes
  "Cycling {2}" and a CORRECT CCM was failed for declaring a draw "the text never says".
  `ccm._KEYWORD_IMPLIED_OPS` now licenses cycling→draw, landcycling/transmute→search_library,
  ward→counter_spell against the RAW text, for the hallucination half only — the omission
  half is untouched, so a CCM that misses an effect still fails. (This closes the
  "revisit against the residue histogram" note left on the v8 campaign.)

**Measured on 30 previously-quarantined cards the corpus actually plays: 0/30 → 10/30
(prompt only) → 17/30 (57%) with both.** Recovered cards include Polluted Delta, Ash Barrens,
Otawara, Takenuma, Canyon Slough, Barren Moor, Tolarian Terror, Finale of Devastation. The
version bump re-arms `compile-top`'s existing retry gate for all 2,275 v8 quarantines — and
because `--refresh-stale` only engages when the normal queue is empty, the backlog is
worked FIRST and stale-refresh stays a fallback. ~2.1 h of GPU at the measured 3.4 s/card.

**Why this matters more than coverage did:** 170 of 174 corpus decks hold at least one
quarantined card (427 distinct, 872 copies) — The One Ring, Urza's Saga, Otawara, Sensei's
Divining Top. Coverage excluding basic lands is 94.2%, and the missing 6% IS this backlog.
Compiling further down EDHREC rank cannot help; the 7/26 night compiled 944 new cards and
moved zero deck ratings.

**Refresh is the low-value fallback, not the lever.** 9,031 accepted CCMs (~31%) were
compiled under prompt v1–v7 and were previously unreachable: `compile-top` short-circuits
on `status == "accepted"` regardless of version, so a card compiled at v1 stayed at v1
forever. `compile-top --refresh-stale` (2026-07-28) recompiles them oldest-version-first,
then by EDHREC rank — the first candidates are Arcane Signet (rank 3), Lightning Greaves
(13), Fellwar Stone (17), Blasphemous Act (22). A refresh that fails the gates keeps the
existing CCM (`_compile_cards(keep_on_failure=True)`), so an upgrade pass can never demote
a working card. The overnight pipeline passes the flag, so the nights compile again.

---

## Data & corpus

- **Scryfall** oracle-cards bulk → 34,128-card slim store (schema v2, includes the WotC
  `game_changer` flag — 53 cards, no hand-maintained list needed).
- **EDHREC** per-commander synergy/inclusion (priors only — never a verdict).
- **Commander Spellbook** find-my-combos (in-deck combos + one-card-away near-misses).
- **Corpus:** 77 committed reference decklists (EDHREC-average + Archidekt-top with
  user-declared bracket labels) + manifest provenance — the calibration anchor set.
- Open: cEDH Bracket-5 anchors (Moxfield API needs an approved User-Agent); explicit precon
  Bracket-2 labels.

---

## Integrations (optional — MythGauntlet stands alone)

MythGauntlet is used on its own via the CLI. These seams stay functional for anyone who wants
them, but are no longer positioned as the product's headline (2026-07-21 refocus):

| Seam | What | Status |
|---|---|---|
| **Collection file** | reads `Documents/MythSuite/collection.csv` (MYTHSUITE_DIR override) for ownership/upgrade features; `--collection` overrides | **Done** — auto-read when present; the path is kept for back-compat with any existing export |
| **HTTP strength API** | `mythgauntlet serve` :8020 (/health /analyze /advise /duel /pod) | **Done** — store pickle-cached (50s cold → 1.4s warm); any HTTP client can consume it |
| **EDHPlay art export** | `edhplay` can pull custom card art from a local MythForge build (optional art source) | **Done** — an art-source convenience, not a coupling |

---

## Card quality: tracks the LADDER, not the boundary (measured 2026-07-28)

Eight composition/card-quality signals were added to `scripts/axis_separation.py` and run
over the enlarged corpus (n=277: B1 78 / B2 90 / B3 84 / B4 15 / B5 11). Two distinct
answers came back, and conflating them would be a mistake:

**Across the whole ladder, card quality is real.** `edhrec_log_rank` is the second-strongest
signal overall at rho **−0.569**, cleanly monotone (B1 8.09 → B2 7.36 → B3 7.07 → B4 6.93 →
B5 6.28): higher-bracket decks play more-played cards. `tutor_density` (+0.304, B1 1.27 →
B5 9.73) and `fast_mana` (+0.296) follow. These are genuine.

**At the boundary that actually needs solving, none of it helps.** On the 120 zero-Game-
Changer B2/B3 decks — the band the official gate cannot resolve — EVERY signal returned
"none":

| signal | B2 | B3 | Cohen d |
|---|---|---|---|
| fast_mana | 4.10 | 3.64 | −0.19 |
| engine_density | 4.31 | 4.76 | +0.15 |
| low_curve_share | 0.41 | 0.40 | −0.09 |
| untapped_land_share | 0.84 | 0.83 | −0.08 |
| **edhrec_log_rank** | **7.35** | **7.30** | **−0.07** |
| cheap_interaction | 3.57 | 3.52 | −0.03 |
| tutor_density | 1.48 | 1.52 | +0.02 |
| cheap_removal | 4.33 | 4.36 | +0.01 |

Card quality — the popularity proxy most likely to capture "powered up with strong synergy
and high card quality", the official B3 wording — reads **identical** across the two labels.

**Read:** a zero-GC deck labeled B3 is not compositionally distinguishable from one labeled
B2. The likeliest explanation is that the label there records the author's INTENT and pod
context, not a property of the 99 cards. At n=87/33 a moderate effect (d≥0.5) would have
surfaced; a small one cannot be ruled out, but nothing of actionable size exists.

**Consequence:** the honest `plays_up` banner is the correct FINAL answer for that band, not
a placeholder — further engineering there is not worth spending. The signals stay in the
harness so they are re-measured free as the corpus grows. Note also that the strongest
ladder-level signal is popularity, which invariant 4 bars from driving a verdict regardless.

**RE-MEASURED 2026-08-21 at a larger n, and both halves of that read hold.** `scripts/
bracket_boundary.py` fits the 0-GC placement rule directly against the labels. At n=130
(90 B2 / 40 B3) the B2-vs-B3 baseline is **69.2%** and the best single-threshold rule reaches
**70.0%** with B3 recall of **2-5%** — "always say B2" wearing a threshold. Two-signal rules
top out at 70.8%. So the 2026-07-28 finding is confirmed rather than superseded: that boundary
is not resolvable from the card list.

**One correction, and it strengthens invariant 4 rather than weakening it.** The recorded
answer to "would popularity have helped?" was *"It doesn't"*, and that is wrong: at the
**B1/B2** boundary a single threshold on `edhrec_log_rank` scores **76.1%** against **64.8%**
for the `manabase_P` rule that ships — 11 points, on a broad plateau, better balanced. The
signal works. It stays barred anyway, because invariant 4 rests on the argument that a
popularity-driven verdict recreates the static-calculator failure mode this engine exists to
replace — not on popularity being weak. A false empirical claim inside a rule's justification
makes the rule look like it is defending a measurement; it is defending a principle.

**A note on the accept criteria.** Phase 5 asks for >=60% bracket-exact. If B2-vs-B3 is
genuinely not resolvable from the 99 cards — and two independent measurements now say it is
not — then a large slice of the corpus is unreachable by construction, and **within-one
(91.6%, target 95%) is the metric that can honestly move**. Exact-match rewards guessing the
annotator.

---

## Which signals actually separate brackets (measured 2026-07-28)

`scripts/axis_separation.py` is the standing calibration test: no axis may influence a
bracket verdict until it demonstrates separation on the labeled anchors. It reports Spearman
rho over the whole ladder AND Cohen's d per adjacent pair, because a signal can trend
beautifully overall and still be useless at the boundary you care about. n = 153 labeled
decks; stable across runs=120 and runs=200.

**Game Changers is the discriminator, and it earns its place as the primary lever:**

| boundary | best signal | Cohen's d |
|---|---|---|
| B2 → B3 | game_changers | **+1.16** STRONG |
| B3 → B4 | game_changers | **+1.43** STRONG |
| B4 → B5 | game_changers | **+2.26** STRONG |
| B1 → B2 | game_changers | −0.35 weak, and BACKWARDS |

**B1 vs B2 is the blind spot, and the mana math is the only thing that sees it.** Game
Changers cannot separate them by construction — the rules define BOTH as zero, so the
measured −0.35 is label noise, not signal. Of everything measured, only `manabase_P`
(`ratings/manabase.py`, added the same day) clears "weak": **d = +0.78**, B1 0.70 vs B2 0.80.
That is intuitive once seen — B1 is "theme over power", where the janky five-colour tribal
builds live, and their mana bases are genuinely worse than a precon's. It is a moderate
effect on n=84 with ~6% label noise: enough to move a prior, NOT enough to gate a verdict.

**B4/B5 gains interaction as a second signal** (interaction d=+1.12, effective_answers
d=+1.39) — cEDH interaction density is a step function, not a trend, which is why its
whole-ladder rho is only +0.09. Judge boundaries pairwise, not by rho alone.

**TRAP — do not wire `consistency` in.** It shows d = −1.07 (STRONG) at B3→B4 and rho
−0.309 overall, but the SIGN IS WRONG: our score falls as brackets rise, while real cEDH
decks are famously more consistent. It is an artifact — low land counts plus fast mana read
as an unstable curve to a goldfish metric. Strong effect size, invalid direction.

**Label hygiene:** 4/37 B1 and 1/47 B2 anchors carry at least one Game Changer, which the
rules forbid at those brackets. Author labels are ~6% noisy; that bounds achievable accuracy
and is why moderate effects should not become gates.

---

## The goldfish clock is bracket-blind (measured 2026-07-28) — NEGATIVE RESULT

The October 2025 bracket update states each bracket's expectation partly in TURNS: B1 "at
least nine turns", B2 "at least eight", B3 "at least six", B4 "at least four", B5 any. That
reads like a gift — T0 already measures a goldfish kill turn, so the criterion looks
directly simulable. **It isn't.** Measured over the 152 labeled anchors (T0, 250 runs,
seed 42):

| bracket | n | mean kill turn | median | stdev |
|---|---|---|---|---|
| 1 | 37 | 10.67 | 10.77 | 1.44 |
| 2 | 47 | 10.69 | 10.74 | 1.11 |
| 3 | 43 | 10.53 | 10.52 | 1.33 |
| 4 | 15 | 10.66 | 10.08 | 1.73 |
| 5 | 10 | 11.17 | 11.49 | 1.10 |

Flat — every bracket lands at 10.5–11.2, well inside one standard deviation, and **B5 is
the SLOWEST**. Wiring `avg_kill_turn` into `estimate_bracket` would add noise, not signal;
do not do it on the strength of the official wording alone.

The reason is the same one behind the B5 rating inversion, now confirmed one tier lower:
`avg_kill_turn` is a **combat** clock. Bracket is about HOW you win, not how fast creatures
connect. A cEDH deck's real clock is a tutor chain into a two-card combo on a single
explosive turn — T0 models none of that, so it measures every deck's beatdown plan and
finds them all similar. The inversion is therefore not only a T2 agent/engine question; the
T0 speed axis is bracket-blind too. `bracket.py` used `avg_kill_turn` only inside the
`_upper_core` "plays up" test (`_UC_KILL_TURN` 9.5) — that narrow use was fine and stayed at
the time. **Since superseded:** there is no `_UC_KILL_TURN` any more; `plays_up` is now a pure
band test, `bracket == 2 and (floor, cap) == (1, 2)`, with no kill-turn threshold at all — so
the speed axis no longer feeds the bracket even there.

**Consequence for calibration:** the newly harvested B1–3 anchors (37/47/43) cannot be
calibrated against speed. The separating signals have to come from composition and from
how a deck WINS — Game Changer density, combo presence/quality, interaction, Ceiling — not
from the clock.

---

## Roadmap status

- **Phase 0 — Skeleton & framework:** Done.
- **Phase 1 — Tier-0 hardened:** Done. *Open:* dorks-as-rocks / cost-reduction ramp
  modeling; 5k games/s perf target (currently ~2.2k).
- **Phase 2 — Data & popularity:** Done. *Open:* cEDH B5 anchors, explicit precon labels.
- **Phase 3 — Semantics compiler:** Done (far exceeded the top-500 goal at 9k). *Open:*
  acceptance ceiling (~88%) blocked on missing-comma JSON.
- **Phase 4 — T1 pressure + Interaction + Ceiling:** Done. *Open:* more disruption classes
  (targeted removal, counter budget). *(Interaction castability weighting shipped 2026-07-21.)*
- **Phase 5 — Gauntlet ratings & bracket v1:** Done (rule-based). *Open:* learned ordinal
  regression (needs more labeled decks).
- **Phase 6 — Tier-2 adversarial 1v1:** Strong MVP. **Stack + instant-timing MVP done**
  (counters + instant removal now function). **Event-trigger execution done** (2026-07-15:
  cast/attack/upkeep/landfall/combat-damage/end-step triggers fire at the event via the
  interpreter; no engine_draw double-count). *Open:* retire the PlayProfile's remaining
  on-resolution fields; X-basis CCM schema field; deliberate mana-holding (the greedy agent
  only reacts with surplus mana); reactive burn / responses to abilities; per-attacker
  fan-out for global attack triggers; job orchestrator + results DB + caching; Forge
  differential harness.
- **Phase 7 — MCTS, multiplayer, ratings v2:** First rung shipped (2026-07-17). The Tier-2 loop
  is now an action-based state machine (`sim/game.py`) driven by pluggable agents; GreedyAgent
  (behavior-preserving — golden master pins it) + ISMCTSAgent (SO-ISMCTS + determinization).
  ISMCTS makes the planning move greedy can't (hold mana for a counter, proven by test). Strength
  ladder measured (`ladder`); ratings tagged at an agent level (`gauntlet --agent`).
  **Reactions are now searched decisions (2026-07-21):** a cast puts the spell on the stack and
  opens `COUNTER_WINDOW` / `INSTANT_WINDOW` decision nodes (LIFO counter-war; pre-combat removal),
  so ISMCTS can counter a spell the greedy value gate would let resolve, or hold a counter greedy
  would spend (proven by test); GreedyAgent reproduces the old auto-resolution bit-for-bit
  (golden master unchanged). **Multiplayer first rung (2026-07-21):** the Pod axis
  (`axes.compute_pod`) reads whether the deck can generate TABLE-lethal unopposed damage (a
  longer goldfish vs opponents x 40) or close via a game-ending combo, and surfaces the duel-
  vs-pod close-rate gap — a 4-player-aware *capacity* signal in the report/API without a T2
  rewrite. **4-player engine stage 1 shipped (2026-07-21):** the T2 engine now runs N-player
  pod games (`play_table`) — living-seat turn rotation, elimination, last-standing/adjudicated
  win, threat-focus combat, and **multi-opponent "each" effect scaling** (stage 2: group-slug /
  drain / mass-damage / wipes hit the whole table) — with the 1v1 golden master byte-identical
  (branch on seat count). *Open (next stages):* death-trigger drains + opponent-cast trigger
  fan-out (primary-only today); reactions + per-attacker combat splitting in pods; a
  politics/threat model; wiring pod win-rates into a meta-rating. Also: meta-strength as the headline number; per-decision search
  perf (single-process pure-Python, slow at mcts:1000) — orchestration/caching is the next lever.

---

## CLI toolbox re-envisioning (this milestone)

The 13 flat subcommands were an undiscoverable pile and a bare `mythgauntlet` errored.
Delivered a navigable front door, **fully backward-compatible** (all command names/flags
preserved, integration seams intact):

- **Home dashboard** (`home` / bare invocation) — environment status + workflow-grouped command
  map + a context-aware next step.
- **Interactive menu** (`menu` / bare on a TTY) — numbered navigation into the real commands.
- **`doctor`** — environment health check (data / gateways / collection / corpus) with fixes.
- **`decks`** — browse the corpus decklists (commander, bracket, source).
- **Workflow-grouped `--help`** — commands grouped into 5 workflows + a common-workflows block.
- **Last-deck memory** — a bare `analyze` re-runs your last deck (`--json` stdout stays pure).
- **Shell completion** — `completion <shell>` for powershell/bash/zsh/fish, names sourced
  from the live parser.
- **`--plain` / `--no-color`** — position-independent plain output (NO_COLOR honored).

Landed on `main` (merged from `cli-toolbox-nav`, commit `45a086b`; branch since deleted).

---

## What's next (prioritized)

*Re-tuned 2026-07-13 after a full review; item 1 (event-trigger execution) shipped
2026-07-15. Earlier this cycle: CLI toolbox, T2 stack MVP, Suite C4 (both halves), advisor
MVP, CCM interpreter (core + wired + board-aware resolver). Investigated-and-rejected with
data: greedy mana-holding (agent problem → Phase 7); real X from board state (X is
cost/chosen in the store, needs schema basis).*

*Measurement note (2026-07-17 gauntlet, seed 777, 111 decks / 417 matchups × 60 games,
post-14k-semantics): with REAL anchor n for the first time (Archidekt `edhBracket` server-
side filter -> 12×B4 + 11×B5 cEDH lists), bracket means are B3 1603 > B2 1489 > B4 1440 >
**B5 1326**. The inversion at the top is now a systematic finding, not noise: battlecruiser
fidelity favors big-creature midrange (Miirym/Yargle-style decks top the table) while cEDH
wins live in tutors, rituals, storm turns, and stack interaction the T2 MVP under-models —
cEDH decks are forced to play combat games they would never play. CONSEQUENCE: T2
meta-rating must NOT feed top-bracket calibration until Phase 7 fidelity lands; the
rule-based bracket gates (GCs, combos, speed) remain the honest top-end signal, and the
anchors are banked for the day the engine can rank them.*

*Re-measure (same day, after the cEDH fidelity increment — ritual mana, tutors-to-hand,
hand-castable combo pieces; docs/SIMULATION.md): B5 1326 → 1355 (+29) while B2/B3/B4
stayed flat (−4..−7). The increment moved exactly the decks it targeted — the inversion
is partly fidelity and shrinks as fidelity rises; the remaining ~240-point gap to B3 is
the Phase 7 mandate (deliberate combo-turn mana holding, storm, stack wars at cEDH
density, protection).*

*Correction (2026-07-31): a MEASURABLE PART OF THE INVERSION WAS AN AGENT BUG, NOT
FIDELITY. The narrative above — "cEDH decks are forced to play combat games they would
never play" — was true but incomplete, and it discouraged looking for a specific defect.
There was one. `_combo_bonus` paid the greedy agent to cast ANY combo piece whether or
not the combo could finish, so dedicated instants/sorceries went to the graveyard for a
popularity prior of ~2.0: Demonic Consultation 0.85 casts/game on Blue Farm, Tainted Pact
0.82, Brain Freeze 0.88, one copy each. The first cast removed the deck's wincon from the
game permanently. Diagnosis that found it: 98% of failed `combo_ready` checks were a
MISSING PIECE (mana bound only 1.4%), and unpressured — 30 turns, no lethal, isolating the
deck's own clock from the beatdown race — Blue Farm assembled in just 34/120 games.*

*After holding instant/sorcery pieces (note the subtlety: NO "unless this cast finishes
it" exception, because `combo_ready` resolves from pieces HELD plus mana, so casting the
last piece is precisely what stops the win): Blue Farm 34/120 → **120/120** unpressured,
24.4 → 13.8 turns; Tymna/Thrasios 36 → 94; Meren Hulk 41 → 66. Head-to-head vs a B2
Ghired list, 5.0% → 16.0%.*

*THE INVERSION IS AN INSTRUMENT PROBLEM AND AN AGENT PROBLEM — not mainly engine
fidelity (2026-07-31, three converging measurements).*

*1. Instrument. Commander brackets describe FOUR-PLAYER games; the gauntlet rates 1v1
duels. Rated in pods instead (`mythgauntlet pod-brackets`, 4-player, 24 pods/deck,
seed 777), the inversion disappears: B1 -0.008, B2 -0.005, B3 -0.008, B4 -0.003,
**B5 +0.148** — cEDH goes from LAST in duels to clearly first, at a 0.398 win share
against a 0.250 baseline. Part of why is mechanical: cEDH's draw engines are
opponent-taxed (Rhystic Study, Mystic Remora, Esper Sentinel) and are close to blank in
a duel by construction.*

*2. But the pod signal is SINGLE-SOURCE. The `--no-combos` control is not optional and
must be run alongside: with combos off, B5 falls to -0.009 and every bracket is flat
(B1 -0.021, B3 +0.004). B5's entire lift is the combo model, so it inherits every
simplification in `combo_ready` — pieces held plus mana, no opposing interaction.
Faithful in kind (a real Thoracle line does beat the whole table at once) but not
independent corroboration that the engine "understands" cEDH.*

*3. Agent strength matters far more than previously concluded. Re-testing greedy vs
ISMCTS-120 WITH COMBOS ON (60 games, seed 778, same scope, only the agent differs):
Blue Farm 31.7% -> 48.3%, Tymna/Thrasios 13.3% -> 40.0%, Meren Hulk 8.3% -> 20.0%, with
combo wins roughly doubling in each. The standing "if it stays inverted it's the ENGINE"
verdict was reached from a contrast that ran `--no-combos` — structurally blind to the
two-card combo that IS the cEDH win — and while the greedy agent was still binning its
own pieces. Both premises are now false; the nightly contrast no longer passes
`--no-combos`.*

*Consequence for calibration: the standing ban should be narrowed from "T2 meta-rating"
to "T2 DUEL meta-rating". Pod rating with combos is a defensible top-end signal today,
stated with its combo-model dependency. It still does NOT separate B1-B4 (all within
0.005 of baseline) — that separation remains a composition question, as the T0 speed
finding above already concluded.*

*What this changes methodologically: before attributing a rating result to "fidelity",
instrument the failure and count the reasons. Fidelity is a real ceiling — Blue Farm's
post-fix clock is ~13.8 turns against games that end at 8.6, and that gap IS
battlecruiser-vs-cEDH — but it is also a comfortable story that hid a one-line agent
defect for two weeks. Also re-tested and still negative: a graduated tutor bonus for
tutoring while 2–3 pieces away (the "tempo trap" finding survives its own re-measurement,
now that fetched pieces are no longer binned).*

1. **Compiler v8 campaign COMPLETE (2026-07-17, 4.7h overnight run).** +4,823 accepted
   (5,044 total v8 accepts: 289 via deep repair, 685 carrying x_basis); executable
   semantics 9,266 → **14,089**. Quarantine floor 1,060 and finally honest — 1,059/1,060
   were retried AT v8 and still failed (~7%); this is the genuine hand-authoring
   worklist. *Gate note (stands):* cycling lands are a cross-check false-positive class
   (gate 3 strips reminder text) — arguably correct to quarantine until cycling is
   modeled as a hand-zone ability; revisit against the residue histogram.
2. **Labeled anchors HARVESTED (2026-07-17)** — `fetch-decks --source archidekt --bracket N`
   (the API filters on `edhBracket` server-side; no Moxfield needed). 33 labeled decks
   (4/6/12/11 across B2-B5). What they measured first is the ENGINE's ceiling (see the
   note above): learned calibration at the top end now waits on Phase 7 fidelity, not on n.
   Still open: explicit precon B2 tags for provenance-clean B2 anchors.
3. **Advisor v2 — per-swap cut selection SHIPPED (2026-07-21).** The advisor no longer cuts
   the single globally-weakest card for every suggestion: each candidate is now tested against
   the `cut_pool` weakest nonland cards (`advise --cut-pool`, default 3; `/advise` request
   field) and keeps whichever cut improves the target axis most, so a ramp add displaces a
   weak ramp piece instead of fighting the one globally-weakest card. Per-swap `cut` shows in
   the CLI table + API; `analyses` (candidates x cut options) reports the true re-sim count.
   Deterministic (ties break by name). `cut_pool=1` reproduces the MVP exactly. *Still open:*
   general (non-owned) candidate pools, multi-card packages, faster batched evaluation.
4. **Phase 7: ISMCTS agent — FIRST RUNG SHIPPED (2026-07-17).** The Tier-2 loop is now an
   action-based state machine (`sim/game.py`) driven by pluggable agents; GreedyAgent is
   behavior-preserving (golden master pins it bit-for-bit) and ISMCTSAgent is SO-ISMCTS with
   determinization. Deliberate mana-holding — the move measured to be beyond greedy — is now
   real (proven by test: greedy taps out, ISMCTS holds the counter). Strength ladder measured
   (`ladder`); ratings tag the agent level (`gauntlet --agent`, `duel --agent-a/-b`). **Parallel
   orchestrator landed** (`ratings/orchestrator.py`, `--jobs/--cache`) — the corpus gauntlet can
   now run under mcts overnight (agent-contrast phase wired into scripts/overnight.py). *Next
   inside Phase 7:* reactions as explicit search decisions (auto-resolved greedy today); a real
   results DB + variance-aware budgeting; then 4-player + headline meta-strength. Investigated &
   rejected with data: a GPU-vectorized env (deletes colors/semantics — spikes/). Note: T2
   meta-rating still must NOT feed top-bracket calibration until cEDH-line *engine* fidelity lands
   — a stronger *agent* doesn't fix an under-modeled engine; the overnight agent-contrast gauntlet
   is designed to measure exactly which of the two the B5 inversion is.
5. **Engine hygiene, ongoing** — **CCM on-resolution flattening RETIRED (2026-07-21):** the
   interpreter is now the single source of truth for CCM resolution; `profile_from_ccm` folds the
   interpreter's effects into the valuation/reactive summary instead of a parallel hand-rolled
   walk, so the greedy prior can't drift from execution (byte-identical golden master; deltas are
   deliberate corrections toward execution). **Per-attacker fan-out for global attack
   triggers SHIPPED (2026-07-21)** — an `attack` CCM trigger is now classified at CCM-load
   time (`tier2._attack_subject_scope`, from Oracle text + card type) into self /
   global_each / global_once, and declare-attackers fans it out to match: a "whenever a
   creature you control attacks" payoff (token/draw/drain) fires **once per attacking
   creature** instead of the old flat once, so go-wide boards score their payoffs (47
   global-each + 377 global-once compiled cards reclassified; self-triggers and the golden
   master unchanged, 395 tests). *Still open:* per-attacker *targeting* ("it gets +X/+X"
   can't single out the attacker); whole-card scope heuristic (a card with 2 attack triggers
   shares one verdict). T2 orchestrator + results DB + job-hash caching when matrix runs get
   heavy; 5k games/s T0 target only when profiling says it matters.

---

## Metrics snapshot

| Metric | Value |
|---|---|
| Version | 0.2.0 |
| Tests (offline, deterministic) | 451 passing, ruff clean |
| Card store | 34,128 oracle cards (slim v2) |
| Executable semantics | 14,089 cards (14 authored + 14,075 compiled) |
| CCM quarantine floor | 1,060 — honest: all v8-retried (~7% of attempts); the hand-authoring worklist |
| Reference corpus | 111 decklists (33 bracket-labeled: 4×B2 6×B3 12×B4 11×B5 — Archidekt `edhBracket` filter) |
| T0 throughput | ~2.2k games/s/core |
| Agent ladder (control mirror) | monotone: mcts:1000 & mcts:100 beat greedy 94%; mcts:1000 beats mcts:100 81% |
| Strength API store load | ~50s cold / ~1.4s warm (pickle cache) |
