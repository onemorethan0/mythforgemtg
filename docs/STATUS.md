# Myth Forge — status and gameplan (updated 2026-11-04, end of day)

One page. **Detail for every open item is in [`BACKLOG.md`](BACKLOG.md)** (evidence, acceptance test,
first command, owner). `HANDOFF.md` is the August record; `CLAUDE.md` is now an 8 KB index into
`docs/engineering/` (local only; the repo is public).

**Goal the work is judged against:** casual Bracket 1-3 gauging — "is this deck fun and on-level
for my pod" — not cEDH optimisation. A wrong card model is a defect, not an approximation.

## 1. Where we are

| Area | State | Evidence |
|---|---|---|
| Deck build / import / analyze | Stable. Builder bench 20/20 valid, every verdict unchanged vs August | B2, closed |
| Strength engine | Mature. Blink no longer simulated as removal (64 abilities fixed) | commit 7753451 |
| Compiler gates | New gate rejects a blink compiled as bare exile or with `gain_control` (41 cards flagged) | commit 3744f5c |
| Calibration | `ARCHETYPE_ROLE_TARGETS` regenerated: 4 -> 11 archetypes; own-role cut suggestions down 18% | commit 2fb68bd |
| Deck Mentor | **87/90 (97%)** on the holistic bench, zero fallbacks; three gate bugs found and fixed on the way (84 -> 81 -> 84 -> 87) | B1, closed |
| Bracket estimate | within-one 92.1% raw, **96.3% excluding 62 labels impossible under the rules** (exact 66.0%): bars met. B5 recall 85%. Only B4 is weak (34%), a labelled-data limit | B5, diagnosed |
| Static abilities | **Anthems live in both sims** (tier2 duels + tier0 goldfish), derived from card text, no schema change. 107 cards, 25% of corpus decks. Cost reducers, CDA power/toughness and the heterogeneous 'other' 41% are open | B3 |
| Tests | ~3,100, all green. 250+ added today across 14 modules | `pytest tests -q` |
| Docs / repo | CLAUDE.md 275 KB -> 8 KB; root cleared; corpus committed; this file + BACKLOG.md | |

## 2. What changed today, in one list

1. Multi-node dispatcher (`scripts/dispatch.py`, `--spread`, `--verify`) and the finding that the
   nodes should do **compute**, not author code (section 4).
2. Archetype role targets regenerated and measured (`scripts/archetype_cut_diff.py`).
3. **A real simulation defect fixed:** flicker/blink abilities executed as permanent exile of the
   opponent's best creature. New tests; `scripts/blink_scan.py` sizes it.
4. **A real compiler-quality gate** for the remaining wrong blink shapes; recompile of 41 cards.
5. **A real renderer bug fixed:** an "inferno" art theme got a *vine* border (substring match on
   "fern"). Found by writing a test, not by looking.
6. Static-ability gap re-sized honestly (the clean core is ~1,300 cards, not 7,000) and the first
   safe piece built.
7. Benchmarks re-run that had not been re-run since 10-23 (mentor, builder).

## 3. Open work, ranked (see BACKLOG.md for each)

| ID | Item | Status | Owner |
|---|---|---|---|
| B1 | Mentor bench | **closed: 87/90** | C |
| B3 | Static abilities: cost reducers, CDA P/T, the 'other' 41% | anthems done (tier2 + tier0) | C |
| B4 | Blink recompile review | **closed** (26 accepted, 15 quarantined, 4 authored) | C |
| B5 | Bracket recall | **done: diagnosed, no tuning (see BACKLOG)** | C |
| B7 | Test gaps: `cc_frames`, `themer`, `image_gen` pure helpers | in progress | C |
| B9 | Role-strength granularity (S13) | specced; needs a doctrine argument | C |
| B6 | Mentor gate moderate band | left as is (your approval of my recommendation) | - |
| B8 | Public CCM snapshot | **done: published 2026-11-04**, download hash verified | C |

## 4. What the offload experiment taught us

12 test files were drafted on qwen3 across both nodes; **every one needed a hand rewrite**, and the
two 8b drafts that went through the new `--verify` repair loop still failed it.

1. **8b writes nothing you land.** Extraction, classification and sweeps only.
2. Writing tests directly is faster than reviewing a bad draft when the module is small.
3. **Use the nodes for compute.** Today that was a 30-minute mentor benchmark and a 41-card CCM
   recompile on node 1, which is what actually saved effort.
4. A green pytest proves the file runs, not that it tests anything. Read every draft.

## 5. Decisions

All three open decisions are settled: B3 phase 2 went ahead without a schema change, B6 stays as is,
and the CCM snapshot is published. Nothing currently waits on you. The next real quality gains are
in BACKLOG.md: B3's remaining statics (cost reducers touch castability, so they need a measured
change), B9 (role-strength granularity, which needs a doctrine argument first), and the sibling
`mythgauntlet` repo's uncommitted store (26 blink rewrites plus nightly state) which only you can commit.

## 6. Keeping this digestible

This file is the entry point; BACKLOG.md holds the detail. Update both at the end of any session
that changes status, and move finished items to BACKLOG.md's Done table.
