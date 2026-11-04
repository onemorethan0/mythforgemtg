# Myth Forge backlog (opened 2026-11-04)

The single list of identified work. `STATUS.md` is the one-page summary; this file is the detail:
every item has evidence, an acceptance test, the first command to run, and an owner. Update the
**Status** column when something moves, and move finished items to the Done table at the bottom.

Owner key: **C** = Claude (rules-facing, surgical, or design), **N** = the local nodes (compute and
sweeps only; see STATUS.md section 3 for why they do not author code), **U** = needs the user's
decision or go-ahead (outward-facing, or a product call).

| ID | Item | Status | Owner |
|---|---|---|---|
| B1 | Mentor holistic bench vs the 87-90/90 bar | 84/90 first run; re-run queued | C reads, N computes |
| B2 | Builder bench vs `docs/bench/current.json` | CLOSED: metric effect, baseline refreshed | C |
| B3 | Static abilities: anthems, cost reducers, CDA P/T | specced, not started | C (N for labelling) |
| B4 | Compile-quality gate for blink / `gain_control` mislabels | gate landed; 41-card recompile running | C (N recompiles) |
| B5 | Bracket recall: B4 34%, B1 44%, B5 36% | specced, not started | C |
| B6 | Mentor gate under-flags a moderate band | design question | U |
| B7 | Test gaps in the art pipeline | in progress | C |
| B8 | Refresh the published CCM snapshot | blocked on user | U |
| B9 | Role-strength granularity (S13) + wipe colour requirement | specced, not started | C |
| B10 | Offload harness follow-ups | specced | C |

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
**Next:** re-run once (node 1 is busy recompiling B4), then compare cell by cell. If the same cells
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
**In progress:** (3) `compile-names` on node 1 for the 41 (backups in the session scratchpad).
**Remaining:** (4) review every recompiled card against its oracle text (the standing bar; a green
gate is not proof), hand-author any the model cannot get right in `ccm/authored/`. Do not bump
`PROMPT_VERSION`. Do not commit in the sibling `mythgauntlet` repo; its working tree already has
uncommitted nightly state.
**Accept:** recheck lists the blink population as failing before the fix and 0 after; the 134 are
either recompiled correctly or marked unsupported; no card gains an executable op it lacked.
**Owner:** C (gate, review); N (recompile compute).

## B5. Bracket recall
**Evidence:** within-one 91.6% (bar 95%), exact 51%; recall B4 34%, B1 44%, B5 36%. The misses are
mostly rule-contradicting self-labels (a deck holding real Game Changers labelled B1/B2) and
ordinary decks the gate under/over-calls. HANDOFF/PLAN_CLOCK already closed B2/B3-by-clock.
**First step (diagnosis, no change):** `python scripts/bracket_accuracy.py` (about 25 min, full CCM
store) and bucket the B4 misses by cause: label contradicts rules / low strength score / combo not
detected. Only then decide whether any fix is an engine gap or a labelling-data limit.
**Accept:** a written split of the B4 misses by cause with counts; any change must keep within-one
>= 91.6% and be shown on the labelled corpus, not argued. **Do not** re-tune thresholds blindly.
**Owner:** C.

## B6. Mentor gate under-flags a moderate band
"Vulnerable to wipes" at 50.6 (band moderate) is a documented design choice. Revisit only with a
doctrine argument, not a number. **Needs the user's call** on whether casual play wants a stricter
band; default is leave it. **Owner:** U.

## B7. Test gaps in the art pipeline
Done: logbuffer, gen_settings, exporter, deck_import (offline), mana_pips, api/cards, buildable,
playstyle, api/state, set_symbol (153 tests added 2026-11-04). Remaining: `card_renderer` (1.5k
lines, 1 test file references it), `cc_frames`, `themer` (3.5k), `image_gen` (3.8k).
**Method:** write directly against pure helpers; skip anything that needs ComfyUI/Scryfall/GPU.
**Accept per module:** the pure helpers have tests that fail when the helper is broken (mutate and
check once), not just tests that run.

## B8. Refresh the published CCM snapshot
Last published 2026-09-21 (31,906 compiled, 99.2% on v11, 21 MB). The store has moved since.
This is **outward-facing** (a GitHub release on the public repo). Spec: run
`scripts/package_ccm_release.py` in the mythgauntlet repo, then the `gh release upload ccm-data
--clobber` + `gh release edit` pair it prints. **Blocked on the user's go-ahead.**

## B9. Role-strength granularity (S13) and the wipe colour requirement
S13: `card_roles` gives counterspell and wipe a flat 3.0, so supply moves in whole-card steps and a
deck with two counterspells is 3.0 over (the Omo/landfall canary). Wipe's W/B/R colour requirement
now fails its own bar. **Method:** the documented three-gate measurement, not a guess; a sweep and
a doctrine argument (the sim's axis delta cannot see this class, so `advisor_bench` cannot settle it;
use `scripts/archetype_cut_diff.py`-style own-role cut counts). **Owner:** C.

## B10. Offload harness follow-ups
`scripts/dispatch.py` works (`--spread`, `--verify`). Keep: 14b drafts with `--verify` only for
modules a deterministic checker covers; 8b for extraction/classification/sweeps. Open: a `--gold`
mode that scores a classification spec against a hand-labelled set before running it on the corpus
(the rule from offload-tiered-labelling), needed before B3's "other" labelling pass.

---

## Done
| Date | Item | Evidence |
|---|---|---|
| 2026-11-04 | Archetype role targets regenerated (18 cells; 4 -> 11 archetypes) | 2fb68bd; own-role cuts 1421 -> 1159 over 501 decks |
| 2026-11-04 | A blink is not removal in the sim | 7753451; 64 abilities fixed, 6 tests |
| 2026-11-04 | CLAUDE.md 275 KB -> 8 KB index + `docs/engineering/` (lossless) | `scripts/split_claude_md.py` asserts the rejoin |
| 2026-11-04 | Repo root cleared; corpus committed; HANDOFF points at STATUS | e6a1b05, 12c310c |
| 2026-11-04 | 153 tests across 10 modules | tests/test_*_pure.py etc. |
