# MythGauntlet — Architecture

The system is a stack of seven layers. Each layer only depends on layers below it, and each is
independently testable. The two load-bearing design ideas are **tiered simulation fidelity**
and **graceful degradation of card knowledge** — together they let the product work end-to-end
from week one while its precision grows monotonically.

```
┌─────────────────────────────────────────────────────────────────┐
│ L6  APP           deck/collection mgmt, Power Profile reports,  │
│                   upgrade advisor, (later) FastAPI + web UI     │
├─────────────────────────────────────────────────────────────────┤
│ L5  LEARNING      gauntlet ratings (Bradley-Terry), card/combo  │
│     & RATINGS     value model, bracket calibration              │
├─────────────────────────────────────────────────────────────────┤
│ L4  SIM           Monte Carlo orchestration: seeded batches,    │
│     ORCHESTRATOR  parallel runners, result store (SQLite)       │
├─────────────────────────────────────────────────────────────────┤
│ L3  AGENTS        greedy heuristic → MCTS (determinized) →      │
│                   learned policy                                │
├─────────────────────────────────────────────────────────────────┤
│ L2  GAME ENGINE   zones, turn structure, combat, priority-lite; │
│                   fidelity tiers T0/T1/T2; deterministic RNG    │
├─────────────────────────────────────────────────────────────────┤
│ L1  CARD          Card Capability Model (CCM): authored →       │
│     SEMANTICS     LLM-compiled → effect-vector fallback         │
├─────────────────────────────────────────────────────────────────┤
│ L0  DATA          Scryfall bulk, EDHREC popularity/synergy,     │
│                   Game Changers list, decklist import           │
└─────────────────────────────────────────────────────────────────┘
```

## Package map

```
src/mythgauntlet/
  config.py            paths, constants (data dir, cache locations)
  data/
    scryfall.py        bulk download → slim local card store        [L0]
    edhrec.py          popularity/synergy ingest (json.edhrec.com)  [L0, planned]
  model/
    card.py            Card record, ManaCost parser                 [L0]
    deck.py            Deck, decklist parsing (text/Moxfield)       [L0]
  semantics/
    tags.py            Oracle-text heuristics → functional tags     [L1, tier-0]
    model.py           EffectVector + CCM data structures           [L1]
    compiler.py        LLM-assisted Oracle→CCM compilation          [L1, planned]
  sim/
    rng.py             deterministic seeded RNG (the ONLY RNG)      [L2]
    tier0.py           goldfish consistency simulator               [L2]
    tier1.py           scripted-pressure simulator                  [L2, planned]
    tier2.py           adversarial engine + stack                   [L2, planned]
    forge_adapter.py   optional Forge headless cross-check          [L2, planned]
  agents/              decision policies for T2                     [L3, planned]
  ratings/
    metrics.py         per-axis metrics from sim results            [L5]
    gauntlet.py        Bradley-Terry ratings vs reference decks     [L5, planned]
    calibration.py     bracket anchoring                            [L5, planned]
  cli.py               argparse CLI: fetch-data / analyze / info
```

## The two core design ideas

### 1. Tiered simulation fidelity

Full comprehensive-rules simulation of MTG is a multi-year effort (Forge has had contributors
for 15+ years; the rules are literally Turing-complete). Waiting for it would kill the
project. Instead, **every strength axis is computed at the cheapest tier that can measure it**,
and tiers are added without discarding lower ones:

| Tier | What it simulates | What it measures | Cost/game | Status |
|---|---|---|---|---|
| **T0 goldfish** | One player, no opponent: mulligans, land drops, mana, casting, ramp/draw engines | Consistency, Speed (proxy), curve efficiency, dead cards | ~0.1 ms | **built (MVP)** |
| **T1 pressure** | T0 + a scripted "meta clock": incoming damage curve, N board wipes, M counterspells at statistically-realistic turns | Resilience, Speed (under fire), Interaction value | ~1 ms | planned |
| **T2 adversarial** | Two+ decks, full zones/combat/stack over the CCM, MCTS agents | Meta strength (win rates → ratings), Ceiling | ~10–1000 ms | planned |
| **T-X Forge oracle** | Forge headless AI-vs-AI (JVM subprocess) for decks whose cards Forge scripts | Cross-validation of T2; ground truth for engine bugs | ~seconds | planned, optional |

Reports always state which tier produced each number. Lower tiers stay useful forever: T0 runs
in CI on every engine change as a regression suite.

### 2. Graceful degradation of card knowledge (the semantics ladder)

The engine never hardcodes card names. All card behavior comes from Layer 1, which answers
"what does this card do?" at the best available rung:

```
rung 3  SCRIPTED CCM      hand-authored, exact behavior          (~top 500 staples)
rung 2  COMPILED CCM      LLM-compiled from Oracle text,          (grows toward all
                          machine-validated                        of Commander)
rung 1  EFFECT VECTOR     statistical approximation: tags +
                          magnitudes from Oracle-text heuristics  (every card, today)
rung 0  VANILLA           mana cost + types + P/T only            (guaranteed floor)
```

A deck's report includes a **semantics coverage score** ("94% of this deck simulated at rung
≥2") so uncertainty is explicit rather than hidden. See `CARD_SEMANTICS.md` for the CCM spec
and compilation pipeline.

## Data flow (steady state)

```
Scryfall bulk ──┐
EDHREC API ─────┼──► local card store ──► semantics ladder ──► engine tiers
Game Changers ──┘         │                                        │
                          │                 ┌──────────────────────┘
Decklist import ──► Deck objects ──► SIM ORCHESTRATOR ──► results DB (SQLite)
                                                              │
                     ┌────────────────────────────────────────┤
                     ▼                                        ▼
              ratings/metrics                          learning loop
              (Power Profile,                    (card/combo value model,
               bracket estimate)                  gauntlet ratings, agent
                     │                            improvement)
                     ▼
               APP: reports, upgrade advisor, deck/collection UI
```

## Cross-cutting invariants

These are enforced conventions, not aspirations — CI and code review guard them:

1. **Determinism.** All randomness flows through `sim.rng.SeededRng`. Same seed + same deck +
   same engine version ⇒ bit-identical results. This is what makes results reproducible,
   debuggable, and cacheable.
2. **No card names in the engine.** Layers 2–3 consume only Layer-1 semantics. If the engine
   needs to know something about a card, that knowledge belongs in the CCM or an effect vector.
3. **Honest uncertainty.** Every reported number carries its tier and semantics coverage.
   A rung-1 approximation is never presented with rung-3 confidence.
4. **Popularity is a prior, never a verdict.** EDHREC data seeds the card-value model and
   builds the reference gauntlet; it must never directly move a deck's measured strength
   (that would recreate the static-calculator failure mode we exist to fix).
5. **Local-first.** Bulk data is cached locally; simulation runs offline; the LLM used for
   semantics compilation is the local llama-swap gateway (`:8010`). No network required after
   `fetch-data`.

## Technology choices

- **Python 3.12+** (developed on 3.14), `src/` layout, stdlib `argparse` CLI + `rich` output —
  same conventions as MythScanner.
- **Engine core in pure Python first.** Correctness before speed; the T0/T1 tiers are already
  fast enough (10⁴ games/sec). When T2 profiling demands it, hot loops move to
  Rust (PyO3) or numpy vectorization — behind the same interfaces.
- **SQLite** for the results store and card store index (proven at 113k cards in MythScanner).
- **Parallelism** via `multiprocessing` pools over independent seeded batches (embarrassingly
  parallel by construction, thanks to invariant #1).
- **Local LLM** (qwen3:14b via llama-swap) for semantics compilation with validation gates —
  never in the simulation hot path.

## Integration points with sibling projects

- **MythScanner** → `--export` CSV/Moxfield files import directly as a MythGauntlet collection.
- **MythForge** → generated decklists can be piped to `mythgauntlet analyze`; long-term, the
  evaluate step closes MythForge's generate→evaluate→improve loop.
- Both share the Scryfall bulk-data approach; the slim-record schema here is deliberately
  compatible in spirit with MythScanner's `slim_card`.
