# Learning & Ratings — turning games into judgment

This layer converts raw simulation outcomes into the things users actually want: a deck
rating that means something, a bracket estimate, and an engine that gets *better at judging
card combinations* the more it plays. Nothing here touches the engine's determinism — learning
consumes simulation output and produces priors/ratings/models as versioned artifacts.

## 1. Deck ratings — the gauntlet

**The reference gauntlet** is a curated, versioned set of ~30–60 benchmark decks spanning the
power spectrum: WotC precons (natural Bracket-2 anchors), EDHREC average decks for popular
commanders (Bracket 3), tuned/optimized lists (Bracket 4), and known cEDH archetypes
(Bracket 5). Gauntlet membership is data (`data/gauntlet/*.txt` + manifest), not code.

**Rating model: Bradley-Terry** (logistic pairwise-strength; the standard model behind
Elo-style systems). A candidate deck plays T2 matches against a spread of gauntlet decks; its
rating is the MLE fit over outcomes. Multiplayer results decompose into pairwise terms
(finish-order → pairwise wins) — a documented approximation, revisited with data. Ratings
carry uncertainty (games played, opponent spread) and are always tagged with
`(engine version, CCM snapshot, agent level)` — a rating is a measurement *by an instrument*,
and the instrument version matters.

## 2. Bracket calibration — pinning the scale to reality

Raw ratings are only internally consistent. To report **official Commander Brackets (1–5)**:

- **Anchors**: precons pin Bracket 2; curated cEDH lists pin Bracket 5; community-labeled
  decks (bracket self-reports scraped/collected over time) fill the middle.
- **Model**: ordinal regression from (rating + Power Profile axes + hard bracket rules) →
  bracket. Hard rules are respected first — Game Changers count, mass-land-denial, chained
  extra turns, and 2-card infinite combos gate brackets per the official beta rules
  (53 Game Changers as of Feb 2026; the list is data, refreshed with WotC updates).
- **Validation**: held-out anchors. Report accuracy as "bracket-exact / within-one" — the
  honest way the static calculators don't.

## 3. Card & combination value — the self-improving core

The user asked for an engine that "refines its understanding over time in its ability to judge
different card combinations." Concretely, three mechanisms, cheapest first:

### 3a. Credit assignment from played games
Every simulated game logs which cards were drawn/cast and when. Across many games of many
decks, fit a regularized logistic model: `P(win) ~ f(cards cast, turns cast, interactions)`.
Presence-when-winning vs presence-when-losing gives each card a **contextual value estimate**
far beyond popularity (a mediocre card that wins games *in this deck* is not mediocre here).

### 3b. Ablation simulation (Shapley-lite)
For a target deck: re-simulate with a card (or package) swapped for a neutral filler, same
seeds. The paired outcome delta is that card's **marginal contribution** in context. Exact
Shapley values are exponential; sampled single-card and package-level ablations are cheap and
directly power the **upgrade advisor** ("this slot is your weakest; here's the measured gain
from each candidate replacement you own").

### 3c. Synergy discovery
Pairwise (later higher-order) interaction terms in the 3a model, restricted to
card pairs that co-occur enough to estimate. Priors from EDHREC synergy scores (their formula:
inclusion% for commander − inclusion% for color identity) keep the model sane at low sample
sizes; simulation evidence overrides priors as games accumulate. Output: a growing **synergy
graph** (card × card × context → lift), which is also a deck-building feature in its own
right.

## 4. The improvement loop

```
        ┌───────────────────────────────────────────────────────────┐
        ▼                                                           │
  simulate games ──► outcomes DB ──► card/combo value model ──► better agent
        ▲                    │              evaluation (3a/3c)      │
        │                    ▼                                      │
        │             deck ratings &                                │
        │             bracket calibration                           │
        │                    │                                      │
  more CCM coverage ◄── quarantine/priority queue ◄── coverage & disagreement
  (semantics compiler)      signals (which cards' approximations are hurting most)
```

Two flywheels: (1) better card values → better agent evaluations → more realistic games →
better card values; (2) simulation disagreement with reality (calibration misses, Forge
divergence) prioritizes which cards get compiled to higher semantic rungs next.

**Guard rails**: agent/model updates never silently rewrite history — ratings re-base as a
new versioned series; regression suites of fixed matchups with expected win-rate bands run in
CI to catch engine drift; and per invariant #4, popularity priors decay as real evidence
arrives instead of being baked into scores.

## 5. Success metrics for this layer

- Bracket accuracy on held-out anchors (exact / ±1) — beat the static calculators' honesty gap.
- Rank correlation between simulated win rates and Forge-oracle win rates on the shared pool.
- Upgrade-advisor lift: measured rating gain of advised swaps vs. EDHREC-popularity swaps on
  the same decks (win condition: simulation advice beats popularity advice).
- Calibration curve: predicted vs. realized win rates across the gauntlet.
