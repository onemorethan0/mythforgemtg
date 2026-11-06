# Deck building: review and development plan (2026-11-06)

Scope: everything between "pick a commander" and "here is your 99": `deck_builder.py`, `bracket.py`,
`deck_quality.py`, `commander_analysis.py`, `edhrec_lift.py`, `theme_match.py`, `collection_pool.py`,
`api/jobs_build.py`, `api/routes_builds.py`, and the `StepCommander / StepTheme / StepDeck` front end.
Goal the work is judged against (owner, 2026-07-18): casual Bracket 1-3 decks that are fun and
on-level for a pod, not cEDH optimisation. A wrong card model is a defect, not an approximation.

**How this was done, and what it does not cover.** I read the builder's build path end to end, read
the recorded 20-commander builder bench (`docs/bench/current.json`), and ran one new measurement
(builds at all five brackets for two commanders). I did not click through the UI, did not re-run the
full bench, and the engine was not running, so nothing below uses a strength number. Each finding is
tagged **measured** (I ran it), **read** (I read the code or recorded data) or **inferred** (follows
from the above, not checked).

---

## 1. What is in good shape

- The builder is well-defended against its own past bugs: every odd rule carries the measurement that
  justified it (lead-theme weighting, dead-fetchland filter, plan normalisation). 99-card legality is
  guaranteed, degraded builds are detected and excluded from the bench, partners and strict
  collection mode are handled.
- The bench exists and is fixed-roster, so builder changes can be compared as numbers.
- Bracket Game-Changer gating reads Scryfall's live `game_changer` flag, not a stale name list.
- On the recorded run all 20 builds are valid, none padded, none rate-limited, no colour shortfalls.

## 2. Findings

Ranked by how much they affect the stated goal.

### F1. The bracket setting is a ceiling, not a target (measured, 2 commanders)
Builds at brackets 1-5 for Krenko and Meren (non-basic cards shared between adjacent brackets):

| Step | Krenko | Meren |
|---|---|---|
| B1 -> B2 | 54 / 63 | 55 / 63 |
| B2 -> B3 | 59 / 64 | 53 / 64 |
| B3 -> B4 | **67 / 71** | **68 / 76** |
| B4 -> B5 | 59 / 71 | 69 / 76 |

Bracket 4 is bracket 3 with the Game-Changer cap removed, and the builder does not go looking for
power: Krenko at **B5 (cEDH) holds 0 Game Changers and 1 fast-mana piece**. In the other direction,
**B1 still includes Sol Ring** and Meren's B1 build holds ~2 tutors. A player asking for "Exhibition"
gets a deck that is allowed to be one, not one that plays like one. For the owner's B1-3 goal the
low end matters most: B1 and B2 are 85% the same list.

### F2. No combo, tutor or fast-mana awareness at brackets 1-3 (read)
`bracket.py` documents "no infinite combos" for B1/B2 and the rules also limit early two-card combos
and tutors in the lower brackets, but `BracketFilter` checks only Game Changers, extra turns and mass
land denial. `grep -i combo deck_builder.py` finds nothing. The engine already has a combo table
(`bracket_accuracy.py --real-combos`), so the knowledge exists on the other side of the process
boundary and is not used when drafting.

### F3. The build is open-loop (read)
Nothing after `DeckBuilder.build()` compares the result with what was asked. The requested bracket is
never checked against the engine's bracket estimate; role targets are never checked; the engine's
`advise` swap search (which already finds the cards driving a deck's strength) is never used to
repair a build. A deck that lands one bracket high or low ships as is. The Mentor can describe the
problem afterwards, which is the wrong place to find it.

### F4. Two (three) role vocabularies that disagree (read, partly documented in the bench)
The builder drafts roles from Scryfall `otag:`/oracle-text queries (`ROLE_QUERIES`); strict collection
mode classifies with `collection_pool`; the engine rates with its own tagger. The bench comments
already record the result: it saw 0 wipes for Krenko and 0 protection for Talrand when the builder
had drafted them to plan. Recorded roster means against a plan of 10 ramp / 4 wipes: **ramp 17.4
(range 9-23), wipes 3.4 with 3 of 20 decks at 0**. Some of that is the engine counting treasure and
rock-adjacent cards the plan never meant; some may be real. The point is that the builder cannot tell.
This is the same "fix one, fix all" class as the profile/tags/executor divergence noted for the engine.

### F5. The slot plan is a fixed recipe (read)
Ramp 10 / draw 10 / removal 7 / wipe 4 / protection 3 / finisher 3 / theme 20, for every commander,
with five successive mutations (bracket 1, bracket 5, aggro bump, collection redirect, then a
`_normalize_plan` patch to make it sum). Land count is 36/37/38 by **commander** mana value only, not
by the deck's own curve or ramp count. Recorded decks carry 37 lands plus ~17 engine-counted ramp
pieces. Whether that floods is **unmeasured**: the goldfish already reports land/ramp consistency but
the builder never reads it.

### F6. The bench cannot say whether a build is *strong or on-level* (read)
Its headline metric, `synergy`, is the deck's mean EDHREC lift, and the builder *sorts by EDHREC
lift*. So the metric mostly measures agreement with EDHREC, which the builder maximises by
construction. The other metrics (curve deviation, role counts, castability) are real but structural.
The bench also builds at **bracket 3 only** and on the Scryfall path, so F1 was invisible to it. The
lowest-signal commanders (Jegantha -1.4, Karona 4.5, Progenitus 3.5; coverage 0.37-0.47) are thin
EDHREC pages; there the builder has little to sort by and falls back to goodstuff.
(Not a defect: the `off-plan` verdict on 12 of 20 is the relative residual quadrant and is
documented as "leans on the commander less than most decks", not "bad".)

### F7. Curve fit is uneven (read)
Curve deviation mean 16, worst Kozilek 36, Talrand/Ur-Dragon/Atraxa 26, best Jegantha/Karona 2. One
reference curve fits all commanders; the high-MV and many-colour commanders miss it most.

### F8. Reproducibility and external dependence (inferred)
Role queries go to Scryfall live and ordering leans on EDHREC's unofficial API (disk-cached, soft-fail
to `{}`). Two builds of one commander a day apart are not guaranteed identical, and a build with the
EDHREC call failed silently differs from one with it. No test pins "same inputs, same deck".

### F9. Structure and test gaps (read)
- `DeckBuilder.build` is ~280 lines of sequential plan mutation; `api/jobs_build.py` is 1,119 lines
  with four generation branches (saved deck, prebuilt, import, generate) in one function.
- `StepDeck.jsx` 1,696 lines / 41 `useState`; `StepTheme.jsx` 1,761 / 25. The 96 frontend tests cover
  only `utils/`; **no component is tested**.
- The builder reports progress with `print` (12 sites) rather than the app's log buffer.
- Python side is well covered (builder, bracket filter, curve, lift, strict, routes all have tests).

### F10. Not examined
The wizard's UX (commander search, theme preview latency, rebuild/regen flows, mobile), art/theme
generation, and the 3D/print path. Those need a hands-on pass, listed as step P7.

---

## 3. Development plan

Principle: **measure first, then change the thing the measurement points at, and gate every change on
the existing guards** (bracket accuracy within-one >= 92.1% raw, builder bench, full suite). Order is
by value to the casual B1-3 goal.

### P0. Measure (no behaviour change) - owner Claude, ~1 day
- Extend `scripts/builder_bench.py`: `--brackets 1,2,3,4,5` and `--commanders N`, recording per build
  GC count, fast mana, tutor count, known-combo count, requested vs engine-estimated bracket.
- Add an engine arm: run the strength engine on each build (needs :8010/:8020) and record bracket
  estimate, power axes, goldfish land/ramp consistency. Commit the result as `docs/bench/brackets-*.json`.
- Add a determinism check (build twice, diff).
- **Accept:** a table of requested-vs-estimated bracket per bracket and commander; F1 and F5 either
  confirmed with numbers or retired. Decide P1/P4 scope from it.

### P1. Make bracket a target - owner Claude (MTG-rules-facing: no local drafting)
- B1/B2: refuse fast mana, tutors and the engine's known combos when drafting, with the same
  "gate the object, subtract the cost" care the other filters use; B2 may allow a small, named budget.
- B4/B5: lift power on purpose (fast mana, tutors, efficient interaction) from the engine's strength
  ranking rather than by removing a cap.
- Per-bracket slot plans as data (see P4), not branches in `build`.
- **Accept:** requested bracket == estimated bracket (or within one, matching the estimator's own
  92% within-one) on >= 80% of roster x bracket; bracket-accuracy guard unchanged; B1 build holds no
  fast mana/tutors/combos.

### P2. Close the loop - owner Claude
- After `build()`, call the engine's analyze; if the estimate is above the request, swap out the
  cards driving it using the existing `advise` search; if role floors or colour sources fail, repair.
  Bound the loop (max 2 passes, never worse on the guard metric) and report what was repaired in the
  build log and `deck.json`.
- **Accept:** P0 table improves; no build takes more than ~+60 s; a repaired build is still 99 legal.

### P3. One role vocabulary - owner Claude, drafts for the mechanical part may go to qwen3
- Classify roles through one shared module consumed by the builder, `collection_pool` and (via an
  exported table) the engine, keeping `otag:` only as a candidate *source*, not the judge.
- **Accept:** builder role counts equal engine role counts on the roster (the 17-vs-10 ramp gap
  explained or closed); tests that fail if the two disagree.

### P4. Plan from data, not constants - owner Claude
- Move the slot recipe into a small data table keyed by (bracket, archetype, commander MV, colours);
  derive land and ramp counts from the deck's own curve; validate with goldfish land/screw/flood rates
  (P0 arm), keeping a change only if consistency improves and the bench does not regress.
- Replace the five successive mutations and `_normalize_plan` patch with one resolver.
- **Accept:** same-or-better bench; plan code readable in one screen per bracket.

### P5. A bench that can see strength - owner Claude
- Make the primary gate the engine's strength/bracket result, with EDHREC synergy kept as a
  secondary "does it respect the commander" signal. Widen the roster (keep the old 20 fixed as a
  comparison set) to include thin-page commanders.
- **Accept:** a change that raises synergy but lowers strength is flagged red.

### P6. Structure and tests - mostly offloadable
- Split `_run_build` into one module per branch behind a small interface; `build` into plan /
  draft / repair stages. Pure moves first, behaviour unchanged, proven by the existing tests.
- Frontend: add vitest + Testing Library; component tests for the wizard's state machine
  (StepCommander -> StepTheme -> StepDeck), starting with the paths that have had bugs (partners,
  strict collection, rebuild). Replace builder `print` with the log buffer.
- Offload: test scaffolds and the mechanical extraction to node 2 (qwen3:8b) / node 1 (14b), always
  read before landing; anything rules-facing stays with Claude.
- **Accept:** suite green at each step; no file in the build path over ~600 lines.

### P7. Hands-on UX pass - needs the app running; do after P1
- Walk the wizard end to end (commander search, partner pick, theme preview, collection modes, build,
  rebuild, export), at desktop and phone widths, and file defects into BACKLOG. This was out of scope
  for this review.

### Suggested order and effort
P0 (1 day) -> P1 (2-3 days) -> P2 (2 days) -> P5 (1 day, can run beside P2) -> P3 (2 days) -> P4 (2
days) -> P6 (ongoing, offloadable) -> P7. Stop after P1+P2 if the P0 numbers show the bracket gap is
smaller than F1 suggests: those two deliver the casual-bracket goal; the rest is quality of life.

### Risks
- P1/P2 raise build time (engine calls); mitigate with the bound above and a "fast build" toggle.
- Hard exclusions at B1/B2 can empty a colour pair's candidate pool; the existing `search_buffer`
  and goodstuff fallback must be re-measured, not assumed.
- The engine is a separate process: the builder must degrade to today's behaviour when :8020 is down.

---

## 4. P0 result (2026-11-06, `scripts/bracket_bench.py`, `docs/bench/brackets-2026-11-06.json`)

6 commanders x 5 brackets = 30 builds, each analysed by the engine (300 runs, combos on). Engine
bracket estimate for the bracket the user asked for:

| Requested | Builds | Mean estimate | Exactly right | Within one |
|---|---|---|---|---|
| 1 | 6 | 2.50 | 1 / 6 | 2 / 6 |
| 2 | 6 | 2.50 | 3 / 6 | 6 / 6 |
| 3 | 6 | 3.00 | **6 / 6** | 6 / 6 |
| 4 | 6 | 3.33 | 0 / 6 | 6 / 6 |
| 5 | 6 | 3.33 | 1 / 6 | 1 / 6 |

Per commander, estimates for requested B1..B5: Krenko 3,3,3,3,3; Meren 3,2,3,3,3; Atraxa 3,3,3,3,3;
Talrand 2,2,3,3,3; Edgar 1,2,3,3,3; Tymna 3,3,3,5,5.

What it settles:

- **F2 is real, and it is the low end's problem.** The engine's reasons show *why* B1/B2 builds read as
  Bracket 3: four of six hold an in-deck game-ending combo that trips the official gate ("N in-deck
  game-ending combo(s) -> min Bracket 3"): Krenko 14 combos, Tymna 8-10 fast two-card terminals,
  Atraxa and Meren 1 each. The builder never looks for combos. Game Changers were 0 at B1/B2 in every
  build, so that gate works; combos are what leak.
- **For your B1-3 goal, bracket 3 is already right (6/6) and brackets 1-2 over-shoot.** Those are the
  ones to fix. Within-one at B2 is 6/6; B1 is the weak cell.
- **F1 is smaller than the first sample suggested at the top and confirmed at the bottom.** Adjacent
  brackets share 86-91% of non-basic cards. B4 and B5 never reach their label: a B5 Krenko measures
  *Bracket 2 on strength* (score 2.6, kill turn ~9.9, ceiling 33). Only Tymna reaches 5, via 10-11
  Game Changers. Getting B4/B5 right means choosing power on purpose, which is not the casual goal.
- **F8 (partly):** one commander built twice at B3 gave an identical list. That ran on warm Scryfall and
  EDHREC caches, so it shows determinism *given the caches*, not across days.
- Structural heuristics (named fast-mana list, library-search text) average 1.3 fast mana and 1.5
  tutors at B1, so those leak a little too, but nothing in the engine's reasons names them as the
  deciding factor yet. Combos are.
- The estimator itself is 92% within-one on labelled decks, so a single miss is not proof; the pattern
  across commanders is.

### Plan changes this causes

- **P1 is split.** **P1a (do now):** at brackets 1-2 (and 3, which also bans early two-card combos
  in the official text) keep combos out of the build by asking the engine's combo table, and treat
  fast mana/tutors as a smaller second-order tuning. **P1b (defer):** pulling power in at B4/B5 does
  not serve the casual goal; do it only if you want those brackets honest.
- **P2 (close the loop)** becomes the natural mechanism for P1a: build, ask the engine whether the
  result is above the requested bracket and *why* (it already returns reasons), swap out the cards in
  the named combos, re-check once.
- P3-P5 unchanged; P0's table is the new baseline for P5's bracket-hit-rate gate.

### P1a result (2026-11-06): combos out of bracket 1-2 builds

Shipped: `bracket_repair.py` + `DeckBuilder.swap_out`, wired into both generation paths
(`/api/deck/generate-list` and the direct build job). For requested brackets 1 and 2 it asks the
engine for the graded combo report, cuts the cards that break the most combos (greedy hitting set;
never the commander or partners), refills from goodstuff with the cut cards blocked from coming
back, and re-checks; at most 3 passes / 12 cuts. Engine down means the build ships unchanged and the
report (`bracket_repair` in the generate-list response, a progress line in the job) says why.
Bracket 3 is deliberately untouched (P0: 6/6 already).

Same 6 commanders, `docs/bench/brackets-2026-11-06-repair.json`:

| Requested | Mean estimate before -> after | Exactly right | Within one |
|---|---|---|---|
| 1 | 2.50 -> 1.67 | 1/6 -> 2/6 | 2/6 -> **6/6** |
| 2 | 2.50 -> 2.00 | 3/6 -> **6/6** | 6/6 -> 6/6 |

Every combo was cleared in a single pass (Krenko 14 -> 0, Tymna 10 -> 0 and 8 -> 0, Meren and Atraxa
1 -> 0) and every library stayed 99. Residual: Bracket 1 builds still read as Bracket 2 on measured
strength (fast mana 1.7 and tutors 1.5 on average; the engine names "consistency" and "multiplayer
closing power"). That is a power ceiling, not a rules leak, and is the next lever (P1c, optional:
trim fast mana/tutors at B1 only), not part of this change. Caveat: 6 commanders, one run, partner
decks not in the bench; the bench builds Tymna alone.


## P2 result (2026-11-06): the estimate-driven power trim does not work, so it ships OFF

`bracket_repair.repair_power` swaps fast mana and tutors out of Bracket 1 builds while the engine reads
them above the request, and reverts any pass that raises the estimate. Measured on the 6-commander
roster (`docs/bench/brackets-2026-11-06-p2.json`, B1 only, repair on): mean estimate **1.67, exactly
as before**, and it cost 1-5 s per build. Krenko lost Sol Ring, Dynamo and two goblin tutors; Meren lost
five tutors; both stayed at 2. The refill is goodstuff, so the cut slots come back as Panharmonicon,
The Great Henge, Gilded Lotus: other strong cards. The engine's own reason line for these builds names
consistency and multiplayer closing power, not fast mana or tutors.

Conclusion: the B1 gap is a consistency/closing-power ceiling of the whole card pool, not a few
identifiable cards, so cutting them cannot close it. The code stays (tested, gated by
`MYTHFORGE_POWER_TRIM=1`) so the bench can retry it, but the default build does not run it. Reaching an
honest B1 would need a *weaker* refill (a B1-specific goodstuff query) or a lower-consistency slot plan,
which is P4 territory, not a repair loop. The estimate also moves with analysis runs (40 vs 300 flipped
Tymna 1<->2): a single-sample estimate is too noisy to steer a loop that fine.
