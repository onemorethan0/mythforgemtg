# Plan — validate, then close the two structural gaps under the simulator (2026-09-10)

**Read this alongside [`CLAUDE.md`](../CLAUDE.md)'s engine section (what already shipped, in
prose, dated) and [`PLAN_CLOCK.md`](PLAN_CLOCK.md) (the bracket-*placement* layer — a different
boundary from this file, which is about the *simulator* underneath it). This file exists so a
context cutoff loses no state: each phase records what was measured, what shipped, what was
rejected and why, in dated sub-sections, the same convention `PLAN_CLOCK.md` already uses.
Update it in place as work lands — do not let it go stale while code moves.**

Nothing here is an estimate unless it says so. Every number was either measured this session or
is marked as pending measurement.

---

## 0. Why this plan exists — the review that produced it (2026-09-10)

A multi-session effort (2026-09-08 through 2026-09-10, commits `fe78c27`..`caedd49`) found and
closed a real structural gap: the text→CCM boundary was ~99% gate-instrumented while the
CCM→simulation boundary had **zero** instrumentation and was silently discarding roughly half of
what the store recorded. `mythgauntlet sim-health` (the missing gauge) and `mythgauntlet
ccm-recheck` (re-validates *accepted* CCMs against *today's* gates — nothing else in the
pipeline ever did that) were built, and a long tail of individual ops/compiler-confusions were
closed against them: `pump`, `discard`/`scry`/`surveil`/`mill`, `return_to_hand`/`sacrifice`/
`tap`/`untap`/`extra_turn`, activated-ability interpreter routing, four `x_basis` fixes, an
`extra_turn`-vs-additional-combat compiler confusion, four ETB keyword-licensing gaps, the
`search_library`-vs-bounded-reveal confusion, and a new op (`look_and_select`) for the class that
confusion pointed at. Full history: `git log --oneline fe78c27..caedd49` in this repo, and the
matching commits in the `mythgauntlet` data repo.

**Every one of those fixes was individually verified**: live-recompiled against real cards,
tested, checked for regressions via `ccm-recheck`. **None of them were verified in aggregate**
against the metric that actually matters — does a deck's *rating* get closer to how it actually
performs. That gap, plus two structural capabilities the whole session kept running into and
declining around, are this plan's three phases:

| Phase | Question | Cost class |
|---|---|---|
| **A — Validate** | Did the session's simulator-code changes move bracket calibration, holding the CCM store fixed? | Cheap (~30 min) |
| **B — Combat keywords** | Combat resolution reads no evasion/keyword text at all. Measured 2026-09-10: **39.5% of all 19,709 creature cards** (7,784) carry flying/trample/menace/deathtouch/first strike/double strike/reach/vigilance/hexproof/indestructible. | Medium, staged B1–B6 below |
| **C — Targeting infrastructure** | Every op declined this session for a "chosen target" is the SAME missing capability showing up repeatedly, not five independent gaps. | Medium, unlocks existing declined work rather than adding new coverage |

None of these three phases block each other. They can land in any order; A is listed first
because it's the cheapest and answers whether the *direction* of the last three days was even
correct before investing more hours continuing it.

---

## 1. Phase A — validate: did tonight's simulator code actually help?

**The problem.** `scripts/bracket_accuracy.py` is the project's own accept-bar harness (see
`PLAN_CLOCK.md` §7 — within-one ≥95% is the met, tracked bar). A 40-deck live sample tonight
read 52.5% exact / 92.5% within-one — in the same neighborhood as the last recorded full-corpus
number (53.9%/91.6%, n=546, dated in `PLAN_CLOCK.md`), but **that is not a controlled
comparison**: different sample size, different deck subset, and — critically — the CCM *store*
changed throughout tonight's session too (both my simulator-code edits AND separate compiler
recompiles happened together), so a naive before/after conflates "did the code get better" with
"did the data change."

**The design.** Hold the CCM store **fixed at its current (latest) state** — that's what ships,
reverting it would be dishonest theater — and vary **only the simulator code**, via a git
worktree of `mtg_deck_builder` at the pre-session commit. Run the same harness, same store, same
seed, from both worktrees.

- **"Before" boundary**: commit `21c2a06` (2026-09-07 12:38) — the last commit before this whole
  investigation began (`fe78c27` at 2026-09-08 08:51 is the first fidelity-session commit).
- **"After"**: current `HEAD` (`caedd49` at time of writing, or later if this plan resumes after
  more work landed — always diff against the actual current HEAD, not this pinned hash).
- Both runs point `MYTHGAUNTLET_STORE` at the same, single, current `ccm/` directory. Neither
  run touches it.
- Sample: start with `--limit 150 --runs 40` for a fast first read (a few minutes); if the
  direction is unclear or borderline, escalate to the full labelled corpus (`--limit 0`, or
  omit `--limit`) at the harness's default `--runs`/`--turns` (matches the app's own
  `DEFAULT_ANALYZE_TURNS` — see `PLAN_CLOCK.md` trap #4, "match the app's configuration or the
  number is about nothing").

**Steps:**
1. `git worktree add ../mtg_deck_builder-before 21c2a06` (isolated, does not disturb the working
   tree; matches the `Agent` tool's own `isolation: "worktree"` idea, done manually here since
   this is a direct comparison run, not a subagent task).
2. From the "before" worktree: `PYTHONPATH=src MYTHGAUNTLET_STORE=<current store>
   MYTHGAUNTLET_DATA=<current data> python scripts/bracket_accuracy.py --limit 150 --runs 40
   --json before.json`
3. From current `HEAD` (this checkout): same command, `--json after.json`.
4. Diff: bracket-exact, within-one, signed bias, the confusion matrix, and (if the harness
   supports it) the rule-consistent-subset figures `PLAN_CLOCK.md` §1.1 introduced.
5. Record the result below, dated, whichever way it comes out. **A null or negative result is
   not a failure to hide** — it's exactly the kind of finding `PLAN_CLOCK.md`'s own §4 Phase 1
   (`nut_draw_turn`/1b) recorded honestly when two real, correctly-wired mechanisms both failed
   to move a gate.
6. `git worktree remove ../mtg_deck_builder-before` when done — don't leave it lying around.

**What this phase does NOT need**: it does not need to re-run `axis_separation.py` (that's the
signal-separation gate for *placement* rule changes, a `PLAN_CLOCK.md` concern; nothing in this
session touched bracket placement logic, only what the simulator executes). It does not need a
controlled CCM-store diff — the store isn't the variable under test here, the code is.

### 1.1 — the harness was pointed at the wrong layer, found by running it (2026-09-10)

Ran the controlled test exactly as designed above (git worktree at `21c2a06`, corpus
population matched between worktrees — the current checkout had 93 untracked deck fetches, 17
labelled, that the pre-session worktree lacked; copied them across so both draw from an
identical population before comparing anything). `--limit 150 --runs 40`, same seed, same store.

**The two runs produced byte-identical output — not just the same rounded summary, `diff` on
the raw `--json` files returns nothing.** 57.3% exact / 94.0% within-one / -0.01 bias, cell-for-
cell identical confusion matrix.

**That is not evidence tonight's work made no difference — it's evidence this harness cannot
see tonight's work at all, structurally, and picking it was a mistake.** Traced it rather than
accepting the surprising result at face value:

- `ratings/bracket.py` (the module `estimate_bracket` lives in) has **zero imports** from
  `sim`/`tier`/`interpret` anywhere in the file.
- `estimate_bracket` DOES take simulation-derived parameters (`speed_kill_rate`,
  `avg_kill_turn`, `consistency`) — but they're computed by the CALLER from **tier0**, not
  tier2. Confirmed by reading tier0's own module docstring: *"Commander tax, haste, and
  ACTIVATED ABILITIES ARE IGNORED"* and *"Noncombat damage isn't modeled at rung 1."*
  `grep -n "\.activated\b" sim/tier0.py` and `grep -n "PlayProfile\|interpret_ability"
  sim/tier0.py` both return **zero hits**. Tier0 is a fast, deterministic, intentionally-simple
  goldfish consistency simulator (mulligans/land-drops/color-access/curve) — a genuinely
  separate simulator from tier2, not a lighter view of the same one.
- `estimate_bracket` also accepts `meta_rating` (which WOULD be a tier2 Bradley-Terry figure) —
  but `bracket_accuracy.py` never populates it (matches the already-known "B5 recall was
  structurally 0% until `--real-combos`" finding in `PLAN_CLOCK.md` §1.3, same root shape: the
  harness silently runs a cheaper, blinder path than the live app does).

**Every fix landed 2026-09-08 through 2026-09-10 lives in `sim/tier2.py`,
`semantics/interpreter.py`, or `semantics/profile._activated_from`'s ability-routing branch —
none of which `bracket_accuracy.py` exercises.** The byte-identical result is therefore
expected, not informative, and does not answer the question this phase exists to answer.

**Corrected instrument: `mythgauntlet gauntlet` (Bradley-Terry ratings via real tier2
round-robin duels) or a direct `tier2.duel()` win-rate comparison — not `bracket_accuracy.py`.**
Same controlled-worktree technique, same store held fixed, re-run against the layer that
actually changed. See §1.2.

**Standing lesson for this whole project, not just this phase**: before treating any harness as
"the" validation for a change, check what it actually imports/computes from, the same way this
session's own doctrine already insists on checking a claim before reporting it. A harness
silently running the cheaper/older code path (bracket_accuracy → tier0; the original B5-recall
harness → `--combos 0`) is a repeating shape in this specific codebase, not a one-off.

### 1.2 — the corrected test, tier2: real, substantial movement (2026-09-10)

Same controlled-worktree technique as §1.1 (store held fixed, only `sim/tier2.py` +
`semantics/interpreter.py` + `semantics/profile.py` differ between the two runs), but through
`mythgauntlet gauntlet` — real tier2 round-robin duels, Bradley-Terry ratings — instead of
`bracket_accuracy.py`. A 24-deck deterministic subset (every 24th of 563 labelled decks, sorted,
spanning brackets), `--opponents 8 --games 15 --seed 777 --no-combos` (1,695 T2 games per run,
~2 minutes each).

**Byte-identical was the wrong outcome to expect from the wrong instrument; this one moved for
real.** Mean `|Δrating|` across the 24 decks: **36.9 points**. Signed mean: −0.0 (expected — a
Bradley-Terry system conserves total rating mass, so this is a *reordering*, not an inflation).

The single largest mover: **Tellah, Great Sage (archidekt-25958277), 1806.5 → 1599.3 (−207.2),
win rate 81.7% → 58.3% over the same 120 games (98-22 → 70-50).** That is not noise at this
sample size — it's the kind of swing that would flip a real matchup's expected outcome. Checked
what's plausible before writing this down: Tellah's own commander ability keys off `mana_paid`
(x_basis), which this session's §"THE `x_basis` FIELD HAS NO CLOSED ENUM" work (see CLAUDE.md)
explicitly measured as genuinely unresolvable and left at the honest default — that part of the
deck's behavior should be unchanged by anything that shipped. The swing is therefore coming from
elsewhere in the 99 (or from opponents in the subset gaining), not diagnosed further this
session — that's real follow-on work, not this phase's job.

**What this phase set out to answer is answered: yes, the session's tier2 code changes move
real simulated outcomes, by a magnitude too large to be sampling noise at n=1,695 games.**
Whether that movement is a net *improvement* (ratings getting closer to true relative strength)
or just *different* is a separate question this bounded test cannot resolve on its own — it
would need either a much larger labelled sample run through `gauntlet`/`meta_rating` (feeding
`estimate_bracket`, which — per §1.1 — is the one path that WOULD let `bracket_accuracy.py` see
this layer, and today doesn't) or human/expert spot-review of specific reordered matchups.
Flagged as the natural larger-scale follow-up, not attempted here.

**A concrete, well-evidenced hypothesis worth flagging for whoever picks this up**: several of
tonight's fixes made previously-inert options newly *available* to the greedy agent (activated
abilities routing especially — survival 11.7%→40%). Making an option executable is not the same
as weighing it correctly; `_INTERPRETER_ACTIVATION_VALUE`'s weights (tier2.py) are hand-set, not
measured against the corpus the way this project insists thresholds be measured elsewhere
(`PLAN_CLOCK.md` §6 trap 3). If a newly-visible option is *mis*-weighted, the agent can now make
a worse decision than the old behavior of leaving that mana unspent — a real candidate
explanation for a deck's win rate *falling* after its own capabilities were expanded, and
directly the kind of thing Phase A's own review flagged in the abstract ("an effect firing
correctly can still be weighed wrong by value heuristics") now showing up as a concrete,
measured instance rather than a theoretical concern.

**Verdict for §1**: Phase A's original design (bracket_accuracy.py) was the wrong instrument and
that is now corrected and documented for future work in this codebase, not just this session.
The right instrument (gauntlet/tier2) shows real, large, non-noise movement. Whether it's *net
positive* needs a bigger run or expert review to answer with confidence, and the activation-
weight-calibration hypothesis above is a concrete, actionable next step that's cheaper than a
full corpus re-run and worth doing before scaling this test up.

Worktree cleaned up (`git worktree remove ../mtg_deck_builder-before`) — raw JSON before/after
kept in this session's scratchpad, not committed (regenerable in ~2 minutes from the commands
above).

---

## 2. Phase B — combat keywords: the resolver reads no keyword text at all

**Current state, quoted exactly** (`sim/tier2.py`, the combat model's own scope docstring):
> "Combat: every non-sick creature attacks; the defender makes winning trades and chump-blocks
> only lethal damage. No evasion/keywords (invisible at rung 1-2)."

**This is not a CCM-effect gap** — it doesn't need the LLM compiler, prompt work, or a new op.
It's the *native* combat math the resolver runs regardless of any card's compiled effects, and
it's foundational: it affects whether combat itself produces a correct outcome, for **39.5% of
every creature card in the format**, measured 2026-09-10 (`grep`-verified against the live
Scryfall API and the local card store — Scryfall's own `keywords` field, confirmed live:
`curl https://api.scryfall.com/cards/named?exact=Serra+Angel` returns `"keywords":
["Flying","Vigilance"]`, structured, reliable, and **currently captured nowhere** — `grep -rn
"keywords" src/mythgauntlet/` returns zero hits on the card model).

**Key scoping fact, found this session**: printed (base) keywords are pure DATA from Scryfall,
not something the LLM compiler needs to produce. Only *granted* keywords (a card giving another
creature flying "until end of turn") go through the CCM `grant_ability` op — already partially
modeled (haste only, see `tier2._apply_resolved`'s `grant_ability` branch). This means Phase B
splits cleanly into a cheap data phase (B1) and a series of combat-logic phases (B2–B6) that can
land independently and each be measured on its own.

### B1 — capture printed keywords as data (cheap, no LLM)

- Add `keywords: frozenset[str]` (or similar) to `Card` (`model/card.py`).
- Wire it through the slim-schema fetch (`data/scryfall.py`) — this is a **schema version
  bump**, which this repo treats as a hard, actionable error by design (see CLAUDE.md's card
  store section) rather than a silently-tolerant optional field. Bump `SLIM_SCHEMA_VERSION`,
  regenerate via `mythgauntlet fetch-data --force`.
- No simulator behavior changes yet — this phase is purely "the data exists and is loadable."
  Acceptance: a test asserts a known card (e.g. a fixture Serra-Angel-shaped card) round-trips
  `keywords: {"flying", "vigilance"}` through slim-schema serialization.

### B2 — vigilance (one-line, `game.py:962`)

`_apply_declare_blocks`: `atk.tapped = True  # attacking taps (no vigilance) -> can't block next
turn` — the comment already names the gap. Once B1 lands, gate this on `"vigilance" not in
atk.keywords` (needs `keywords` threaded onto `_Permanent`, not just `GameCard`/`Card` — check
how `is_artifact`/`is_commander` already get copied onto `_Permanent` at construction time in
`_resolve`, same pattern). Cheapest possible first keyword to ship; good smoke test for the
whole B1 plumbing before touching anything harder.

**Shipped 2026-09-09.** `_Permanent.keywords` (+ `has_keyword()`) threaded from `card.keywords`
at both construction sites in `tier2._resolve`; `_apply_declare_blocks` gates the tap on
`not atk.has_keyword("vigilance")` exactly as scoped above. Confirmed `_spawn_tokens` correctly
stays at the empty default — `create_token`'s `OP_SPECS` has no keywords/abilities field, so a
token-granted keyword ("1/1 flying Spirit") is a separate, still-open gap, not a regression here.
Two synthetic regression tests in `tests/engine/test_game.py`
(`test_attacking_taps_a_creature_without_vigilance`,
`test_vigilance_keeps_the_attacker_untapped_and_able_to_block`) pin both outcomes off the same
shape — only `keywords` differs — matching this file's own §5 acceptance bar ("a synthetic
before/after test proving the old resolver gets it wrong and the new one doesn't"). Full suite
(1501 tests) green, including the golden-master test — no existing fixture had a vigilant
attacker, so nothing pinned the old unconditional-tap behavior.

### B3 — flying / reach (block LEGALITY, `agents/greedy.py:49` `greedy_block_assignment`)

`blockers = [c for c in defender.creatures() if not c.tapped]` — currently any untapped creature
can block anything. Needs: a flying (or menace-adjacent-but-simpler-first) attacker can only be
blocked by a creature with flying or reach. This is a **legality filter on the candidate pool**,
not a new decision shape — `greedy_block_assignment`'s existing "winning trades first, then
chump-block" logic stays the same, it just draws blockers from a per-attacker-filtered pool
instead of the whole board. The natural next step after B2 because it's still additive/filtering,
not restructuring the assignment's data shape.

**Shipped 2026-09-09.** `_legal_blockers(atk, blockers)` filters the candidate pool per CR
702.9b (flying attacker -> flying-or-reach blockers only; a non-flying attacker is unaffected,
so a flier can still block a grounded creature) and is applied in BOTH of the function's passes
(winning-trade and chump-block) — the chump pass needed its own filter too, or a defender facing
lethal from a flier would illegally chump-block with a grounded creature. `_block_candidates`
(the ISMCTS-side block enumeration in `game.py`) calls `greedy_block_assignment` directly rather
than reimplementing it, so it inherited the fix with no separate change. Four unit tests in
`tests/engine/test_greedy_block.py` pin both passes and both legality directions. **Closed a real
plumbing gap neither B2 nor B3's own unit tests reached**: nothing had verified `_resolve()`
actually copies `Card.keywords` onto the `_Permanent` it puts on the battlefield (every existing
test hand-built `_Permanent` directly) — two new tests in `test_tier2_interpreter.py` resolve a
real `Card` through the real path and check the resulting permanent's `has_keyword()`. Verified
live, not just via unit tests: `mythgauntlet duel` runs clean end-to-end on real corpus decks
(confirmed `Card.keywords` populated correctly off the live store too, e.g. Serra Angel ->
`{'flying', 'vigilance'}`), and a traced run across 5 real deck pairs / 75 games recorded 201
real flying-attack block decisions, 151 of which had at least one illegal grounded blocker
filtered out of the pool, and 14 of which still found a legal flying/reach blocker to assign —
the fix is actually live in real games, not just reachable in theory. Full suite green (1507
tests) throughout.

### B4 — deathtouch (combat math, `game.py:974-977`)

`if atk.power >= blk.toughness: _kill(opp, blk, ...)` — with deathtouch, ANY nonzero combat
damage from the source is lethal, i.e. the check becomes `atk.power >= blk.toughness or
("deathtouch" in atk.keywords and atk.power > 0)`, both directions (attacker deals it, or a
deathtouch *blocker* kills an attacker that connects with it). Also affects
`greedy_block_assignment`'s own "winning trade" definition — a small deathtouch blocker profitably
trades with something much bigger, which the current `b.power >= atk.toughness` check misses
entirely. **Touches both files together**, so land as one unit.

### B5 — trample (damage assignment, `game.py:973-977`)

Currently a blocked attacker's damage either fully trades with the blocker or (if the blocker
dies) simply vanishes — no excess ever reaches the player. Trample should let `max(0, atk.power
- blk.toughness)` carry over to `opp.life` when the attacker has trample and the blocker dies.
Interacts with B4 (a deathtouch+trample attacker only needs to assign 1 damage to the blocker
before trampling the rest over) — sequence B4 before B5 for that reason, or handle both in the
same change once both are understood.

**B4+B5 shipped together, 2026-09-09** (the interaction made a combined change the natural
shape once both were understood, per the note above). `_Permanent.deals_lethal_to(other)`
(`tier2.py`) is the single shared predicate — `self.power >= other.toughness or
(self.has_keyword("deathtouch") and self.power > 0)` — used in three places so the definition
of "lethal" can't drift between them: `game._apply_declare_blocks`'s combat-damage resolution
(both directions), and `greedy_block_assignment`'s winning-trade pick (`b.deals_lethal_to(atk)
and not atk.deals_lethal_to(b)`, replacing the old plain power/toughness comparison). Trample
excess: `assigned = 1 if atk.has_keyword("deathtouch") else blk.toughness`, `excess = max(0,
atk.power - assigned)`, added to `opp.life` — the deathtouch case matches CR 702.19e (only 1
damage need be assigned to the blocker once it's already lethal via deathtouch). **Extended one
step beyond the plan's literal scope, deliberately, not as creep**: trampled excess to the player
now also accrues `commander_damage_taken` when the attacker is a commander, mirroring the
UNBLOCKED branch three lines above it in the exact same function — omitting it would have been a
freshly-introduced near-miss in a mechanic (commander damage) this codebase already treats as
load-bearing (the S18 fix). Did NOT extend to firing `combat_damage_to_player` triggers off
trampled excess (a blocked attacker doesn't join `unblocked_hitters` today) — a real CR-accurate
nuance, but a separate, independent trigger-plumbing concern from "the life total and commander
damage are right," left as a known open gap rather than bundled in.

Ten synthetic regression tests (`test_game.py`: 7 covering both `deals_lethal_to` directions, the
un-shortcut base case, plain trample, no-lethal-no-excess, the deathtouch+trample combo, and
commander-damage-from-trample; `test_greedy_block.py`: 2 covering the winning-trade pick both
gaining a case via deathtouch and correctly declining a mutual-kill). Verified live: real store
has 352 deathtouch creatures / 988 trample creatures / 1 with both (Odric, Blood-Cursed) — a
first attempt to hand-pick verification examples from memory (Reaper of the Wilds, Thorn
Elemental) turned out to be WRONG (checked live against Scryfall before trusting it: Reaper's
deathtouch/hexproof are activated-ability GRANTS, not printed keywords — correctly absent from
`Card.keywords` by the same design already documented for B1). A traced 6-deck-pair/90-game run
recorded 71 real `deals_lethal_to` calls from a deathtouch source, 16 of which were lethal ONLY
because of deathtouch (the old plain comparison would have gotten these wrong), and 6 real
trample-excess-to-player events — both mechanics are live in real games, not just reachable in
theory. Full suite green (1516 tests) throughout.

### B2–B5 calibration checkpoint (2026-09-09) — closing the loop Phase A opened

Phase A's whole point (§1) was to check whether a code-only change moves real simulated
outcomes, using a controlled technique: hold the CCM store fixed, re-run the exact same 24-deck
subset (`--opponents 8 --games 15 --seed 777 --no-combos`, 1,695 games) before/after. §1.2 ran
that technique against the state right before Phase B started and found real movement (mean
`|Δrating|` 36.9) from that session's broader tier2 fixes. B2–B5 landed since, so re-running the
identical subset/params now (same 24 decks, preserved from §1.2's run) isolates what the four
combat-keyword fixes alone contributed, apples-to-apples.

**Mean `|Δrating|` = 22.2, signed mean 0.00** (zero-sum reordering again, as Bradley-Terry
requires — consistent with §1.2). Smaller than §1.2's 36.9, which is the expected shape: B2–B5
are four narrow, surgical combat-math fixes, not the broad activated-ability/pump/duration
layers §1.2 measured. Real movement, not noise, at this sample size. Biggest movers: **Seluma,
Light of Aysen (archidekt-25709096) 1748.1 → 1832.8 (+84.7)** and **Storm, Force of Nature
(archidekt-10056486) 1610.6 → 1685.0 (+74.4)**, both up; **Peter Parker // Amazing Spider-Man
(archidekt-25772418) 1506.1 → 1466.3 (−39.8)** and **Bjorna, Nightfall Alchemist
(archidekt-25747263) 1227.7 → 1195.7 (−32.0)**, both down.

Checked plausibility before writing this down (same discipline as §1.2's Tellah check): Seluma's
deck carries 38 creatures, **35 of which (92%) have at least one combat keyword**; Storm, Force
of Nature carries 16 creatures, 11 (69%) keyworded. Both are exactly the kind of
keyword-dense deck B2–B5 should move the most, and both moved *up* — consistent with "these
creatures now actually get to use the vigilance/deathtouch/trample/flying-evasion they were
always printed with." **Tellah itself (§1.2's biggest mover, −207.2 from the broader fix set)
barely moved this round (−5.1)** — expected, since its own commander ability keys off
`mana_paid`, unrelated to combat keywords, and §1.2 already established that basis stays at its
honest unresolved default.

Not investigated further (out of scope for a calibration checkpoint, same boundary §1.2 drew for
Tellah): *why* specifically Peter Parker and Bjorna fell, beyond noting Bradley-Terry is
zero-sum so a keyword-dense deck's opponents in the round-robin necessarily absorb some of its
gain. Raw before/after JSON kept in this session's scratchpad (`gauntlet_after.json` from §1.2,
`gauntlet_after_B2B5.json` from this run), not committed — regenerable from the commands above
against the preserved `gauntlet_subset` directory. **This closes Phase B's acceptance gate for
B2–B5**: real, non-trivial, direction-plausible movement, verified against the same instrument
and the same controlled subset Phase A itself validated.

### B6 — menace and first/double strike (STRUCTURAL, size separately before starting)

Both of these are a different *shape* of change from B2–B5, not just a bigger version of the
same filter/threshold edit, and should not be estimated by analogy to B2–B5's cost:

- **Menace** needs 2+ blockers assigned to the same attacker. `DeclareBlocks.assignment` is
  currently `tuple[tuple[int, _Permanent], ...]` — one blocker per attacker index, structurally.
  Supporting menace means either changing that shape to `dict[int, list[_Permanent]]` (cascades
  through `_apply_declare_attackers`, `_apply_declare_blocks`, `greedy_block_assignment`, and
  any ISMCTS-side block enumeration) or a narrower bolt-on. **Measure how many attacking
  creatures in the corpus actually carry menace before designing this** — if it's a small
  population relative to B2–B5's keywords, the ROI may not justify the structural cost yet.
- **First strike / double strike** needs the combat-damage step split into two passes (first-
  strikers deal damage, state-based kills happen, THEN remaining creatures deal damage) instead
  of `_apply_declare_blocks`'s current single simultaneous pass. This is the most invasive of
  the six — it changes the *sequencing* of combat, not just a threshold inside one existing pass.

**Recommendation: land B1–B5 as one coherent slice, re-measure, and treat B6 as its own
follow-on plan phase** (size it with real numbers the way every other decision in this project
gets made, not by assumption) rather than bundling it into the same estimate.

**B6 sized, 2026-09-09 — real numbers, per the plan's own instruction above.** Measured
store-wide creature prevalence (19,202 unique creature cards) for direct comparison against
B2–B5's own shipped keywords: **menace 380 (2.0%), first strike 388 (2.0%), double strike 121
(0.6%)** — for reference, the already-shipped keywords are flying 3,202 (16.7%), trample 975
(5.1%), vigilance 718 (3.7%), reach 434 (2.3%), deathtouch 347 (1.8%). **The population argument
against B6 does NOT hold**: menace and first strike sit in the exact same prevalence band as
deathtouch, which was clearly worth shipping. What actually distinguishes B6 from B2–B5 is not
size, it's shape, exactly as this section already said before any numbers existed — menace needs
a real data-shape change (`DeclareBlocks.assignment`'s one-blocker-per-attacker-index tuple
becoming a multi-blocker mapping, cascading through attack declaration, block resolution,
`greedy_block_assignment`, and ISMCTS block enumeration), and first/double strike needs the
combat-damage step split into two sequential passes with a state-based-action check between them
— a sequencing change, not a threshold or a filter, and the most invasive of all six keywords in
this phase. **Conclusion: worth doing eventually (real, non-trivial, deathtouch-comparable
population), explicitly NOT done in this session** — each of the two sub-problems is its own
small design task (the multi-blocker data shape; the two-pass damage sequencing with SBA
in between), and bolting either onto the B2–B5 pattern under time pressure risks exactly the
kind of near-miss defect this project's own doctrine treats as worse than an honest gap. Left as
a named, sized, ready-to-pick-up follow-on phase rather than attempted at the end of this slice.

### Acceptance gate for Phase B

Following this project's own standing rule (`PLAN_CLOCK.md` §6 trap 1 / the `axis_separation.py`
discipline: *no signal drives a verdict without demonstrated separation*): B1–B5 shipping is not
itself required to move `bracket_accuracy.py` — that's a placement-layer question, a step removed
from "does combat resolve correctly." The gate for THIS phase is narrower and more honest:

- A synthetic test board where the old resolver gets the outcome wrong and the new one gets it
  right, for each keyword landed (a flying attacker connecting through a ground-only defense; a
  vigilant attacker still available to block; a deathtouch 1-power blocker trading up).
- Re-run Phase A's controlled harness (same before/after worktree technique, "before" = the
  commit right before Phase B started) to see whether keyword-aware combat moves calibration —
  record it the same honest way, whichever direction it goes.

**Both bullets satisfied, 2026-09-09.** First: every landed keyword (B2 vigilance, B3
flying/reach, B4 deathtouch, B5 trample) has a synthetic before/after test in
`tests/engine/test_game.py` / `tests/engine/test_greedy_block.py` pinning exactly this shape.
Second: the B2–B5 calibration checkpoint above IS this re-run (same 24-deck subset, same
`--opponents 8 --games 15 --seed 777 --no-combos`, "before" = the state right before B2 started,
captured in §1.2's own run) — real, zero-sum, direction-plausible movement (mean `|Δrating|`
22.2). **Phase B's combat-keyword work (B1–B5) is DONE; B6 is sized and deliberately deferred.**

---

## 3. Phase C — targeting infrastructure: one gap wearing five names

**The pattern.** This session declined the chosen-target majority of `return_to_hand` (2,668 of
3,232 effects), `gain_control` (1,499 of 2,067, and the op was declined *entirely*), `attach`
(every sampled instance), and part of `sacrifice`. Each was declined for the identical reason:
*picking which enemy permanent to hit, or which of my own to boost, is a decision this engine has
no general way to make, and guessing would fabricate.* That is one missing capability, not four
separate op-level gaps — and it already has two real, working, narrow instances to generalize
from instead of building blind:

- `sim/tier2.py:1473` `_instant_target(active)` — picks the active player's **biggest threat by
  power** for reactive removal. "Steal/remove the best enemy creature" shape.
- `sim/tier2.py` `_tutor_pick(me, what)` — picks the **highest-impact matching card** from a
  pool (library), with a missing-combo-piece priority layered on top. "Best of mine, filtered"
  shape, already generalized once this session for `_look_and_select`'s battlefield window.
- `sim/tier2.py` `_weakest_creature(player)` (added this session for `sacrifice`'s edict case) —
  picks the **worst** creature, for "the affected player chooses" shapes (an edict).

**The design question Phase C actually needs to answer**, not yet decided: is a single
`_pick_target(pool, key, direction)` utility (parameterized: rank by what, biggest or smallest,
whose creatures) enough, or do "remove their best" / "boost mine" / "they sacrifice their worst"
need to stay as three distinct named helpers because the CALLING op's cost/benefit reasoning
differs per shape (e.g. `attach`'s pick should weigh "which of my creatures most benefits from
this specific bonus," not just raw impact — a +0/+3 vigilance equipment is wasted on a creature
that's already a wall). **Measure before designing**: sample what each currently-declined op's
`target.controller` values actually look like across the store (mirroring every other
measurement this session did) before committing to one shared function vs. several.

**Proposed sequence** (not yet started, revise if measurement changes the picture):

1. Measure the `target.controller`/`target.type` shape distribution for `return_to_hand`,
   `gain_control`, and `attach`'s currently-declined effects (same method as every op measured
   this session: sample real stored CCMs, bucket by shape).
2. Generalize `_instant_target`'s "biggest enemy threat" pattern into a reusable helper if the
   measurement shows `gain_control`/`return_to_hand`'s declined majority is dominantly
   "opponent's best creature" (steal/bounce tempo plays) — the common EDH shape for both ops.
3. Wire `gain_control` (self/mass already shipped, declined-chosen-target majority is the
   target) through it first — it was declined *entirely* this session (not even a partial
   branch), so it's the cleanest test of the new capability with no prior partial logic to
   reconcile.
4. Re-measure `sim-health`'s partial/inert split for `gain_control` and `return_to_hand` to
   confirm the fix actually shifted effects out of "declined" rather than just adding a branch
   that never fires (the exact self-flattery class `sim-health` itself was built to catch — hold
   this new work to the same bar).
5. `attach` last — it's the biggest population (608/635 cards) but structurally different
   (needs "would this bonus actually help this creature," not just "biggest/best"), so it
   shouldn't block the simpler wins above.

### Acceptance gate for Phase C

- Live-verify (recompile or replay, not just unit-test) that a picked target is never the
  fabricating kind this project's doctrine forbids — e.g. `gain_control` stealing a creature
  must still respect the existing duration/subtype declines already shipped (Act of Aggression's
  duration-reliability finding, the subtype-filtered-mass finding) — Phase C only unlocks the
  *chosen-target* subset, it does not relitigate why the mass/duration subset stays declined.
- `sim-health` shows the targeted op's inert/partial count moving, with the specific before/after
  numbers recorded here the same way every op this session recorded them.

---

## 4. What NOT to do (decided, don't re-litigate)

- **Don't treat "more effects execute" as self-evidently "more accurate."** That's the whole
  reason Phase A exists — it's an unverified assumption, not yet a measured fact, however
  plausible it sounds.
- **Don't build Phase B's menace/first-strike (B6) at the same estimated cost as B2–B5.** They
  are a different kind of change (restructuring combat's sequencing/data shape, not filtering or
  thresholding an existing pass) and deserve their own sizing pass, not an assumption they're
  "just two more keywords."
- **Don't build Phase C as five separate per-op targeting hacks.** That's exactly the pattern
  that produced five separate declines this session in the first place; the point of naming it
  as one phase is to generalize once, per the measurement in step 1, not to ship op #6's bespoke
  picker next week.
- **Don't skip live verification for either B or C on the grounds that unit tests passed.**
  This exact session found three real bugs (the floor-of-1 fabrication, the Augur-of-Bolas
  double-effect risk, the gauge's own three self-flattery bugs) that passing unit tests did not
  catch and a live recompile/duel did.

## 5. Definition of done

- [x] Phase A run and recorded (§1.1, §1.2).
- [x] Phase B1 (keyword data capture) shipped, schema-bumped, tested (2026-09-09).
- [x] Phase B2–B5 shipped, each with a synthetic before/after test proving the old resolver
      gets it wrong and the new one doesn't (B2, B3, B4+B5 all landed 2026-09-09).
- [x] Phase B6 sized (real numbers on menace/first-strike prevalence) before any code is written
      for it (2026-09-09) — concluded "not yet": prevalence is deathtouch-comparable (worth
      doing eventually) but the cost is structural (multi-blocker data shape + damage-sequencing
      change), not a threshold edit, so it's deferred as its own follow-on phase rather than
      rushed. A valid outcome per this checklist's own wording, not a failure to close it.
- [ ] Phase C's shape-measurement (step 1) run and recorded before any picker code is written.
- [ ] Phase C's `gain_control` unlock shipped and reflected in a re-run `sim-health`.
- [ ] This file updated in place, dated sub-sections, as each item above lands — not rewritten
      from scratch, following `PLAN_CLOCK.md`'s own convention of preserving prior dated findings
      even when a later measurement supersedes them.
