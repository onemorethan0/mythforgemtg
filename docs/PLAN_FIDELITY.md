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

### Step 1 measured, 2026-09-09 — and it overturned step 3's own sequencing

Classification (mirroring `_apply_resolved`'s own self/mass check exactly, not a second
reimplementation) over the live store (34,562 CCMs):

| op | total effects | self | mass | chosen (declined) |
|---|---|---|---|---|
| `return_to_hand` | 3,324 | 296 (8.9%) | 342 (10.3%) | **2,686 (80.8%)** |
| `gain_control` | 2,526 | 218 (8.6%) | 488 (19.3%) | **1,816 (71.9%)** |
| `attach` | 798 | 20 (2.5%) | 11 (1.4%) | **767 (96.1%)** |

(Close to but not identical to the store-wide figures quoted earlier in this doc and in
CLAUDE.md — 3,232/2,067 vs 3,324/2,526 — because the store has grown since those were recorded
and the nightly compiler keeps adding cards; same order of magnitude confirms this measurement's
classifier matches the engine's real one.)

**`return_to_hand` and `attach`'s "chosen" populations are clean.** Two random 20-card samples
(seeds 9) of each op's non-self/non-mass effects read as genuinely on-topic for the op every
time — real bounce effects, real Equip/Aura-attach effects, a couple of compound cases (Mantle
of the Ancients' graveyard-to-battlefield-attached is arguably two effects in one) but nothing
mislabeled. These two are ready for picker-generalization work as originally planned.

**`gain_control` is NOT clean — a large fraction of its "chosen" population is a different
effect entirely, mislabeled by the compiler.** Sampled 55 real `gain_control` effects across all
three `target.controller` values (`you`/`opponent`/`any`) with full oracle text, the same
discipline this session used to catch the Reaper-of-the-Wilds mistake in the B4 write-up above.
The `controller: "you"` bucket (524 effects, 28.9% of "chosen") is the worst: of 37 sampled, only
Jon Irenicus and (arguably) one or two others describe anything resembling "gain_control" — the
rest are OTHER effects entirely, wearing `gain_control`'s op name. Categorized by what they
actually are:

- **Blink / exile-then-return** (Gossip's Talent, Ghostway, Turn to Mist) — "exile it, return it
  to the battlefield under its owner's control" is not a control CHANGE (the owner already
  controlled it), it's a temporary removal-and-reset. A separate, real effect shape with no op
  of its own today.
- **`return_to_hand`-shaped** (Cephalid Constable, Tidecaller Mentor, Ares God of War, Ancestral
  Statue, Aether Tradewinds) — genuinely "return X to hand," using the sibling op's own
  vocabulary, mislabeled as `gain_control` instead.
- **"Becomes a creature" / Crew** (Corrupted Zendikon, Subway Train, Unctus's Retrofitter) — the
  ALREADY-KNOWN catch-all pattern from this doc's own gain_control history (CLAUDE.md), now
  confirmed as one slice of a bigger problem, not the whole of it.
- **Restriction / evasion grants** ("can't attack or block", "can't be blocked", "doesn't
  untap") — Whirlwind Killer Cyclone, Spara's Adjudicators, Briber's Purse, Splinter Radical Rat,
  Ty Lee — `grant_ability`-shaped, mislabeled.
- **Monarch** (Crown of Gondor) — an unrelated mechanic; `target.type` is even `"player"`, not a
  permanent, which should have been a structural tell.
- **Play-from-exile / impulse** (Ob Nixilis Captive Kingpin, Bloodsoaked Insight, Chandra Hope's
  Beacon) — "you may play/cast that card" from exile, a distinct mechanic this doc's own
  CLAUDE.md history already names (`impulse` theme) with no dedicated resolution op either.
- **`add_counter`, `sacrifice`-with-condition, graveyard recursion** — one-off further
  mislabelings (Nils Discipline Enforcer, Painwracker Oni, Serra Paragon).
- **Genuinely reversed-polarity gain_control** (Sleeper Agent, Jinxed Ring, Drooling Ogre) — the
  OP is arguably right (a creature/permanent's control changes), but the BENEFICIARY is not "you,
  the effect's controller" — it's "target opponent," a player CHOICE this engine's one-directional
  `gain_control` (which always assumes the caster ends up controlling the result) cannot
  represent at all. Executing these as ordinary `gain_control` would hand the caster control of
  their own creature — a silent no-op at best, backwards at worst.
- **Genuinely correct `gain_control`** (Orcish Squatters, Sliver Overlord, Jet's Brainwashing,
  Geyadrone Dihada, Jeering Instigator, Possession Engine, Govern the Guildless, Merieke Ri
  Berit) — these exist in real numbers too, concentrated more in the `opponent`/`any` controller
  buckets than in `you` (roughly half of the `opponent` sample, a bit under half of `any`).

**This overturns step 3's own reasoning.** The plan proposed wiring `gain_control` first
specifically *because* it looked like the cleanest test case (declined entirely, no partial logic
to reconcile) — that premise is now known to be wrong. A large, uncounted fraction of what
`gain_control` "declined" was never a targeting-infrastructure gap at all; it's a compiler
op-vocabulary confusion that a `_pick_target` helper would paper over by confidently executing
the WRONG effect (stealing a creature for a card that actually meant tap-lock, or return-to-hand,
or nothing related to control at all). Building Phase C's picker against this population first
would be building on the exact kind of near-miss defect this project's whole doctrine exists to
catch — worse than declining, because it would look wired and be wrong.

**Revised sequencing, effective now**: start Phase C's picker-generalization work on
`return_to_hand` (confirmed clean, 80.8% of its own effects, 2,686 real chosen-target bounces)
instead of `gain_control`. Treat "diagnose and fix `gain_control`'s op-vocabulary confusion at
the compiler layer" as its own separate, sized-but-not-yet-scoped follow-on item — it needs the
same kind of prompt-guidance/gate work this session already did for the extra_turn-vs-combat-
phase confusion and the search_library-vs-bounded-reveal confusion (both cited elsewhere in this
doc), not a simulator-side fix. Rough scope from this sample: at least 7 distinct real effect
shapes are hiding under `gain_control`'s name, several of which (blink, restriction/evasion
grants, impulse-play-from-exile) have no dedicated op today either — this is closer in size to
the `look_and_select` op-creation effort than to a prompt tweak. Not attempted this session;
sized and recorded here so it can be picked up on its own.

### `return_to_hand`'s chosen-target picker — shipped 2026-09-09

Scoped narrowly and precisely rather than to the full 2,686-effect "chosen" population,
following this project's own repeated discipline of shipping the safe subset first and
measuring before widening (the same shape as `pump`/`sacrifice`/`add_counter` all shipping
self-or-mass-only originally). Two more measurements narrowed the scope further than step 1's
headline numbers suggested, each done BEFORE writing code, not after:

- **This engine has no graveyard zone** (already true of `discard`/`scry`/`mill`/`surveil`, see
  `tests/engine/test_hand_library_ops.py`'s own docstring) — ~39% of the "chosen" population
  (1,047 effects, `zone: "graveyard"`) is recursion, permanently out of scope regardless of
  picker quality. A real minority of graveyard-sourced effects omit the `zone` field entirely
  even though their oracle text says "from your graveyard" (Shipwreck Dowser is one) — caught
  because `type` itself is diagnostic: `instant`/`sorcery`/generic `"card"` can never be a
  battlefield permanent, so those types are declined regardless of what `zone` says or doesn't.
- **Cross-tabbing `controller` against `type`/`zone`** (not just reading the marginals) found
  the two unambiguous-direction populations smaller than the headline suggested: **505 effects
  / 417 cards** for `controller: "you"` (any real permanent type: creature/permanent/artifact/
  land/enchantment, battlefield-only) and **40 effects / 33 cards** for `controller:
  "opponent"`/`"each_opponent"` restricted to `type: "creature"` (a non-creature permanent's
  `power` is always 0 in this engine, making "biggest by power" meaningless for that side).

**Implementation**, both directions reusing an EXISTING picker rather than inventing a new
metric per the plan's own design question: `_best_of_mine_to_bounce(player, exclude)`
(`tier2.py`, new) ranks MY OWN permanents by `.source.profile.impact` — the exact "best of
mine" metric `_tutor_pick` already uses, reused rather than re-derived — excluding both tokens
(no card to re-cast) and the permanent whose ability is currently resolving (a bounce ability's
target is conventionally "ANOTHER target permanent you control"). The opponent direction calls
`_instant_target` (unchanged) across every opponent's board via the EXISTING `_affected_boards`
helper (already used by the mass branch two lines above — one definition of "who counts as an
opponent" in a multiplayer pod, not a second one that could drift) and bounces the single
biggest-power creature found. Everything else — `any`/absent controller (the genuinely ambiguous
53% majority), non-battlefield zones/types — stays declined exactly as before.

**A real, fourth instance of this project's most-repeated bug class, found by this exact
change**: adding the new code changed `_apply_resolved`'s `return_to_hand` branch from a flat
`if self / elif mass` (falls through silently, correctly read as "guarded" by `sim/health.py`'s
detector) to `if self / elif mass / else: <setup> if you: ... elif opponent: ...` — a REAL
terminal `else` whose own body is a further guarded if/elif. `sim/health.py`'s `_has_unelsed_if`
only ever checked "does the chain terminate in a real else", not "does that else's own body
still fall through one level deeper" — so `return_to_hand` silently dropped out of the guarded
set the moment this shipped, which `test_an_if_elif_chain_with_no_else_reads_as_guarded`
(pinned at the top of Phase B this session) caught immediately. Same self-flattery shape
CLAUDE.md already documents twice over (branch-exists-≠-effect-happens; the elif-chain not
walked) — this is the third instance in the gauge itself, fixed by recursing into a real else's
own body rather than treating "has a body" as "handles every case." A new synthetic test
(`test_a_guarded_if_elif_nested_inside_a_real_else_still_reads_as_guarded`) pins the AST shape
directly, independent of `return_to_hand`'s own implementation ever changing again.

**Verified.** Nine synthetic tests (`tests/engine/test_return_to_hand_chosen.py`) cover both
directions, the token/self-exclusion, the multiplayer-pod reach, and all three still-declined
shapes (any, absent, graveyard, non-creature-opponent). Live, not just unit-tested: a real
stored card, **Into the Flood Maw** (`{"op":"return_to_hand","target":{"type":"creature",
"controller":"opponent","count":1}}`), resolved end-to-end through the real semantics store
correctly bounced the bigger of two opposing creatures to its owner's hand. A traced 10-pair/
150-game duel run found the `you`-direction firing **11 times** in real games with no crashes;
the `opponent`-direction fired **zero** times in that same sample — checked whether that meant
broken rather than merely rare (70 real cards carry the shape store-wide, a much smaller
population than `you`'s 417 cards) by resolving Into the Flood Maw directly, which confirmed the
mechanism works and the zero count is sampling rarity, not a defect. Full suite green (1526
tests).

### `attach` — the TARGETING shape is clean, the BONUS itself is not representable at all (2026-09-09)

Started `attach` next (per the plan's own ordering — the third and last op step 1 measured
clean) and found the real blocker sits one layer under targeting. Every sampled Equipment/Aura
card stores its actual bonus — "+2/+1", "gets +0/+3 and has vigilance", "Equipped creature has
flying" — as a **free-text `note` on a `kind:"static"` ability, with no structured op/amount/
keyword field at all**. Measured store-wide: **17,438 static abilities, EVERY ONE note-only**.
Even a perfect `attach` picker would move an Equipment onto the right creature and grant it
nothing, because the bonus doesn't exist anywhere machine-readable to apply.

Refined before treating this as one giant number, the way this session treats every population:
cross-referencing each note against the card's own `Card.keywords` (Phase B1's Scryfall-backed
field) shows **10,169 of 17,438 (58.3%) are pure printed-keyword restatements already covered**
by Phase B — "Flying", "Trample, Ward {2}" and similar are functionally fine even though the CCM
itself never structures them. The genuine, still-open gap is the other **7,268 (41.7%)**:
anthems and other-affecting statics ("Other creatures you control get +1/+1", "Other untapped
creatures you control have hexproof"), attach/enchant bonuses (attach's own 496-of-608-card
problem — Vow of Lightning: "Enchanted creature gets +2/+2, has first strike..."), cost
reductions ("Creature spells you cast cost {1} less"), characteristic-defining values (Duggan's
"power and toughness are each equal to the number of cards in your hand"), block/attack/cast
restrictions on self or others, and replacement effects. **This is a CCM-schema-level gap, not a
simulator dispatch gap** — fixing it needs a structured static/continuous-effect sub-schema,
prompt + gate work, a corpus recompile, AND simulator-side infrastructure to apply a CONTINUOUS
effect at all (this engine has no layer system — see `expire_until_end_of_turn`'s own docstring,
built for temporary buffs only). Almost certainly the single largest remaining representational
hole in the whole CCM->simulator pipeline, bigger in scope than the `gain_control` confusion
above. **Not attempted this session — sized and recorded, `attach` stays blocked on it.**

### Death-triggered effects: a third gauge blind spot, and Undying shipped (2026-09-09)

Investigating `reanimate` (the CCM op for "put a card onto the battlefield", declared in
`ccm.OP_SPECS` and — per this doc's own earlier notes — never dispatched anywhere) surfaced two
more findings before any code was written, plus one real fix.

**Finding 1 — `sim-health` itself couldn't see what happens to `death`-triggered abilities.**
`ccm._EXECUTED_EVENTS` names `"death"` as engine-executed and calls `sim/tier2._EVENT_TRIGGERS`
"the authority" — but `_EVENT_TRIGGERS` does not contain `"death"` at all. It IS executed, just
through a THIRD, separate flattening (`semantics/profile._death_from`, 5 fixed ops: draw/
lose_life/deal_damage/gain_life/create_token) that a death-triggered ability's effects go
through instead of `_apply_resolved` — and `sim/health.py`'s `analyze_store` didn't know this
path existed, so it judged every death-triggered effect against the WRONG vocabulary
(`_apply_resolved`'s "resolved" set) by default. **This is a real, 5th instance of the gauge not
seeing everything** — this project's most-repeated bug class, and a different SHAPE from the
4th (a whole missing dispatch path this time, not a detection gap within one already-targeted
function). Fixed: `executed_ops()`/`analyze_store` now read `profile._death_from`'s own AST as
a third vocabulary (`"death"`) and route `kind:"triggered", trigger:"death"` abilities through
it. Verified: `reanimate` now reports as a clean, correctly-attributed 132 cards / 140 effects
inert (previously silently misjudged); `executed_share_ceiling` moved down (0.6847 -> 0.6723),
the expected direction for a gauge becoming MORE honest, not less.

**Finding 2 — the compiler is inconsistent about which op it picks for "put a card onto the
battlefield," and it isn't only `reanimate` at stake.** Sampling `return_to_hand`'s and
`gain_control`'s "any"/absent-controller populations with real oracle text (re-testing my own
earlier "genuinely ambiguous, decline" call from the return_to_hand writeup rather than assuming
it — the call held for genuine bounces, but a large share of that same bucket turned out to be
BLINK effects — "exile it, return it to the battlefield" — mislabeled under `return_to_hand`'s
or `gain_control`'s op name, e.g. Momentary Blink, Galepowder Mage, Spaceshift, Abuelo). A
store-wide scan for the oracle-text signature "battlefield under \\<its/their/his/her\\> owner"
found it scattered across **return_to_hand (173 cards), exile (146), gain_control (49),
add_counter (42), reanimate (20, i.e. correctly labeled), draw (17)** and a long tail of ~55
other op values — including several UNOFFICIAL, schema-tolerated-but-never-dispatched invented
names the compiler minted for the same idea (`return_to_battlefield`, `put_into_play`,
`put_into_play_under_control`, ...). `reanimate` already exists in the vocabulary for exactly
this pattern; the compiler simply doesn't use it consistently. **This is its own follow-on
item** — prompt guidance naming the confusion explicitly (the same fix shape as this session's
earlier extra_turn-vs-combat-phase and search_library-vs-bounded-reveal fixes) plus a recompile
of the affected population — not attempted this session, but the `return_to_hand`/`gain_control`
"any"/absent declines it flows through remain SAFE regardless (declining means neither wrong op
executes the wrong thing).

**What shipped: Undying (CR 702.92c), reached through `Card.keywords` rather than the CCM's own
inconsistent `reanimate` op.** Measuring `reanimate`'s self-target population precisely (not the
rough estimate from the first pass) found only 18 cards genuinely shaped as a `death`-triggered
self-return with a checkable condition — small, and most of those conditions are literally
Undying's own wording ("if it had no +1/+1 counters on it") or Persist's ("...no -1/-1 counters
on it"). Checking `Card.keywords` directly (Phase B1's Scryfall-backed field, the same source
that already carries `undying`/`persist` as printed keywords) found a materially larger and far
more reliable population: **22 real Undying creatures, 24 real Persist creatures store-wide** —
worth building against `Card.keywords` instead of the CCM's inconsistent op, exactly matching
the reasoning that made Phase B's combat keywords reliable in the first place. **Persist is
declined**: `_Permanent.counters` is a single undifferentiated int (`add_counter`'s own comment:
non-+1/+1 counter types are "tracked in `.counters` ... but no P/T ... interaction"), so "had no
-1/-1 counters" is not answerable without either building real counter-type tracking or
fabricating. **Undying shipped**: in `tier2._kill`, `has_keyword("undying") and counters == 0`
returns the permanent to the battlefield with a +1/+1 counter, resetting it as a NEW OBJECT per
CR 400.7 (sickness, tap state, and any "until end of turn" temp buff all reset, mirroring
`expire_until_end_of_turn`'s own subtract-back-out pattern) — composes correctly with the
existing self-death-trigger mutations (draw/drain/gain_life/tokens still fire) and with mass
kills (`_wipe_table`/the sacrifice-mass loop both snapshot via `list(player.creatures())` before
killing, so a returning creature is never double-processed in the same wipe). A returning
creature's own ETB does NOT re-fire — a known, documented under-count, not attempted this
session (would need `_kill` to reach back into resolve-ability machinery it doesn't have access
to today). Eight synthetic tests (`tests/engine/test_undying.py`) plus live verification: a
real store card (Butcher Ghoul) resolved through the real pipeline correctly returns as a 2/2
with a counter on its first death and stays dead on a second (the counter now blocks the
condition) — and a traced 15-pair/225-game duel run found it firing twice with no crashes,
consistent with its small (22-card) population. Full suite green (1534 tests).

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
- [x] Phase C's shape-measurement (step 1) run and recorded (2026-09-09) — and it changed the
      plan: `return_to_hand`'s TARGETING shape is clean, `gain_control`'s is not (a compiler
      op-vocabulary confusion). `attach`'s targeting shape is ALSO clean, but its underlying
      BONUS is a much bigger, separate blocker — see below, corrected from this line's first
      draft which called it simply "clean, ready for picker work."
- [x] Phase C's picker generalized from `_instant_target`/`_tutor_pick`'s existing metrics,
      wired through `return_to_hand`'s two unambiguous directions (2026-09-09, re-sequenced
      from `gain_control` per the step-1 finding) — `you` (505 effects/417 cards, ranked by
      source-card impact) and `opponent`+creature (40 effects/33 cards, `_instant_target`
      reused as-is across the pod). `any`/absent controller and graveyard/non-permanent types
      stay declined (fabrication risk / no graveyard zone, respectively). Found and fixed a
      real, fourth instance of the gauge's own most-repeated self-flattery class in the
      process (`_has_unelsed_if` didn't recurse into a real else's own nested guarded
      if/elif) — see the writeup above.
- [ ] `return_to_hand`'s own `any`/absent-controller majority (53% of "chosen", genuinely
      ambiguous — needs a real decision, not a default guess).
- [x] `attach` investigated (2026-09-09) — concluded blocked, not "not yet started": its
      targeting shape is clean, but 17,438 static abilities store-wide (496 of attach's own 608
      cards) store their bonus as unstructured prose with no op/amount/keyword field at all.
      10,169 of those are keyword restatements Phase B1 already covers; the genuine 7,268-
      ability gap (anthems, cost reduction, characteristic-defining P/T, attach/enchant bonuses,
      replacement effects) needs a new CCM sub-schema + prompt/gate work + a corpus recompile +
      simulator-side continuous-effect infrastructure this engine doesn't have (no layer
      system). Sized as likely the largest remaining representational gap in the pipeline;
      recorded as its own major follow-on, not attempted this session.
- [x] `reanimate` investigated (2026-09-09) — never dispatched anywhere (confirmed); the
      compiler is inconsistent about which op it picks for "put a card onto the battlefield"
      (return_to_hand/gain_control/reanimate/~55 other op values all used for the same real
      pattern across the store) — its own sized-but-unscoped follow-on, same shape as
      `gain_control`'s confusion. **Undying (CR 702.92c) shipped** from this investigation,
      reached via `Card.keywords` rather than the CCM's unreliable `reanimate` op (22 real
      creatures store-wide); Persist stays declined (needs counter-type tracking this engine's
      single undifferentiated `.counters` field doesn't have).
- [x] Found and fixed a 5th instance of the `sim-health` gauge's own self-flattery class
      (2026-09-09): `analyze_store` judged death-triggered abilities' effects against
      `_apply_resolved`'s vocabulary, but they never reach it — they go through a THIRD,
      separate flattening (`profile._death_from`) the gauge didn't know existed. Fixed by
      reading that function's own AST as a third dispatch vocabulary, same "read the source,
      never restate it" discipline as the other four fixes.
- [ ] `gain_control`'s compiler-layer op-vocabulary confusion diagnosed further and fixed —
      its own follow-on item, sized but not scoped, do not bolt it onto the picker work above.
- [ ] This file updated in place, dated sub-sections, as each item above lands — not rewritten
      from scratch, following `PLAN_CLOCK.md`'s own convention of preserving prior dated findings
      even when a later measurement supersedes them.
