# Myth Forge backlog (opened 2026-11-04)

The single list of identified work. `STATUS.md` is the one-page summary; this file is the detail:
every item has evidence, an acceptance test, the first command to run, and an owner. Update the
**Status** column when something moves, and move finished items to the Done table at the bottom.

Owner key: **C** = Claude (rules-facing, surgical, or design), **N** = the local nodes (compute and
sweeps only; see STATUS.md section 3 for why they do not author code), **U** = needs the user's
decision or go-ahead (outward-facing, or a product call).

| ID | Item | Status | Owner |
|---|---|---|---|
| B1 | Mentor holistic bench vs the 87-90/90 bar | CLOSED: 87/90 after 3 gate fixes | C |
| B2 | Builder bench vs `docs/bench/current.json` | CLOSED: metric effect, baseline refreshed | C |
| B3 | Static abilities: anthems, cost reducers, CDA P/T | anthems DONE (tier2 + tier0); COMPLETE: cost reducers in the duel sim, 'other' is long-tail | C |
| B4 | Compile-quality gate for blink / `gain_control` mislabels | DONE: gate + recompile + 4 authored | C |
| B11 | Self-target / off-battlefield exile ran as removal | DONE (found during B4 review) | C |
| B12 | Own-side effects hitting the opponent (pain mana, mass recursion) | DONE via effect_audit.py; 93 ambiguous left | C |
| B5 | Bracket recall: B4 34%, B1 49% (B5 is 85%, the old 36% was stale) | DIAGNOSED: labelled-data limit, no tuning | C |
| B6 | Mentor gate under-flags a moderate band | design question | U |
| B7 | Test gaps | ongoing (model3d + routes_misc now covered; strength mentor/breakdown/card-impact/feedback routes now covered); 9 bugs found by writing tests (1 path traversal) | C |
| B13 | JS<->Python drift (parity tests) | DONE: 2 divergences fixed, 4 mirrors locked | C |
| B8 | Refresh the published CCM snapshot | DONE: published 2026-11-04, download hash verified | C |
| B9 | Role-strength granularity (S13) | DECIDED 2026-11-04: keep strength unit (owner call); closed | U |
| B10 | Offload harness follow-ups | deferred: no consumer (see section) | C |
| B14 | Deck building: measure bracket as a target (P0) | specced in `DECKBUILD_REVIEW.md` | C |
| B15 | Bracket as target + close the loop (P1, P2) | specced; depends on B14 | C |
| B16 | One role vocabulary, data-driven slot plan (P3, P4) | specced | C |
| B17 | Strength-aware builder bench (P5) | specced | C |
| B18 | Build-path structure and component tests (P6), UX pass (P7) | specced | C |

---

## B1. Mentor holistic bench
**Why:** `mentor_holistic_bench.py` and the Shelob bench were never re-run after the 2026-10-23/25
mentor changes (castability prefetch, table-feel salt wording, key-card lead, swap split).
**Run:** `python scripts/mentor_holistic_bench.py --json docs/bench/mentor_holistic_2026-11-04.json`
(needs llama-swap on :8010; about 30 min). Then `scripts/mentor_bench.py` on Shelob.
**Accept:** holistic >= 87/90 and Shelob >= 47/52 (the bars from 2026-10-02). Below that: list the
failing cells, read the replies (a rubric failure OR a pass can be wrong), fix, re-run only those.
**Record:** the result goes in `STATUS.md` section 4.
**Result 2026-11-04 (first run):** 84/90 (93%), just under the 87 floor. Of the 6 failing cells in the
stored run, **5 are the gate's honest fallback** ("I couldn't put together an answer I'm confident is
fully accurate": shelob cards, ghired overview + cards, isshin overview, arahbo cards) and 1 is a
missing resilience verdict (ghired). No fabricated claim shipped in the stored run (77/81 passed the
gate first try). Model variance is documented at 2-3 cells, so this is borderline, not conclusive.
**CLOSED 2026-11-04: 87/90 (97%), zero fallbacks.** Four runs: 84, 81, 84, **87**. The reply text in
the early runs was mostly the gate's fallback, and reading the rejection reasons found three real
defects, each fixed with tests: (1) the table-feel matcher read "the most salty cards are Sol Ring"
and "less salty than 85% of decks" as calling a friendly deck salty (commit 5 in the mentor series);
(2) a faithful draft rejected ONLY for length (2554 > 2400) regenerated identically three times, so
the retry now says how to shorten and the last attempt trims at section boundaries; (3) a follow-up
after a fallback echoed it in ~1 s with no tool call, so the mentor's own fallback turn is dropped
from history. Remaining misses (3): two `resilience` cells with no verdict phrase (tymna 29/100,
arahbo 58/100) and `arahbo overview` claiming 'fast' for a slow deck; model phrasing, not gate
bugs, and within the documented 2-3 cell variance. The Shelob bench (`mentor_bench.py`, bar 47/52)
was not re-run; do it if the mentor changes again.
**Superseded plan (kept for the record):** re-run once (node 1 is busy recompiling B4), then compare cell by cell. If the same cells
fail twice the cause is real: look at `rejections` in the JSON for why the gate refuses (suspects: the
10-25 key-card lead and table-feel wording changes interacting with gate checks 7/16).

## B2. Builder bench
**Why:** the 10-23 `toughness` theme changed builds for the 11 toughness commanders; the bench was
not re-run. **Run:** `python scripts/builder_bench.py --out docs/bench/current-2026-11-04.json`
then `--compare docs/bench/current.json docs/bench/current-2026-11-04.json`.
**Accept:** no commander regresses outside noise; a degraded run (Scryfall rate-limited) is
discarded and re-run, not counted. Refresh `docs/bench/current.json` only if the comparison is clean.
**Result 2026-11-04:** 20/20 valid, 0 dropped, every commander's verdict unchanged, mean synergy
15.85 -> 15.62. One summary figure moved: `mean_weakest_theme_cards` 9.12 -> 7.22. The baseline is
from 2026-08-18, so code AND live Scryfall data both drifted. **Disambiguating run in progress:** the
baseline commit (45235c0) in a worktree, run on today's data (worktree since removed).
**Answer: it is a code change, not data drift, and it is narrow.** The baseline code on today's data
reproduces the August figure exactly (9.57 on the 7 comparable multi-theme, non-degraded commanders;
the run also dropped Atraxa and Tom Bombadil for empty Scryfall role queries, correctly discarded).
HEAD differs on exactly two of the seven: **Talrand** weakest theme 10 -> 6 (voltron_combat) and
**Muldrotha** 11 -> 6 (reanimator); the other five are identical. Synergy did not fall (Talrand
16.7 -> 17.0, Muldrotha 11.2 -> 11.3) and no verdict changed, so this may be an improvement (fewer
cards in a spurious theme) rather than a regression.
**Closed 2026-11-04 (B2b):** read the theme sets instead of bisecting. Talrand gained a *third
detected theme* (`voltron_combat`, 6 cards) while its on-theme total stayed 31 (spellslinger 10 -> 19,
tokens 24 -> 16); Muldrotha has the same two themes and the same on-theme total (16), with the
reanimator count 11 -> 6 (a counting shift after the 520e2df reanimator-pattern fix). The "weakest
theme" figure falls mechanically whenever a theme is added, so this is a metric effect, not worse
builds. `docs/bench/current.json` is refreshed from the 2026-11-04 run. `builder_bench` gained
`--only` (comma-separated ROSTER names) for future bisects; a partial run is not comparable whole.

## B3. Static abilities (the largest remaining hole)
**Measured 2026-11-04 (`scripts/static_scan.py`):** 16,555 note-only statics (no op, free text).

| Bucket | Count | Share | Tractable? |
|---|---|---|---|
| keyword_only (already `Card.keywords`) | 6,870 | 41.5% | nothing to add |
| restriction ("can't attack", "enters tapped" ...) | 1,509 | 9.1% | partly; false positives in the scan |
| cost_reduction | 487 | 2.9% | yes, closed template |
| anthem_kw ("creatures you control have K") | 362 | 2.2% | yes |
| anthem_pt ("creatures you control get +N/+N") | 232 | 1.4% | yes, the first target |
| cda_pt ("power is equal to ...") | 219 | 1.3% | yes but needs a count basis per card |
| other | 6,876 | 41.5% | NOT regex-able; a labelling queue |

This corrects the earlier "7,268 open" framing: the clean, deterministic core is roughly **1,300
cards** (anthem_pt + anthem_kw + cost_reduction + cda_pt), not 7,000. The rest is heterogeneous.

**Phase 1 DONE 2026-11-04 (parser only, nothing wired to the sim yet):** `compiler.parse_anthem` +
`anthem_for_card` (28 tests). Strict closed template (creatures / other / nontoken, "you control" or
"your opponents control", literal +N/+M, closed keyword vocabulary, whole-note reject). **Corrected
sizing: 107 cards parse cleanly, not ~600.** But they sit in **293 of 1,154 corpus decks (25.4%)**
(94 decks carry two or more), so phase 2 reaches one deck in four. A 30-card random hand-check read
against oracle text found 0 wrong parses and exposed one trap, now closed: an anthem inside a
modal bullet (Frostcliff Siege) only applies if that mode was chosen, so `anthem_for_card` requires
the note to be a whole printed oracle line (ability-word prefixes decline: honest under-count).
**Still to decide for phase 2 (needs a schema call):** statics have no `effects`, so the parsed
anthem needs a home. Recommended: a new optional `anthem` object on the static ability, validated by
the schema, filled by the compiler and by a no-GPU backfill (like `backfill_attach_grants.py`).

**Phase 2 DONE 2026-11-04 (tier2 duels), and it needed NO schema change.** The recommendation above
(an `anthem` object on the static ability) was dropped in favour of deriving the anthem at profile
time: `profile._anthems_from` reads the note-only static and `anthem_for_card` (so a modal bullet
still declines) into `PlayProfile.anthems`; nothing in the CCM store was rewritten, no backfill,
nothing in the sibling repo touched. Sim: `_Permanent.anthems` on the source, `anthem_delta` /
`anthem_keywords` on the affected creature (their own fields, so an anthem leaving never deletes an
equipment's keyword or a temp pump), and `tier2.refresh_anthems`, a FULL recompute (subtract old
delta, add new) called wherever combat rules are refreshed (turn start, each combat), idempotent,
with state-based death at 0 toughness repeated to a fixed point. 13 tests.
**A/B (gauntlet --opponents 8 --games 20 --seed 777, 1,153 decks):** bracket means identical within
1 Elo. Dose-response is clean: decks with no anthem -1.2 (noise), one anthem +3.4, two or more
+6.2; the top gainers hold 2-4 anthems. Small by nature (one card in 99) but pointed the right way.
**Phase 2b DONE 2026-11-04: tier0 (the goldfish clock behind `analyze`) now sees anthems.** It is
rung-1/CCM-free, so `tier0._anthems_in_text` reads the card's own oracle lines with the same strict
parser (flat power bonuses to your own creatures only; `nontoken` skipped as an honest under-count;
a lord never buffs itself; a creature-sourced anthem dies in a wipe, an enchantment survives;
instants and sorceries never count). 7 tests, suite 3,094 green. **Guard run (bracket_accuracy,
624 labelled decks, real combos): within-one UNCHANGED at 92.1% (96.3% excluding impossible
labels), as the strength model's zero weight on the goldfish clock predicted. Cost, stated plainly:**
3 decks moved B1 -> B2, all three labelled B1, so exact slips 59.5% -> 59.0% (371 -> 368) and B1
recall 48.8% -> 46.5%. They are go-wide decks whose anthems now count and self-labels skew low, so it
ships; revert is removing the three `anthem_*` blocks in `tier0._run_one`.
**Cost reducers: DONE in the duel simulator (2026-11-04); tier0 deliberately left alone.** The tier0
wiring was reverted by the bracket guard (within-one 575 -> 574; 4 of 5 changed decks moved away from
their label). The DUEL simulator does not feed the bracket, so reducers live there: `sim/cost_rules.py`
(strict parser reuse, subject matching, `discounted`, `total_discount`), `_Permanent.cost_reducers`,
and ONE helper `tier2.cast_cost(player, gc)` that replaced all 13 places the duel sim read a card's
cost (legal-action enumeration, the commander cast with tax-then-reduction per CR 601.2f, counter and
instant-removal windows, the apply paths, `_find_counter`, `_find_instant_removal`, and the greedy
agent), so legality and payment cannot disagree. 10 tests, including "an unaffordable spell becomes
legal AND payable and spends the discounted amount". Suite 3,460 green (the golden-master tests pin
decks without reducers). **A/B (gauntlet seed 777, 1,153 decks): bracket means within 2 Elo; 404 decks
with a reducer +2.8 mean, 749 without -1.5.** Bracket accuracy not re-run: tier0 is unchanged.
**Phase 2b DONE 2026-11-04: tier0 (the goldfish clock behind `analyze`) now sees anthems.** It is
rung-1/CCM-free, so `tier0._anthems_in_text` reads the card's own oracle lines with the same strict
parser (flat power bonuses to your own creatures only; `nontoken` skipped as an honest under-count;
a lord never buffs itself; a creature-sourced anthem dies in a wipe, an enchantment survives;
instants and sorceries never count). 7 tests, suite 3,094 green. **Guard run (bracket_accuracy,
624 labelled decks, real combos): within-one UNCHANGED at 92.1% (96.3% excluding impossible
labels), as the strength model's zero weight on the goldfish clock predicted. Cost, stated plainly:**
3 decks moved B1 -> B2, all three labelled B1, so exact slips 59.5% -> 59.0% (371 -> 368) and B1
recall 48.8% -> 46.5%. They are go-wide decks whose anthems now count and self-labels skew low, so it
ships; revert is removing the three `anthem_*` blocks in `tier0._run_one`.
**Cost reducers: parser shipped, tier0 wiring TRIED AND REVERTED (2026-11-04).** 61 permanents print a
closed unconditional generic reducer ("Instant and sorcery spells you cast cost {1} less to cast"), in
35% of corpus decks. `compiler.parse_cost_reducer` is strict (generic mana only, closed subject list,
whole line; 12 tests) and stays. I wired it into the tier0 goldfish clock (reducers apply when their
source resolves, creature sources die in a wipe) and ran the standing guard (bracket_accuracy,
624 labelled decks): **within-one 575 -> 574 (92.1% -> 92.0%, below my own "no drop" rule), exact
59.0% -> 58.7%, and of the 5 decks whose bracket changed, 4 moved AWAY from their label, 1 closer.**
Reverted per the rule. The effect is real but lands on the bracket estimate; the DUEL simulator is
the better home because it does not feed the bracket. Cost there is the ~10 scattered `card.cost`
sites in `game.py`/`tier2.py` (legal-action generation and payment must agree, or a card is
offered that cannot be paid). Raw data: `docs/bench/bracket_accuracy_2026-11-04_reducers.json`.
**The 'other' 41% re-examined (`scripts/static_clusters.py`, 2026-11-04): it is NOT 6,876 cards of
unmodelled mechanics.** Clustering by template, the largest shapes are already handled elsewhere:
Equipment/Aura bonuses ("Equipped creature gets +2/+2": ~690 notes) are carried by the `attach` op's
grant, and the keyword reminder lines (Devoid, Convoke, Shadow, Changeling, Kicker, Bestow, Soulbond,
Toxic, bare "Protection from X") are `Card.keywords`. The 5-word-shape distribution is flat (2,275
shapes; the top 45 cover 30.7%, and most of those are the two groups above). What is genuinely left is
bespoke conditional self-pumps ("this creature gets +2/+2 as long as ...": ~100; "... for each X":
~80; "as long as you control ...": ~76) with no shared template, plus ~100 combat-conditional ones
("as long as this creature is attacking, it gets +2/+0", "during your turn, this creature has first
strike"). **Conclusion: no further parsing pass is worth building**; the only closed, combat-relevant
shape is the attacking / your-turn self-pump (~100 cards), a candidate if anyone wants it. B3 is
effectively COMPLETE: anthems in both sims, cost reducers parsed, the rest is long-tail.
**NOT done, deliberately:** (b) cost reducers and CDA P/T;
(c) the "other" 41% of statics.

**Plan, in order (each phase ships and measures on its own):**
1. *Parser, no sim change.* A deterministic parser beside `parse_attach_grant` (no LLM; reject the
   WHOLE note on any unrecognised token; zero false positives over the store, checked by a scan like
   the one that validated attach). Emits structured fields on the static ability: `affects`
   (`you` / `opponents` / `all`), `subject` (creature filter), `power`, `toughness`, `keywords`.
   Backfill the already-accepted CCMs without GPU, as `backfill_attach_grants.py` did.
2. *Sim layer, P/T anthems only.* tier0 board power and tier2 combat read the anthem while its
   source permanent is on the battlefield; it leaves with it (mirror `attached_to` / `attach_grant`).
   Add `static` ops to `sim-health` so the gauge reports them rather than flattering itself.
3. *Calibrate.* Run `gauntlet` and `bracket_accuracy` before/after (the recipe in the engine notes:
   copy `corpus/decks/*` into the worktree). Expect keyword-dense and go-wide decks to move; if
   bracket medians move by more than noise, stop and decide with the user before shipping.
4. *Then* cost reducers (touches castability and the mentor's `card_castability`) and CDA P/T.
**Accept (phase 1):** the parser covers >= 90% of anthem_pt notes with 0 wrong parses in a random
30-card hand check (the standing lesson: spot-checks of 6-20 cards are not proof).
**Not in scope:** the "other" 41%; layer system; conditional statics ("as long as ...").
**Owner:** C. N may do a gold-set-gated labelling pass on "other" later (see offload-tiered-labelling).

## B4. Compile-quality gate for blink and `gain_control`
**Done already:** the sim no longer executes a blink as removal (commit 7753451).
**Remaining:** the CCMs are still *wrong*, they just no longer do damage. `ccm-recheck` reports
0 failing because **no gate describes these defects**, so the nightly cannot see them.
- Blink: 161 cards carry the blink signature; 134 compile to `exile` + `return_to_hand`/`gain_control`
  (top shapes: `exile, return_to_hand` x25; `+draw` x10; `+add_counter` x10; `+gain_control` x7).
  Momentary Blink is stored as exile + return_to_hand + gain_control.
- `gain_control` is a catch-all for at least 7 effects (blink, bounce, "becomes a creature"/Crew,
  restrictions, Monarch, impulse draw, reversed polarity); the sim declines the op, so this is a
  data-quality and mentor-description issue, not a simulation one.
**Correction after measuring (2026-11-04):** `exile` + a return op is the *accepted* blink encoding
(`interpreter.is_flicker` reads it), so the 134 figure overstated the problem. The genuinely wrong
shapes are exactly two: **exile with no return op** (17 cards; executes as permanent removal of an
opponent's creature, e.g. Hallowed Respite) and **a blink carrying `gain_control`** (25 cards).
**Done:** (1) gate 3 now rejects both (commit 3744f5c, 9 tests); the return-op set is pinned in
lock-step with the interpreter; `ccm-recheck` lists 41 cards. (2) The mirror direction is the existing
"CCM declares exile, text never says exile" check plus this gate's no-return arm.
**Done (3)+(4), 2026-11-04:** `compile-names` on node 1: **26 accepted, 15 quarantined**
(Aminatou, Conciliator's Duelist, Cosmic Intervention, Emiel the Blessed, Flickerwisp, Glimmerpoint
Stag, Icewind Stalwart, Lae'zel's Acrobatics, Liberate, Mistmeadow Vanisher, Quantum Entanglement,
Settle Beyond Reality, The Dragon-Kami Reborn, The Fall of Lord Konda, Wiccan Rising Magician). A
quarantined card has no CCM, so it falls back to rung-1 heuristics: the honest under-count, and the
model could not satisfy the gate in 2 attempts (Wiccan looped 10x). Reading all 26 against oracle
text found **four the gate cannot catch** because the blink is structurally indistinguishable from
Oblivion Ring (return tagged `zone: exile`, return aimed at `self`, or exile/return split across two
abilities): Blizzard Strix, Hallowed Respite, Eldrazi Confluence, The Shattered States Era. Those four
are hand-authored (`ccm/authored/90-*.json`, rung 3, committed) in the plain exile+return shape, with
a test that no executable exile targets another permanent. Modal cards (Charming Prince, Djinn of the
Fountain, Ojutai Exemplars) keep only their non-blink modes: honest omission.
**The sibling `mythgauntlet` store has the 26 rewrites uncommitted** (ledger and compiled files; a
backup of the 41 originals + ledger is in the session scratchpad). I did not commit in that repo.
**Standing limitation:** a blink-vs-exile-until ambiguity cannot be fixed structurally; it needs an
explicit blink encoding in the schema. Not worth it for ~4 residual cards; recorded so it is known.

## B11. (found while reviewing B4) Self-target and off-battlefield exile ran as removal
**Done 2026-11-04 (commit 7ea6adf):** tier2's exile/destroy branch skipped only `controller: you`,
so 271 `exile(self)`, 25 `destroy(self)` and 83 off-battlefield exile effects (including impulse
draw: Mind's Desire, Jeska's Will, Improvisation Capstone) killed the opponent's best creature. Fixed
with 6 tests. **A/B over 1,153 decks (gauntlet seed 777):** mean shift 0.0 signed, 7.7 Elo absolute
(noise 2-5), bracket means B1-B4 within 2, B5 -13; 77 decks moved >20, the largest losers are Ral
spellslinger decks (-270), a correct deflation. **Follow-up:** the engine's rated gauntlet numbers
(`data/gauntlet_*.json`, any cached `--cache` results) predate this fix; the nightly will refresh
them, but nothing should quote pre-fix ratings for impulse-draw-heavy decks.
**Accept:** recheck lists the blink population as failing before the fix and 0 after; the 134 are
either recompiled correctly or marked unsupported; no card gains an executable op it lacked.
**Owner:** C (gate, review); N (recompile compute).

## B5. Bracket recall
**Evidence:** within-one 91.6% (bar 95%), exact 51%; recall B4 34%, B1 44%, B5 36%. The misses are
mostly rule-contradicting self-labels (a deck holding real Game Changers labelled B1/B2) and
ordinary decks the gate under/over-calls. HANDOFF/PLAN_CLOCK already closed B2/B3-by-clock.
**DIAGNOSIS DONE 2026-11-04** (`docs/bench/bracket_accuracy_2026-11-04.json`, 624 labelled decks,
real Spellbook combos, current strength model). **The headline figures in the line above are stale.**
Current: exact **59.5%** (bar 60), within-one **92.1%** (bar 95), bias +0.05; recall B1 48.8%,
B2 53.9%, B3 75.6%, **B4 34.2%, B5 85.5%** (not 36%). **Excluding the 62 labels impossible under the
rules** (a B1/B2 self-label holding a real Game Changer or combo): exact **66.0%**, within-one
**96.3%**, which clears both bars. The remaining weakness is B4 alone.
*B4 misses (48 of 73), bucketed by cause:*
- **28 predicted B3**, all with <=3 Game Changers (20 hold a combo). B4 by the official rule means
  "unlimited Game Changers", so a B4 deck that simply does not run them looks like a strong B3.
  Among the 73 B4-labelled decks, **25 hold 0 or 1 Game Changer** (34%).
- **15 predicted B5** (12 via the combo gate): optimised B4 decks that read as cEDH.
- **5 predicted B1/B2** (gc=0).
Strength score medians: B3 2.47, B4 2.87, B5 4.60. The B3/B4 gap (0.40) is small against the spread.
**Conclusion:** mostly a labelled-data limit, not an engine gap. The one signal that separates B4
from B3 is the Game Changer count, and a large share of self-labelled B4 decks do not use it.
**Decision: no tuning.** Any threshold move trades B4 recall against B3 (the largest, best-served
bracket) and the earlier sweeps already showed that trade is a wash. Re-open only with new evidence
(for example a larger B4-labelled sample or a feature that is not Game Changers).
**Original first step (kept for the command):** `python scripts/bracket_accuracy.py` (about 25 min, full CCM
store) and bucket the B4 misses by cause: label contradicts rules / low strength score / combo not
detected. Only then decide whether any fix is an engine gap or a labelling-data limit.
**Accept:** a written split of the B4 misses by cause with counts; any change must keep within-one
>= 91.6% and be shown on the labelled corpus, not argued. **Do not** re-tune thresholds blindly.
**Owner:** C.

## B6. Mentor gate under-flags a moderate band
"Vulnerable to wipes" at 50.6 (band moderate) is a documented design choice. Revisit only with a
doctrine argument, not a number. **Needs the user's call** on whether casual play wants a stricter
band; default is leave it. **Owner:** U.

## B7. Test gaps (now: "write tests for untested helpers" as a bug-finding method)
Method that paid off: pick the untested pure helpers, read them, write tests, and let a failing
assertion expose the defect. **Seven real bugs found this way on 2026-11-04, every one fixed with a
regression test:** (1) `card_renderer._classify_border_theme` matched substrings ("inferno" got a
vine border via "fern"); (2) `themer._extract_theme_palette` matched substrings ("a hundred years
war" -> red) and its de-dup could never fire ("gold"+"golden" repeated); (3) `themer._parse_batch`
took the first parseable list, so a thinking model's own "[1, 2]" before the answer discarded the whole
batch to plain names; (4) `image_gen._theme_darkness_score` matched substrings ("lightning storm" was
"whimsical" and had its dark LoRAs crushed to 20%); (5) `collection._from_decklist` (behind
`load_owned_names`, the ownership set every build reads) turned "1x Sol Ring" into the key
"1x sol ring"; (6) the same parser cut "Erase (Not the Urza's Legacy One)" to "Erase"; (7) the
audit-driven sim fixes in B11/B12. **Recurring class: bare substring matching on natural-language
text** (4 of the 6 non-sim bugs): worth a repo-wide grep for `word in text_lower` over short words.
**Route-level pass (same day), 2 more real bugs:** (8) **`POST /api/decks/delete-batch` validated
no ids** while the single delete does (its own comment says it `rmtree`s a path built from the id), so
`{"job_ids": ["../victim"]}` deleted a directory outside the renders folder; now every id must match
the 16-hex shape or it is skipped. (9) **`apply-swap` checked duplicates against the TYPED name, then
resolved the add by a fuzzy lookup**, so "arcane signt" resolved to a card already in the deck and
added a second copy to a singleton deck (and had already cut the other card); the resolved name is
now checked before anything is mutated. Collection routes (20 tests), build routes (17), import routes (15), engine-proxy routes (30) and
the themer LLM transport (17) found no bugs; the transport tests pin the documented sampler-forwarding
regression and were mutation-checked (dropping the forwarding fails 2 of them). Remaining route-level: `routes_strength` breakdown/mentor/card-impact routes, the rest of `routes_misc`.
Covered so far (2026-11-04, ~480 tests): logbuffer, gen_settings, exporter, deck_import parsing,
mana_pips, api/cards, buildable, playstyle, api/state, set_symbol, card_renderer, themer, image_gen,
card_video, collection parsing. Remaining by untested-function count: `api/routes_collection.py`,
`model3d.py` (all 14), `api/routes_decks.py` and `routes_strength.py` (route level, needs a
TestClient fixture), `collection_index.py`.
**Accept per module:** the pure helpers have tests that fail when the helper is broken, not just tests
that run (check at least one by mutation).

## B13. Cross-language drift (JS <-> Python) - found by running the real JS under Node
**Method:** the code base documents several places where the browser re-implements a server rule
("keep in step", "mirrors", "MUST match"). Nothing enforced it. `tests/test_*_js_python_parity.py` now
import the real JS module under Node and compare it with the Python side on the same inputs (skipped
when Node is absent). **Two real divergences found and fixed (2026-11-04):** (1) the server's mana-cost
normaliser stripped only spaces while the browser stripped all whitespace, so a pasted
`2<tab>W` previewed as `{2}{W}` but was stored raw (the colourless, pip-less card the normaliser
exists to prevent); (2) the deck view's card-type classifier tested the WHOLE type line (a modal DFC
"Sorcery // Land" was filed under Land, the back face) and had no Battle bucket, while the server uses
the front face and knows Battle; `StepDeck` also carried a second private copy, now removed in favour of
`deckGrouping.primaryType`. **Locked clean:** gen-settings keys and defaults (UI schema vs
`GenSettingsModel`/`GenSettings`), collection sort keys and group-bys, the single-card "needs the LLM"
rule (checked by reading, identical). Covered by parity tests: manaCost, genSettings, collectionView
sorts/groups, primaryType (4 files, 17 tests). **Open:** `StepDeck`'s remaining local logic and any
future "mirrors the server" comment should get a parity test when added.

## B8. Refresh the published CCM snapshot
Last published 2026-09-21 (31,906 compiled, 99.2% on v11, 21 MB). The store has moved since.
This is **outward-facing** (a GitHub release on the public repo). Spec: run
`scripts/package_ccm_release.py` in the mythgauntlet repo, then the `gh release upload ccm-data
--clobber` + `gh release edit` pair it prints. **Blocked on the user's go-ahead.**

**PUBLISHED 2026-11-04.** The first upload attempt was denied by the permission layer; after you
re-confirmed in chat the retry succeeded. One mistake caught and fixed: the first upload used the dated
filename, which created a second asset while the default download name still served the September file;
I re-uploaded under `mythgauntlet-ccm-store.zip`, deleted my duplicate, and checked that the public URL
now returns a file with the same SHA-256 as the local zip (3e4e75de...). The release holds exactly one
asset, titled "CCM data (beta) - 2026-11-04": 32,186 compiled, 99.8% on prompt v11, 133 quarantined, 21 MB.
`docs/ENGINE_DATA.md` figures updated. Caveats worth knowing: the manifest's `source_commit` is the sibling repo's HEAD (27c9e5321), but the
snapshot reflects its working tree, which holds uncommitted nightly state plus the 26 blink recompiles.
`README.md` and `docs/ENGINE_DATA.md` state the old figures (31,906 compiled / 260 quarantined /
2026-09-21); update them after publishing.

## B12. (found by `scripts/effect_audit.py`) Effects aimed at the caster's own side hit the opponent
**Done 2026-11-04.** The audit runs every stored effect through the real tier2 executor on a fixed
synthetic board and lists those that change the OPPONENT although their target says self / `you` /
a non-battlefield zone. Of 18,219 such effects, **298 changed the opponent**. Fixed (6 tests,
`test_effect_executor_targets.py`): (1) `deal_damage` to a player with `controller: you` (110: Ancient
Tomb, City of Brass, Mana Vault, the Talismans, Aftershock) and to the source itself (33) landed on
the opponent, i.e. **every pain mana source dealt its self-damage to the opponent each time it was
tapped**; now declined (the self-cost is unmodelled, an honest omission, because the same field also
spells Curse of Shaken Faith); (2) a MASS `return_to_hand` from a graveyard/exile bounced every board.
Audit now reads 99, all understood: 93 creature-type `controller: you` damage (the compiler's spelling
of the SOURCE in a bite/fight effect: deliberately left alone, it is right more often than wrong),
plus Thoughtseize-style hand discards and three lose_life effects where `target.self` is the X source.
**A/B (gauntlet seed 777, 1,153 decks):** signed shift 0.0, mean |shift| 12.0 Elo (noise 2-5), 194 decks
moved >20, bracket means B1-B4 within 4, **B5 -13** (cEDH lists were running the most pain mana). Top
losers hold City of Brass / Ancient Tomb / Mana Vault; the one big gainer held Custodi Squire.
**Mirror audit (`effect_audit.py --mirror`): opponent-aimed effects that improve the CASTER.**
906 effects say opponent; 168 improved the caster. Fixed the unambiguous ones: **`gain_life` with
`who: opponent`/`each_opponent` (63 effects, including Swords to Plowshares: "its controller gains
life") credited the CASTER**; now the opponent(s) gain it. The same two blind spots (self-damage
counted as reach; opponent life gain counted for the caster) existed in all three FLATTENED profile
summaries (resolution, activated, death), so those now agree with the executor (the project's
standing lesson: tags.py / profile.py / the executor are separate derivations). 6 more tests.
A/B vs the previous commit: mean |shift| 3.85 Elo (noise), 19 decks >20.
**B12c DONE:** `create_token` with `who: opponent`/`each_opponent` (7 effects: Pongify, Generous
Gift, Bloodroot Apothecary: "its controller creates a 3/3") gave the token to the CASTER because `who`
was not a declared create_token param and the interpreter dropped it. Added an optional `who` to the
op spec (backward compatible: stored CCMs already carry it, grammar already tolerated extras), the
executor now spawns it for the opponent(s), and the three flattened summaries skip it. 3 tests.
The other 133 mirror hits (bare `target: opponent player`, `who: target_player`) stay: ambiguous ("for
each opponent, create a token" means the caster creates it).
**Open (B12b, small):** `deal_damage` with `controller: you` and creature/any/planeswalker type is
ambiguous (bite vs self-damage, 93 effects); needs a compiler-side split, not an executor guess.

## B9. Role-strength granularity (S13) - DECIDED 2026-11-04: keep the strength unit
**The question:** `card_roles` gives each role a fixed strength per card (wipe/counterspell 3.0, tutor
2.0, removal 1.0, ramp/draw scaling), so `score_card`'s oversupply (`supply - target`) is in STRENGTH
units and roles are not comparable: one extra counterspell (3.0 over) outranks a role that is, in the
player's own terms, further over. The unit a player means, and the one the Mentor already reports
("removal 2 vs a target of 7"), is CARDS; `role_card_counts` and `card_targets_for` already exist.
**Experiment (`scripts/cut_unit_experiment.py`, 577 corpus decks, top-6 pool, nothing shipped):**
| | strength (shipped) | cards |
|---|---|---|
| cut pool differs | | on **48.5%** of decks |
| offered cuts from a role NOT over its card target | 18.8% | **14.2%** |
| offered cuts that fill the deck's own archetype role | 14.7% | **12.4%** |
Both proxies improve with the card unit, and it would make cut suggestions use the same unit as the
Mentor's role table. **Why it is not shipped:** (1) the gain is modest, ~4 points; (2) the sim's axis
delta cannot rank cut policies (see `advisor_bench`), so there is no outcome metric to confirm it;
(3) the unit is baked into `redundancy_backed`, the cut sentences (`card_impact._cut_sentence`), the
swap brief, `role_swap` and about 30 tests, so the change is wide; (4) integer card counts tie often,
which hands more decisions to the popularity tiebreak. **Recommendation:** ship it behind a `unit`
parameter, default `cards`, as one reviewed change, and keep the strength unit for the golden-master
tests. **Decision needed:** do you want cut suggestions in cards (matches the Mentor, ~4 pt fewer
false positives) or left as is? Default if no answer: left as is.

## B10. Offload harness follow-ups
`scripts/dispatch.py` works (`--spread`, `--verify`). Keep: 14b drafts with `--verify` only for
modules a deterministic checker covers; 8b for extraction/classification/sweeps. Open: a `--gold`
mode that scores a classification spec against a hand-labelled set before running it on the corpus
(the rule from offload-tiered-labelling). **DEFERRED 2026-11-04, no consumer:** it was needed for a B3
'other' labelling pass, and B3 closed without one ('other' is long-tail). Build it when a real
classification sweep needs it, not before.

---

## B14-B18. Deck building development plan
Full review, evidence and acceptance tests: [`DECKBUILD_REVIEW.md`](DECKBUILD_REVIEW.md). Start with B14 (measure only, no behaviour change); its table decides how much of B15-B17 is needed.

---

## Done
| Date | Item | Evidence |
|---|---|---|
| 2026-11-04 | Archetype role targets regenerated (18 cells; 4 -> 11 archetypes) | 2fb68bd; own-role cuts 1421 -> 1159 over 501 decks |
| 2026-11-04 | A blink is not removal in the sim | 7753451; 64 abilities fixed, 6 tests |
| 2026-11-04 | CLAUDE.md 275 KB -> 8 KB index + `docs/engineering/` (lossless) | `scripts/split_claude_md.py` asserts the rejoin |
| 2026-11-04 | Repo root cleared; corpus committed; HANDOFF points at STATUS | e6a1b05, 12c310c |
| 2026-11-04 | 230+ tests across 12 modules; renderer border-theme bug fixed | tests/test_*_pure.py etc. |
| 2026-11-04 | B1 mentor bench 84/81/84 -> 87/90 via 3 gate fixes (salty matcher, length trim, fallback history) | runs 1-4 in docs/bench/ |
| 2026-11-04 | B4 blink gate + recompile of 41 + 4 authored | 3744f5c, ccm/authored/90-* |
| 2026-11-04 | B11 self/off-battlefield exile no longer removal (771 effects) | 7ea6adf; 77 decks moved >20 Elo |
