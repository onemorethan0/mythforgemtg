# Myth Forge — status and gameplan (2026-11-04)

One page. Read this first; `HANDOFF.md` and `CLAUDE.md` are the deep references and are long
(CLAUDE.md is 275 KB, local only, and not meant to be read top to bottom).

**Goal the work is judged against:** casual Bracket 1-3 gauging — "is this deck fun and on-level
for my pod" — not cEDH optimisation. A wrong card model is a defect, not an approximation.

## 1. Where we are

| Area | State | Evidence |
|---|---|---|
| Deck build / import / analyze | Stable. Last review 2026-10-23, 12 fixes shipped | `docs/REVIEW_2026-10-23_deckbuild_analyze.md` |
| Strength engine (`src/mythgauntlet`) | Mature. 22+ simulated op types, keywords, planeswalkers, toughness commanders | `sim-health` gauge |
| Bracket estimate | Within-one 91.6% (target 95%). Exact 51%. B4 recall 34%, B1 44%, B5 36% | `scripts/bracket_accuracy.py` |
| Deck Mentor | 87-90/90 holistic, 47-49/52 Shelob as of 2026-10-02. **Re-run after 10-23/25 changes: see section 4** | `scripts/mentor_holistic_bench.py` |
| App shell | `server.py` split into `api/` (10-24). Lint clean (10-25) | `git log` |
| Tests | ~3,000, all green. +107 added today (see section 3) | `python -m pytest tests -q` |
| Feature work | Last feature commit 2026-10-25. Nothing in flight | `git log` |

## 2. What is open, ranked by value to the casual goal

| # | Item | Why it matters | Size | Who |
|---|---|---|---|---|
| 1 | Static-ability gap: 7,268 stored statics are note-only (anthems, cost reducers, characteristic P/T) | Biggest remaining hole in how the sim sees cards; needs a schema, prompt, recompile and a continuous-effect layer | Large, multi-session | Claude (design); nodes for recompile labelling |
| 2 | `gain_control` is a catch-all op (7 distinct real effects behind one name); blink effects mislabelled across ~55 ops | Wrong card model, executed at full value | Medium | Claude (rules-facing) |
| 3 | Bracket B4/B1/B5 recall | Directly the headline output | Medium; mostly a labelling-data limit | Claude |
| 4 | **Measured today:** `ROLE_TARGETS` is current; `ARCHETYPE_ROLE_TARGETS` has **18 drifted cells** (6 moved, 12 newly clearing the gates, e.g. tribal_elves ramp 24, theft ramp 23). Also open: wipe colour requirement, per-card role strength is granular (S13) | Skews cut suggestions for those archetypes | Small: regenerate, then review the diff | Script runs locally; Claude reviews |
| 5 | Mentor open items: gate under-flags a moderate band; benches not re-run (section 4) | Trust in the mentor's answers | Small | Claude |
| 6 | Test gaps: `card_renderer` (1.5k lines), `cc_frames`, `themer` (3.5k), `image_gen` (3.8k), `set_symbol` | Regression safety on the art pipeline | Medium | See section 3 |
| 7 | Hygiene: 48 untracked corpus decks + modified manifest; 12 stray logs and `ro_*_test.py` scripts in the repo root; HANDOFF.md is dated 2026-08-14; CCM release last refreshed 2026-09-21 | Findability | Small | Claude |

## 3. What the offload experiment taught us (today)

Nine test files drafted on qwen3 across both nodes. **Every one needed a hand rewrite.**

| File | Model / node | Draft quality |
|---|---|---|
| logbuffer, mana_pips, gen_settings, exporter, deck_import, api/cards, buildable, playstyle | 8b and 14b, nodes 1+2 | Invented fields and return shapes; some did not parse; wrong expected values |
| api/state, set_symbol | 8b, node 2, **with** the new `--verify` repair loop | Still FAIL after 2 repair rounds; set_symbol imported a module that does not exist |

Conclusions, kept as rules:
1. **8b writes nothing you land.** Use it for extraction, classification and sweeps only.
2. **Tests drafted by a model are faster to write directly** when the module is under ~300 lines.
   The model saves effort only where the output is checked by something deterministic.
3. `--verify` is worth keeping for 14b, but a green pytest only proves the file runs, not that it
   tests anything. Still read every draft.
4. **Best use of the nodes is compute, not authorship:** benchmarks, calibration sweeps,
   recompiling/rechecking CCMs, labelling queues with a gold set. Node 1 is running the mentor
   benchmark now; node 2 is the parallel box for 8b sweeps.

## 4. Verification run in progress

`mentor_holistic_bench.py` (9 decks x 9 questions) on node 1. It was never re-run after the
2026-10-23/25 mentor changes. Prior bar: 87-90/90. Result is appended below when it finishes.

RESULT: _pending_

## 5. Gameplan — next three moves, in order

1. **Close the open verification** (this session): read the bench result, fix any regression it
   shows, then re-run `scripts/builder_bench.py` only when the network is quiet (it hits Scryfall).
2. **Regenerate the archetype targets** (item 4). The `--check` already ran: 18 cells drift. Next is
   `archetype_role_targets.py` to rewrite the table, then a before/after `advisor_bench` so the
   change is shown to help or hurt rather than assumed. This is CPU work, so the nodes are not the
   bottleneck; I own the judgement of the diff.
3. **Decide item 1 or 2 with you**: both are the real quality gains, both are Claude-owned and
   multi-session. Item 2 is smaller and fixes live wrong-card-model defects; item 1 is bigger and
   unlocks more. Recommendation: item 2 first.

Housekeeping rides along: commit or ignore the corpus decks, clear the root clutter, and replace
HANDOFF.md's header with a pointer to this file.

## 6. How to keep information digestible

- This file is the single entry point; update it at the end of any session that changes status.
- CLAUDE.md should be split by heading into topic files under `docs/engineering/` with a short
  index (a script can do this deterministically; no model needed). Not done yet — it is your local
  file, so it needs your go-ahead.
