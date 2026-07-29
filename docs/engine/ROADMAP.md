# Roadmap

Phases ship user-visible value on their own; no phase depends on a later one. Acceptance
criteria are testable. Sequence within a phase is suggestive, not contractual.

## Phase 0 — Skeleton & framework ✅ (2026-07-05)
Repo, docs (vision/architecture/semantics/simulation/learning/data/research), package layout,
CI, CLAUDE.md, Tier-0 MVP, tests.

## Phase 1 — Tier-0 consistency engine, hardened
The goldfish simulator becomes trustworthy and fast.
- [x] Color-aware castability upgraded (exact pip assignment via augmenting-path matching;
      hybrid pips honored, phyrexian still color-only — documented)
- [x] Mulligan policy configurable + sensitivity-tested
- [ ] Ramp modeling: land-fetch vs rocks distinguished ✓; dorks-as-rocks and cost-reduction
      (medallions, Henge) still pending
- [x] Draw modeling: one-shots vs repeatable engines (triggered-draw → engine_draw/turn)
- [x] `analyze` report v1: Consistency + Speed axes (goldfish combat clock), rich terminal
      output, JSON export
- [ ] Benchmarks: ≥5k games/sec/core (measured 2026-07-05: ~2.2k/s — matching loop is the
      hot path, optimize when it matters); determinism test in CI ✓
- **Accept:** 10 well-known decks (precon → cEDH) produce sane, explainable, stable numbers;
  a precon and a cEDH deck are unambiguously separated by the report.

## Phase 2 — Data & popularity foundation
- [x] EDHREC client (`data/edhrec.py`): per-commander inclusion/synergy, cached, defensive
      parsing (verified live against json.edhrec.com)
- [x] Game Changers: sourced from Scryfall's `game_changer` flag in bulk data (better than a
      hand-maintained file — verified 53 cards, matches WotC's Feb 2026 list) + surfaced in
      the analyze report with bracket gate hints
- [x] Deck polling (`fetch-decks`): EDHREC average decks + Archidekt top decks (with
      user-declared bracket labels) → `corpus/decks/` + manifest; sanity gate filters
      non-decks. **62-deck corpus seeded 2026-07-05, 62/62 fully resolve** (7 bracket-labeled)
- [x] Combo database (Commander Spellbook find-my-combos): combos in deck + one-card-away
      near-misses; `combos` CLI verb + `analyze --combos`; feeds Ceiling axis & bracket gates
- [ ] cEDH anchor lists (Bracket-5) — cEDH DDB links to Moxfield (API needs approved UA);
      add via manual exports or UA approval
- [ ] Explicit precon anchor labels (several fetched Archidekt decks ARE precons; tag them
      in the manifest as bracket-2 anchors)
- [x] Collection import (MythScanner CSV / Moxfield / plain text) + `analyze --collection`
      ownership report
- **Accept:** `fetch-data` builds a complete offline snapshot; corpus decks all parse. ✓
  (62/62 resolve against the card store)

## Phase 3 — Card semantics compiler MVP
The novel subsystem, proven end-to-end on a bounded pool.
- [x] CCM schema v1 (`semantics/ccm.py`, JSON + hand-rolled validation): 26 effect
      primitives, 5 ability kinds, 12 trigger events; 3 gates (schema / Scryfall lint /
      bidirectional rung-1 cross-check that catches both omissions and hallucinations)
- [x] 12 hand-authored exemplar CCMs (rung 3) in `ccm/authored/` — Sol Ring, Cultivate,
      Counterspell, Swords, Divination, Beast Whisperer, Wrath, Rhystic Study, Bolt,
      Sakura-Tribe Elder, Demonic Tutor, Command Tower (grow toward 20+)
- [x] Compiler pipeline vs llama-swap `:8010` (`semantics/compiler.py`): few-shot prompt
      (PROMPT_VERSION), qwen3:14b temp 0, retry-with-gate-feedback, quarantine, committed
      ledger + `ccm/compiled/` store. CLI: compile-card / compile-top / ccm-status
- [ ] Compile the top-500 EDHREC cards; publish coverage stats (first batches running;
      top-40 validation batch 2026-07-05)
- [ ] Per-deck semantics coverage score in `analyze` reports (rung per card from ledger)
- **Accept:** ≥60% of top-500 pass gates automatically; 0 accepted CCMs with wrong behavior in
  a 50-card manual audit; per-deck coverage score appears in reports.

## Phase 4 — Tier-1 pressure & Resilience axis
- [x] Board-wipe disruption in T0 (2026-07-07): `_Source.from_creature` tagging; an
      opt-in board wipe at turn W resets the creature clock + kills mana dorks (rocks/
      lands/noncreature engines survive — documented under-count); no behavior change
      when absent
- [x] Paired-seed Resilience score (`sim/tier1.py:compute_resilience`): clean vs wiped
      runs at identical seeds → retained board+mana output; surfaced in `analyze`
      (`--no-resilience` to skip). Verified: noncreature ramp ~100, creature/dork decks
      score lower; Selvala ramp = 72/100 (rebuilds mana, loses payoffs)
- [ ] More disruption classes: targeted removal (kill best permanent), counter budget
- [x] Interaction axis (`ratings/axes.compute_interaction`): answer density x breadth of
      coverage {spot removal, counters, wipes} from semantics. Castability weighting is a
      documented TODO.
- [x] Ceiling axis (`ratings/axes.compute_ceiling`): nut-draw = top-percentile of the T0
      goldfish distribution (fastest kills) + game-ending combo boost. Honest to T0
      fidelity — reads low when a finisher (overrun/ETB payoff) isn't compiled yet.
- **Accept:** glass-cannon vs resilient deck pairs separate correctly ✓ (tested);
  paired-seed variance cancellation ✓ (matched seeds by construction).

## Power Profile status (docs/VISION.md's six axes)
- [x] Consistency (T0) · [x] Speed (T0 goldfish clock) · [x] Resilience (T1) ·
      [x] Interaction (semantics) · [x] Ceiling (T0 distribution + combos) ·
      [x] Meta strength (T2 gauntlet, Bradley-Terry). **All six axes now measured.**
- `analyze` prints the 5 single-deck axes in one report; `gauntlet` produces Meta strength.
  The API's `/analyze` power_profile carries consistency/speed/resilience/interaction/
  ceiling/coverage for the Forge panel.

## Phase 5 — Gauntlet ratings & bracket calibration v1
Even before T2, T0+T1 axis vectors can drive a useful calibrated bracket model.
- [x] Hard bracket gates (`ratings/bracket.py`, 2026-07-09): official WotC gates — Game
      Changers count (0→1-2, ≤3→3, >3→4-5), 2-card combos (→min 3), mass land denial (→4-5),
      chained extra turns (→4-5); measured axes place within the band; meta rating / fast
      combo distinguishes 4 vs 5. Rule-based (mirrors how the official system works).
- [x] Report v2: `analyze` leads with "Bracket estimate: N. Label (confidence X%)" + the
      reasons that drove it; API /analyze power_profile carries bracket_estimate/label/
      confidence. Confidence scales down with thin semantics coverage + unchecked combos.
- [ ] Learned ordinal regression over a LARGE labeled corpus (still too few labels to fit
      without overfitting — the rule-based estimate is the honest interim).
- **Accept:** leave-one-out on corpus once enough labels exist: ≥60% bracket-exact,
  ≥95% within-one.

## Phase 6 — Tier-2 adversarial engine, 1v1
- [x] MVP engine (`sim/tier2.py`, 2026-07-05): zones, combat with trades/chump-blocks,
      commander zone + tax, decking, turn-cap adjudication; card behavior via
      **PlayProfiles** (`semantics/profile.py`: CCM rung 2/3 flattened to executable
      effects, EffectVector rung-1 fallback); GreedyAgent value function; `duel` CLI verb.
      Verified live: 300 games between two corpus decks in seconds, sane directional
      results. Semantics coverage shown per deck (invariant #3).
- [x] Activated abilities executed (2026-07-07): repeatable pay-mana/tap outlets
      (generic-only payment; tap once/turn; summoning sickness + tapped-can't-attack/block
      respected) and self-death triggers (aristocrat drains, death draws/tokens)
- [x] Combo win conditions (2026-07-07): Spellbook game-ending combos become T2 win
      conditions — a player wins when all pieces of a lethal combo are on its battlefield
      and past summoning sickness (`spellbook.winning_combos` + engine check + agent
      nudge; `--no-combos` to disable). Measured: B4 mean 1466->1499, B3/B4 gap 61->25 pts
      (18/62 decks have a detected combo). Remaining gap: instant/sorcery-piece combos
      don't persist as permanents (under-count), and n=2 labeled B4 is statistically thin.
- [~] Full CCM interpreter (attack/cast triggers, conditions, real X) replacing the
      PlayProfile flattening. **Core built + wired into T2, 2026-07-13** (`semantics/
      interpreter.py`): `interpret_ability` walks a CCM ability into resolved effects against
      a pluggable `Resolver`; `sim/tier2.py` now executes CCM cards' on-resolution effects
      (spell_effect + ETB) through it, per-effect instead of aggregated (all tokens spawn,
      every removal resolves — verified: two create_token effects now both fire). Rung-1 cards
      keep the flattened path; structural facts stay on the PlayProfile. `DefaultResolver`
      (X->1) keeps the numbers aligned; a live duel shifted only modestly (35%->38%), 240
      tests green. **Board-aware resolver added** (`_EngineResolver`): "for each creature you
      control" (`each`) scales to the caster's board (capped). **Finding:** real X is NOT
      broadly recoverable — the CCM store shows `X` is overwhelmingly a COST/CHOSEN amount
      (686 count + 582 amount uses), not a board count, so resolving it from live state would
      *reduce* fidelity; it stays at the default. The real fix is a schema that carries X's
      basis, not an engine guess. **Event-trigger execution added, 2026-07-15**: CCM
      permanents' cast_spell/cast_creature/opponent_casts_spell/attack/combat_damage_to_player/
      landfall/upkeep/draw_step/end_step triggers now fire AT their event via the interpreter
      (`_fire_triggers`/`_fire_perm_triggers` in `sim/tier2.py`; conventions + under-counts in
      docs/SIMULATION.md "Event-trigger execution"). CCM permanents' `engine_draw` is zeroed in
      the engine (draw triggers fire for real — no double-count); rung-1 keeps the flat
      approximation. 258 tests green. *Open:* retire the PlayProfile's on-resolution fields;
      X-basis in the CCM schema; per-attacker fan-out for global attack triggers.
- [x] Stack + instant timing MVP (2026-07-13, `sim/tier2.py` + `semantics/profile.py`):
      counterspells (LIFO counter-war chain) + held-up instant removal (pre-combat window)
      now function; PlayProfile exposes `counter`/`is_instant`. Reactions fire
      opportunistically (surplus mana). **Deliberate mana-holding was investigated and NOT
      shipped** (2026-07-13): three heuristics (fixed reserve / value threshold / value
      comparison) all durdled the greedy agent and made reactive decks a net negative
      (measured), because choosing to pass with mana up is a planning decision — it belongs
      to the ISMCTS/learned agent (Phase 7), not the greedy value function. Don't re-attempt
      it as a greedy heuristic.
- [~] Job orchestrator + results DB + job-hash caching. **Parallel pool + job-hash cache built**
      (2026-07-17, `ratings/orchestrator.py`; `gauntlet --jobs/--cache`): matchups run across
      processes (parallel == serial bit-for-bit, verified on real decks), cache keyed by
      semantics version for resume-for-free — the lever that makes an ISMCTS gauntlet affordable
      (~4x on uneven mcts jobs, ~core-count on a full run). *Open:* a real SQLite results DB with
      per-turn aggregates (today a flat JSON win/loss cache); variance-aware game budgeting.
- [ ] Forge adapter: same-matchup differential harness
- **Accept:** 1v1 gauntlet win-rate matrix is stable (re-run correlation ≥0.95) and
  rank-correlates with Forge on ≥20 shared matchups (ρ ≥ 0.7).

## Phase 7 — MCTS, multiplayer, ratings v2
- [x] ISMCTS agent (determinization); strength ladder vs GreedyAgent measured (2026-07-17).
      The Tier-2 turn loop is now an **action-based state machine** an Agent drives
      (`sim/game.py`: clonable GameState, decision points MAIN/ACTIVATION/COMBAT_ATTACK/
      COMBAT_BLOCK, legal_actions/apply/clone/determinize). GreedyAgent (`agents/greedy.py`,
      behavior-preserving — a golden-master test pins it bit-for-bit) is the baseline + rollout
      policy; ISMCTSAgent (`agents/ismcts.py`) is single-observer ISMCTS with determinization.
      It makes the planning move greedy can't — deliberately holding mana up for a counter
      (proven by a test where greedy taps out and ISMCTS passes to hold the counter). `ladder` /
      `ratings.ladder` measures the ladder; `gauntlet --agent` and `duel --agent-a/--agent-b` tag
      ratings *at* an agent level. *Open:* reactions (counter-war, instant window) are still
      auto-resolved greedy, not independent search decisions (their value IS found by rolling out
      the hold-mana line); combat candidate sets are bounded; search is single-process pure-Python
      (slow at mcts:1000 — perf/orchestration is the next lever).
- [ ] 4-player mode + threat model; Bradley-Terry ratings (+ uncertainty) on gauntlet
- [ ] Meta-strength axis goes live as the headline number (needs cEDH-line fidelity per the
      STATUS measurement note + the perf to run the corpus gauntlet under mcts)
- **Accept:** agent ladder monotone (MCTS-1k > MCTS-100 > Greedy, ≥55% pairwise) — **✓ verified**
  on a decision-rich control mirror (16 games/pair, seed 11): mcts:100 and mcts:1000 each beat
  greedy **94%**, and mcts:1000 beats mcts:100 **81%** (all >55%). Ratings re-base machinery works
  across an agent upgrade (gauntlet/duel run under a chosen agent, output tagged). ISMCTS rung
  done; 4-player + headline meta-strength remain.

## Phase 8 — Learning loop
- [ ] Games DB → card-value model (3a), EDHREC-priored synergy terms (3c)
- [x] Ablation engine (3b) → upgrade advisor (collection-aware) — **MVP 2026-07-13,
      v2 per-swap cut 2026-07-21** (`ratings/advisor.py` + `advise` CLI): ranks owned-card
      swaps by their MEASURED improvement to a Power Profile axis (re-run `analyze_deck` per
      swap; deterministic so the delta is signal, not noise). **v2:** the cut is now chosen
      PER candidate — each add is tested against the `cut_pool` weakest nonland cards
      (`--cut-pool`, default 3; `cut_pool=1` == the MVP single-global-cut) and keeps whichever
      cut improves the axis most, so an add that wants to displace a weak ramp piece no longer
      has to fight the one globally-weakest card. `--axis` or auto (weakest). Owned-restricted
      (Myth Suite C4 advisor-owned mode); `/advise` API exposes `cut_pool`/`analyses`/per-swap
      `cut`. *Open:* multi-card packages, general (non-owned) pools, faster batched evaluation.
- [ ] Disagreement-driven CCM priority queue (close the flywheel)
- **Accept:** advisor beats popularity-only swaps on measured rating gain across ≥10 decks;
  synergy graph reproduces ≥5 known iconic pairs without being told.

## Phase 9 — Application layer
- [ ] FastAPI backend + web UI (MythForge stack), deck/collection CRUD, report views
- [ ] MythForge integration (evaluate generated decks); MythScanner collection sync
- **Accept:** non-CLI user completes import → analyze → understand → improve unaided.

## Standing risks & mitigations
- **CCM compiler accuracy plateau** → gates + quarantine keep wrongness out; hand-author the
  head of the distribution; effect vectors floor the tail.
- **T2 scope creep** → priority-lite documented deviations; Forge differential as reality
  check; turn caps everywhere.
- **Calibration data scarcity** → precons/cEDH anchors are free; grow labels opportunistically.
- **Perf in Python** → determinism + job purity make Rust/numpy drop-ins safe when profiling
  says so, not before.
