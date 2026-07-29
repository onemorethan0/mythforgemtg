# MythGauntlet — Vision

## The problem

Every Commander player has lived this conversation: *"What power level is your deck?" — "Uh… a 7?"*

Deck strength in Magic: The Gathering is assessed today by **vibes and static heuristics**. The
existing tools (EDH Power Level, Draftsim's bracket calculator, ScrollVault, Commander Power
Meter, and a dozen others) all work the same way: scan the decklist for known-powerful cards,
count Game Changers and combos from a database, look at the mana curve, and emit a number.
None of them ever *plays the deck*. The community's criticism of these tools is consistent and
justified:

- They misclassify cards because they match on text patterns without understanding function.
- They can't see synergy — a deck of 100 individually-mediocre cards that assemble an engine
  scores low; a pile of unconnected staples scores high.
- They can't measure consistency, speed, or resilience, because those are *emergent properties
  of playing games*, not properties of a list.
- Their scores don't correspond to anything measurable, so they can't be validated or improved.

Meanwhile, WotC's official **Commander Brackets** system (5 brackets, Game Changers list) gives
players shared vocabulary but explicitly relies on self-assessment — it names the problem
without solving it.

## The thesis

**Deck strength is an empirical quantity. You measure it by playing games.**

MythGauntlet is a deck & collection manager whose core innovation is a **simulation-grounded,
self-improving strength engine**:

1. **Play the deck, thousands of times.** A rules-aware game engine simulates games at
   escalating fidelity — from goldfish consistency runs to full adversarial matches against a
   gauntlet of reference decks — producing distributions, not guesses: win rate, average win
   turn, mulligan rate, resilience under disruption.

2. **Understand the cards.** A *card semantics compiler* turns Oracle text into
   machine-executable capability models, built card-by-card: hand-authored for staples,
   LLM-compiled with automated validation for the long tail, and statistically approximated
   ("effect vectors") for everything not yet compiled — so **every deck is simulatable on day
   one, and precision only goes up over time**.

3. **Learn from the results.** Simulated match outcomes feed a ratings system (Bradley-Terry
   over a reference gauntlet) and a card-value model that learns which cards and *combinations*
   actually cause wins — seeded with real-world popularity priors (EDHREC inclusion & synergy
   data) and refined by simulation evidence. The engine's judgment of card combinations
   improves the more games it plays.

4. **Calibrate against reality.** Precons anchor Bracket 2. cEDH staples anchor Bracket 5.
   Real tournament and EDHREC meta data pin the scale so a MythGauntlet rating *means*
   something outside the simulator.

## What the user sees

- **Deck & collection management** — the table-stakes features done well: import from
  Moxfield/MythScanner/plain text, collection-aware deck building ("what can I build with what
  I own?"), price and legality tracking.
- **The Power Profile** — not one number, but six measured axes:

  | Axis | Question it answers | How it's measured |
  |---|---|---|
  | **Speed** | How fast does it win unopposed? | Goldfish win-turn distribution |
  | **Consistency** | Does it do its thing every game? | Mulligans, land drops, curve efficiency, color access |
  | **Resilience** | Does it fold to a board wipe or a counterspell? | Outcome delta under injected disruption |
  | **Interaction** | Can it stop opponents? | Answer density × coverage × castability |
  | **Ceiling** | What does its nut draw look like? | Top-percentile simulated runs, combo detection |
  | **Meta strength** | Does it actually win? | Rating vs. the reference gauntlet (the headline number) |

- **Bracket estimate with confidence** — mapped onto the official 1–5 Commander Brackets,
  calibrated, with an explanation of *which cards and behaviors* drove the estimate.
- **Upgrade advisor** — "your deck loses most often because it can't rebuild after turn-6
  wipes; these 3 swaps from your collection improve resilience by X" — recommendations backed
  by ablation simulation, not popularity alone.

## Why now / why us

- Scryfall bulk data makes complete card data free and local (MythScanner already ships a
  113k-card offline index; MythForge already parses Oracle text for themes).
- EDHREC's open JSON API provides the popularity and synergy priors.
- Local LLMs (llama-swap gateway already running on this machine) make per-card semantics
  compilation affordable at the scale of tens of thousands of cards.
- Open-source rules engines (Forge) prove full-rules simulation is possible and can serve as a
  cross-validation oracle while our native engine grows.

## Non-goals (for now)

- Playing against humans online (not a game client).
- Perfect comprehensive-rules coverage (MTG is Turing-complete; 100% is a research program,
  not a milestone — the tiered-fidelity design exists precisely so this is not a blocker).
- Formats beyond Commander first (the engine core is format-agnostic; 60-card formats are a
  configuration, not a rewrite).

## Sibling projects

- **MythScanner** (`onemorethan0/mythscannermtg`) — collection intake via webcam; exports CSV
  → MythGauntlet collection import.
- **MythForge** (`onemorethan0/mythforgemtg`) — deck generation & theming; MythGauntlet is the
  evaluator that can close MythForge's loop (generate → evaluate → improve).
