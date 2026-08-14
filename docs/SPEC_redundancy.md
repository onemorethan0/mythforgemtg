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

| role | target | source |
|---|---|---|
| ramp | 10 | `playstyle.DEFAULT_SLOTS` |
| draw | 10 | `playstyle.DEFAULT_SLOTS` (`card_draw`) |
| removal | 7 | `playstyle.DEFAULT_SLOTS` |
| wipe | 4 | `playstyle.DEFAULT_SLOTS` (`board_wipe`) |
| finisher | 3 | `deck_builder` default finisher slot |
| counterspell | 3 | **estimate** — see below |
| tutor | 3 | **estimate** — the builder has no tutor slot |

The numbers are the builder's own so the advisor cuts against the same shape the builder
builds to. The two estimates are flagged rather than dressed up as derived numbers.

**The counterspell role is named `counterspell`, not `protection`, deliberately.** The
builder's `protection` slot (target 3) also buys ward, hexproof and indestructible, but the
rung-1 `EffectVector` has no field for any of those — it only knows `counterspell`. Naming
this role `protection` would claim a measurement that isn't happening. Ward and hexproof
protection is **not measured here at all** — the honest under-count, consistent with how
this module treats every card it cannot read.

This is a naming fix, **not** a numeric one: the target is still 3, and it is an estimate
for counterspells specifically. A blue control deck legitimately runs more — corpus deck
`archidekt-10354152` (Jegantha) supplies 24.0 (eight counterspells) against that 3, so its
counterspells do carry a large oversupply. They do not currently reach the top of its cut
pool (its draw role is over-served further), but a counterspell-heavy deck with a tighter
draw count would see its interaction offered as redundant. **Open: the counterspell target
needs its own calibration, not the protection slot's number.**

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
assumed. Deck context for every row: ramp supply 18.0 (target 10 → oversupply 8.0), removal
supply 5.0 (target 7 → oversupply 0.0).

| card (abridged oracle text) | role | oversupply | within | score | note |
|---|---|---|---|---|---|
| Llanowar Elves — "{T}: Add {G}." | ramp | 8.0 | 1.0 | 4.00 | weakest ramp → cut first |
| Worn Powerstone — "enters tapped. {T}: Add {C}{C}." | ramp | 8.0 | 2.0 | 2.67 | better ramp → cut later |
| Cultivate — "Search … two basic land cards … one onto the battlefield tapped" | ramp | 8.0 | 3.0 | 2.00 | best ramp (land + fetch bonus) → cut last of the three |
| Swords to Plowshares — "Exile target creature." | removal | 0.0 | 1.0 | 0.00 | removal is not over-served |
| a manifest-blink pet card — "Whenever a face-down creature you control is turned face up, scry 1." | `None` | 0.0 | 0.0 | 0.00 | **protected**, sorts last |

Cut order: Llanowar Elves, Worn Powerstone, Cultivate, Swords to Plowshares, pet card —
monotone in within-role strength across the three ramp spells, which is the property that
matters.

The last two rows are the whole point: under the old popularity rule the pet card was the
*first* cut. Here it is the last.

## Public API

```python
ROLE_TARGETS: dict[str, int]

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
- Pure, offline, deterministic. No I/O, no network, no logging.

## Consumer

`advisor.advise(..., cut_strategy=...)` — `CUT_REDUNDANT` (default) calls `rank_redundant`;
`CUT_POPULARITY` keeps `_weakest_cuts` for the golden-master tests and as the fallback for
a deck whose cards the semantics layer cannot read at all.
