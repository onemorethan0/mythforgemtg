# SPEC — `src/mythgauntlet/ratings/redundancy.py`

Cut-candidate selection for the upgrade advisor.

## Why this exists

The advisor needs a pool of cards worth cutting. It used to take the deck's least-played
nonland cards (`advisor._weakest_cuts`, highest EDHREC rank first, unknown rank weakest of
all). That rule is backwards. What sits at the bottom of a popularity ranking is pet cards,
silver bullets and utility the pilot chose on purpose — the cards they least want to lose.

The cards actually worth cutting are the **redundant** ones: the eleventh ramp piece in a
deck that wanted ten. Redundancy is therefore a property of the **deck**, not of the card.

Prior art: [recommander.cards](https://recommander.cards) reaches the same conclusion from
the collaborative-filtering side and stops there — a pure association model can only say
what a card correlates with, so it cannot tell over-supply from fit. This engine has a role
taxonomy and a simulator, so it can.

## Role targets

**Calibrated against real decks, not borrowed from the builder.** Each target is the 60th
percentile of what the corpus decks actually supply in that role; regenerate with
`python scripts/role_targets.py` (`--check` diffs against the constant).

The sample is **all 499** corpus decks. It used to stop at 120, which mis-measured `tutor`
(2 against a true 4) and was invisible because `--check` re-measured under the same cap the
constant came from — a checker that could only agree with itself.

| role | target |
|---|---|
| ramp | 14 |
| draw | 16 |
| removal | 4 |
| wipe | 3 |
| counterspell | 3 |
| finisher | 2 |
| tutor | 4 |

The first version took these from `playstyle.DEFAULT_SLOTS` — the builder's plan for a deck
it is about to *construct*. That is the wrong baseline for judging a deck someone already
owns, and measuring showed why: the plan sits **below** the population median for ramp and
draw and **above** it for removal and wipe.

| role | old (plan) | median supply |
|---|---|---|
| ramp | 10 | 12.0 |
| draw | 10 | 14.5 |
| removal | 7 | 4.0 |
| wipe | 4 | 3.0 |
| counterspell | 3 | 0.0 |

So nearly every deck read as draw/ramp-oversupplied and essentially none ever read as
removal-oversupplied. The cut pool came out systematically lopsided — **draw 48.7% and ramp
34.5%** of all suggestions against **removal 1.5% and wipe 1.0%**. That is an artifact of
the baseline, not a judgement about any deck.

p60 rather than p50, so a role must clear a modest evidential bar before counting as
over-served. Swept against cut-pool balance:

| targets | top role share | draw+ramp | removal+wipe |
|---|---|---|---|
| old (plan) | 48.7% | 83.2% | 2.5% |
| p50 | 34.9% | 63.8% | 12.3% |
| **p60** | **32.8%** | **57.8%** | **17.1%** |
| p75 | 30.4% | 55.7% | 16.4% |

p75 barely improves on p60 while pushing targets so high (ramp 18, draw 20) that little
would ever flag. A floor of 2 applies: the median deck runs **zero** counterspells, and
"any counterspell is redundant" is obviously wrong.

**The counterspell role is named `counterspell`, not `protection`, deliberately.** The
builder's `protection` slot also buys ward, hexproof and indestructible, but the rung-1
`EffectVector` has no field for any of those — it only knows `counterspell`. Naming this
role `protection` would claim a measurement that isn't happening; ward and hexproof are
**not measured here at all**, the honest under-count. Its target of 3 is now *derived* from
the p60 sweep rather than borrowed from the protection slot, which closes the calibration
gap this module shipped with.

## Role derivation (from `EffectVector`)

| role | strength |
|---|---|
| ramp | `ramp_sources + (2.0 if fetches_land)` |
| draw | `draw_cards + 1.5 * engine_draw` |
| removal | `removal` |
| wipe | `3.0 if board_wipe` |
| counterspell | `3.0 if counterspell` |
| tutor | `2.0 if tutor` |
| finisher | `2*overrun_pump + 3*overrun_scales + 3*grants_storm + 2*scaling_burn + 2*cheats_creatures` |

Only roles with strength > 0 are kept. **An empty result means the card has no role this
module recognises**, which is treated as "never redundant" — the honest under-count rather
than a confident guess.

## Scoring

    score = oversupply / (1 + within_role)

where `oversupply = max(0, supply[role] - target[role])` for the role the card is *most*
over-supplied in, and `within_role` is the card's own strength in that role.

Oversupply raises the score; within-role strength **lowers** it. This is the load-bearing
detail: once ramp is over-served you cut the *worst* ramp spell, not the best one. The
obvious formulation (`oversupply * within_role`) inverts that and recommends cutting your
Cultivate before your worst mana rock. That is a defect, not an approximation.

A card whose roles are all at or under target scores 0.0 — correctly, it is not redundant.

## Gold set

Role strengths below are the values `tags.analyze` actually produces, measured — not
assumed. Deck context: ramp supply 18.0 (target **14** → oversupply 4.0), removal supply
3.0 (target **4** → oversupply 0.0). Targets are the p60 of what real decks supply and
are regenerated by `scripts/role_targets.py` — see ROLE_TARGETS for why the builder's
slot plan was the wrong baseline.

| card (abridged oracle text) | role | oversupply | within | score | note |
|---|---|---|---|---|---|
| Llanowar Elves — "{T}: Add {G}." | ramp | 4.0 | 1.0 | 2.00 | weakest ramp → cut first |
| Worn Powerstone — "enters tapped. {T}: Add {C}{C}." | ramp | 4.0 | 2.0 | 1.33 | better ramp → cut later |
| Cultivate — "Search … two basic land cards …" | ramp | 4.0 | 3.0 | 1.00 | best ramp → cut last of the three |
| Swords to Plowshares — "Exile target creature." | removal | 0.0 | 1.0 | 0.00 | removal is not over-served |
| a manifest-blink pet card — "Whenever a face-down creature you control is turned face up, scry 1." | `None` | 0.0 | 0.0 | 0.00 | **protected**, sorts last |

Cut order: Llanowar Elves, Worn Powerstone, Cultivate, Swords to Plowshares, pet card —
monotone in within-role strength across the three ramp spells, which is the property that
matters.

The last two rows are the whole point: under the old popularity rule the pet card was the
*first* cut. Here it is the last.

## Archetype targets

One population baseline cannot judge every deck. A deck that plays to a role as its **plan**
reads as over-supplied in exactly the thing it is trying to do: `counterspell`'s population
target of 3 is the weight of a *single card* (the median corpus deck runs zero), while the
corpus decks that actually are spellslinger decks supply a p60 of **12** — so their whole
plan became the cut pool, Flusterstorm and Mental Misstep included.

`ARCHETYPE_ROLE_TARGETS` records, per archetype, the same p60 of real supply measured over
only the decks detected as that archetype. Regenerate with
`python scripts/archetype_role_targets.py` (`--check` diffs, `--audit` shows every candidate
cell and the gate that rejected it).

| archetype | role | target | population |
|---|---|---|---|
| spellslinger | counterspell | 12 | 3 |
| spellslinger | draw | 26 | 16 |
| draw_matters | counterspell | 9 | 3 |
| landfall | ramp | 23 | 14 |
| chaos | draw | 28 | 16 |

A cell is baked only when it clears three gates: **≥20 decks** carry the theme, **both
halves** of those decks independently exceed the population target, and the archetype wants
at least **3 more supply units**. The table only ever raises a target — the defect is
false-positive cut suggestions, and a lower target manufactures more of them.

It raises the bar; it does not remove it. A deck past even its archetype's supply is still
flagged, which is why the own-plan share of the cut pool falls to 33.8% rather than to zero.

## Public API

```python
ROLE_TARGETS: dict[str, int]
ARCHETYPE_ROLE_TARGETS: dict[str, dict[str, int]]

def targets_for(themes: Iterable[str] | None, base=None) -> dict[str, int]
def card_roles(ev: EffectVector) -> dict[str, float]
def role_supply(resolved: ResolvedDeck) -> dict[str, float]

@dataclass(frozen=True)
class RedundancyScore:
    card: Card
    role: str | None      # most over-supplied role; None when roleless
    oversupply: float
    within_role: float
    score: float
    protected: bool

def score_card(card, supply, targets=None) -> RedundancyScore
def rank_redundant(resolved, k, *, targets=None) -> list[Card]
```

## Contracts

- `role_supply` skips lands and **excludes commanders**. The commander is never a cut
  candidate, and counting it would inflate the very role it defines — making the deck look
  over-supplied in its own strategy.
- `rank_redundant` ordering: score descending; then, among equally-redundant cards, the
  **least-played first** (EDHREC rank descending, `None` = least played) since that is the
  safest of a set of interchangeable pieces; then card name.
- Protected cards always sort last, and are returned only when there are not enough scored
  cards to fill `k` — so a deck of pure pet cards still yields a pool rather than nothing.
- `k` is clamped to at least 1.
- Deduplicate by card **name**: `Card` is a mutable dataclass and therefore unhashable.
- `targets=None` means "use `ROLE_TARGETS`". An explicitly-passed empty dict must be
  honoured, so the check is `is None`, not `or`.
- `targets_for` takes archetype names as **plain strings** and never raises on an unknown
  one — the detector (`deck_themes`) lives in Forge, a separate process on a separate
  release cadence, so the engine is *told* what the deck is and cannot look it up. An
  unrecognised name degrades to the population baseline.
- `targets_for` merges several archetypes by **max**, only ever RAISES a target above the
  population, and never mutates `ROLE_TARGETS`.
- Pure, offline, deterministic. No I/O, no network, no logging.

## Known limit — the score is silent when nothing is over-supplied

`score = oversupply / (1 + within_role)`, so a deck that over-supplies NOTHING scores every
card at exactly 0.0 and the ordering falls entirely through to the tiebreak: **least-played
first**, which is the rule this module exists to replace. Roleless cards are still protected
and sort last, so it is "the least-played card carrying a role" rather than pure popularity.

Measured over 499 corpus decks: **45 (9.0%)** over-supply no role at all, **40 (8.0%)** have
all six pool slots at 0.0, and **426/2966 (14.4%)** of all cut slots are chosen this way. It
compounds with every calibration that raises a target — builder-slot 3.8% → p60 7.6% →
+archetype 9.0%.

`rank_redundant` still owes its caller `k` candidates, so it returns them. Consumers must not
present them as measured redundancy: `card_impact._cut_sentence` checks `oversupply > 0` and
says which it is. Tracked as **S12**.

## Consumer

`advisor.advise(..., cut_strategy=..., themes=...)` — `CUT_REDUNDANT` (default) calls
`rank_redundant`; `CUT_POPULARITY` keeps `_weakest_cuts` for the golden-master tests and as
the fallback for a deck whose cards the semantics layer cannot read at all.

`card_impact.assess_card(..., themes=...)` uses the same pool. It did not until 2026-08-20 —
it called `_weakest_cuts` directly, so the interactive "is this card good in my deck?" route
answered by displacing the deck's most obscure card. Measured over 40 (deck, card) cases the
recommended cut changed on **95%** and the final verdict on **30%**.
