"""Closed-form mana-base consistency (Karsten hypergeometric math).

Everything else in this repo measures by SIMULATION. This module is the one place that
answers a mana question analytically, because the question has an exact answer and the
exact answer is more useful than a sampled one:

    "To cast a {G}{G} spell on turn 3 at least 90% of the time, how many green sources
     does a 99-card deck need?"

Frank Karsten established the method and the 90% convention (ChannelFireball, "How Many
Colored Mana Sources Do You Need to Consistently Cast Your Spells?"); his widely-quoted
tables are for 60-card decks with a ~1.6x rule of thumb for Commander. We do not use the
tables — we evaluate the hypergeometric distribution directly for the ACTUAL deck size,
pip count, and turn, which is exact for 99-card singleton instead of scaled from 60.

**This is deliberately the CONSERVATIVE bound, and it does not reproduce Karsten's table.**
Karsten's published numbers assume a mulligan strategy (and, in later treatments, scry and
card selection); those are escape valves a one-shot hypergeometric has no way to use, so it
always demands MORE sources. Measured against his 60-card figures on the draw at 90%:

    pips / turn        this module      Karsten
    1 pip,  turn 2         13             14
    2 pips, turn 2         22             18
    3 pips, turn 3         26             21

The single-pip case nearly agrees; multi-pip diverges because that is exactly where
mulliganing a colour-screwed hand rescues you most. So do NOT present `sources_needed` as
"the Karsten number" — it is the floor you reach with no mulligan and no selection. The
honest headline is `ColorRequirement.probability`: what THIS deck's actual source count
achieves. Tier-0 already models mulligans (`free_first_mulligan`, `mulligan_min_lands`), so
the simulator remains the referee; this module is the closed-form diagnostic beside it.

Why this belongs next to the simulator rather than inside it:
  - It is deterministic and offline: no RNG, no seeds, no card data beyond produced_mana.
  - It DIAGNOSES rather than scores. T0 can tell you a deck stumbled; this tells you it
    stumbled on {G}{G} by turn 3 at 14 green sources, and quantifies the gap.

Deliberate simplifications (stated, per repo convention):
  - Cards seen = opening 7 + one per turn. No mulligans, no cantrips, no extra draw, no
    scry/surveil selection — see the calibration note above.
  - A "source" is any card whose produced_mana includes the color. Untapped-ness, ETB
    conditions (fetches, filters, tapped duals), and activation costs are NOT modeled, so
    a greedy tapland-heavy base reads slightly better here than it plays. Karsten's own
    tables carry the same caveat.
  - Hybrid pips count as satisfied by EITHER color; a pip is evaluated against the union
    of its colors' sources, which slightly over-counts when the two overlap.
  - Generic costs are ignored — this measures COLOR consistency, not total mana.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import comb

# Karsten's convention: a mana base is "consistent" when it casts on curve this often.
TARGET_PROBABILITY = 0.90

# Cards seen by turn T on the play: opening 7 plus one draw per turn after the first.
OPENING_HAND = 7


def cards_seen(turn: int, on_play: bool = True) -> int:
    """Cards seen by the start of `turn`'s main phase. On the draw you see one more."""
    return OPENING_HAND + max(0, turn - 1) + (0 if on_play else 1)


def hypergeom_at_least(population: int, successes: int, draws: int, k: int) -> float:
    """P(at least k successes) drawing `draws` from `population` containing `successes`.

    Exact rational arithmetic via comb(); no floating-point sampling error.
    """
    if k <= 0:
        return 1.0
    if successes < k or draws < k:
        return 0.0
    draws = min(draws, population)
    total = comb(population, draws)
    if total == 0:
        return 0.0
    # P(X >= k) = 1 - P(X <= k-1)
    below = sum(
        comb(successes, i) * comb(population - successes, draws - i)
        for i in range(0, k)
        if 0 <= draws - i <= population - successes
    )
    return 1.0 - below / total


def sources_needed(
    deck_size: int,
    pips: int,
    turn: int,
    *,
    on_play: bool = True,
    target: float = TARGET_PROBABILITY,
) -> int:
    """Fewest sources that reach `target` probability of having `pips` of them by `turn`.

    Returns deck_size when even a full deck of sources cannot reach the target (which
    happens for absurd pip counts on early turns — a real "you cannot get there" answer).
    """
    seen = cards_seen(turn, on_play)
    for k in range(pips, deck_size + 1):
        if hypergeom_at_least(deck_size, k, seen, pips) >= target:
            return k
    return deck_size


@dataclass(frozen=True)
class ColorRequirement:
    """One card's demand on one color, and whether the deck can meet it."""

    color: str
    pips: int
    turn: int          # the turn we want to cast it (= its mana value, floored at 1)
    have: int
    need: int          # no-mulligan floor; NOT Karsten's table value (see module docstring)
    probability: float  # what `have` actually achieves — the honest headline
    example: str       # a card in the deck that creates this requirement

    @property
    def shortfall(self) -> int:
        return max(0, self.need - self.have)

    @property
    def met(self) -> bool:
        return self.have >= self.need


@dataclass(frozen=True)
class ManabaseReport:
    deck_size: int
    sources: dict[str, int]
    requirements: list[ColorRequirement]

    @property
    def worst(self) -> list[ColorRequirement]:
        """Requirements the base serves least well, least likely first."""
        return sorted(self.requirements, key=lambda r: (r.probability, r.turn, r.color))

    @property
    def consistency(self) -> float:
        """Mean probability across the deck's colour demands (0..1).

        Deliberately the MEAN ACHIEVED PROBABILITY rather than the share of requirements
        clearing `need`. Counting pass/fail against the no-mulligan floor is misleading in
        the common case: a Golgari deck with 38 green and 14 black scores 25% "met" even
        though the only real problem is black — its {G}{G} sits at P=0.89, which plays fine
        once mulligans exist. Averaging the probabilities says "mostly fine, black is thin",
        which is the true shape.
        """
        if not self.requirements:
            return 1.0
        return sum(r.probability for r in self.requirements) / len(self.requirements)


_BASIC_TYPE_COLORS = {"plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G"}

# Both real fetch wordings. A TYPED fetch names land types and says "card", not
# "land card" — Misty Rainforest reads "…for a Forest or Island card" — so a pattern
# anchored on the literal "land card" silently matched only the generic ones.
_FETCH_RE = re.compile(
    r"search your library for (?:an?|up to \w+)\s+([^.]*?)\bcards?\b", re.IGNORECASE
)

# A land-tutor that puts the found card into HAND rather than onto the battlefield is still
# real colour fixing -- just a turn later once it's cast -- so it should be credited the same
# as a battlefield fetch, not treated as a dead search. Matched on the Comprehensive-Rules
# template wording ("search your library for a land card, reveal it, put it into your hand"
# / "...put that card into your hand") rather than a looser guess, per the same conservatism
# the battlefield case already applies (a bare "cards" search with neither destination stays
# uncredited).
_HAND_RE = re.compile(r"put (?:it|that card) into (?:your|their) hand", re.IGNORECASE)


def fetched_colors(card, basic_colors: set[str] | None = None) -> set[str]:
    """Colours a land can put onto the battlefield OR into hand, even if it taps for none itself.

    Fetchlands carry `produced_mana == []` on Scryfall — correctly, they tap for no mana —
    so counting only `produced_mana` scored every one of them as ZERO colour sources.
    That is wrong for consistency math: a fetchland IS a source for whatever it can find,
    which is how manabase counting is normally done.

    This mattered because `manabase_consistency` is the SOLE discriminator for the
    Bracket 1 vs 2 gate, and the common cases are the BUDGET fetches casual decks
    actually run — Evolving Wilds, Terramorphic Expanse, Fabled Passage, Prismatic
    Vista — not the expensive ones. All of them counted zero.

    A land TUTOR that puts the found land into HAND (Edge of Autumn's class) is credited
    the same way — it is real fixing, not a dead search, even though the card doesn't tap
    for mana until the fetched land is later played. Excluded only when the search names
    something that isn't a land at all (a true dead fetch for this purpose).

    `basic_colors` is the set of colours the deck can really find with a generic
    "basic land card" fetch, i.e. colours it runs an actual basic in. Passing it keeps
    the credit honest: an Evolving Wilds in a deck with no basic Swamp is not a black
    source. A TYPED fetch is not restricted that way — "a Forest or Island card" finds
    any land with that type, including duals, so it counts for those colours outright.
    """
    if "Land" not in (getattr(card, "type_line", "") or ""):
        return set()
    text = getattr(card, "oracle_text", "") or ""
    match = _FETCH_RE.search(text)
    if not match:
        return set()
    lower = text.lower()
    if "onto the battlefield" not in lower and not _HAND_RE.search(text):
        return set()
    named = {c for word, c in _BASIC_TYPE_COLORS.items() if word in match.group(1).lower()}
    if named:
        return named
    if "land" not in match.group(1).lower():
        return set()                       # searches for something that isn't a land
    return set("WUBRG") if basic_colors is None else set(basic_colors)


def count_sources(cards: list[tuple]) -> dict[str, int]:
    """Sources per color across (card, quantity) pairs — anything that produces the color."""
    counts = dict.fromkeys("WUBRG", 0)
    # Which colours a generic "basic land card" fetch can actually find in THIS deck.
    basic_colors: set[str] = set()
    for card, _qty in cards:
        type_line = getattr(card, "type_line", "") or ""
        if "Basic" in type_line and "Land" in type_line:
            basic_colors.update(s for s in (getattr(card, "produced_mana", ()) or ()) if s in counts)
    for card, qty in cards:
        for symbol in getattr(card, "produced_mana", ()) or ():
            if symbol in counts:
                counts[symbol] += qty
        # A land that taps for mana AND fetches (Krosan Verge, Thawing Glaciers) is both.
        for symbol in fetched_colors(card, basic_colors):
            if symbol in counts:
                counts[symbol] += qty
    return counts


def analyze(cards: list[tuple], commanders: list | None = None) -> ManabaseReport:
    """Build the per-colour requirement report for a resolved deck.

    `cards` is the deck's (Card, quantity) list; `commanders` are evaluated too — the
    commander is the one card you can always expect to cast, so its pips matter most.
    """
    deck_size = sum(qty for _card, qty in cards) or 1
    sources = count_sources(cards)

    # Collapse to the HARDEST demand per (color, pip-count): the earliest turn any card
    # asks for that many pips. Two double-green cards don't create two problems — the
    # cheaper one is the binding constraint.
    hardest: dict[tuple[str, int], tuple[int, str]] = {}
    for card in list(commanders or []) + [c for c, _ in cards]:
        cost = getattr(card, "cost", None)
        if cost is None or not getattr(cost, "pips", ()):
            continue
        demand: dict[str, int] = {}
        for pip in cost.pips:
            colors = {c for c in pip if c in "WUBRG"}
            if len(colors) == 1:  # hybrid pips are flexible; don't bind the base
                color = next(iter(colors))
                demand[color] = demand.get(color, 0) + 1
        for color, pips in demand.items():
            turn = max(1, getattr(card, "mana_value", 1))
            key = (color, pips)
            if key not in hardest or turn < hardest[key][0]:
                hardest[key] = (turn, card.name)

    requirements = [
        ColorRequirement(
            color=color, pips=pips, turn=turn,
            have=sources.get(color, 0),
            need=sources_needed(deck_size, pips, turn),
            probability=hypergeom_at_least(
                deck_size, sources.get(color, 0), cards_seen(turn), pips
            ),
            example=name,
        )
        for (color, pips), (turn, name) in sorted(hardest.items())
    ]
    return ManabaseReport(deck_size=deck_size, sources=sources, requirements=requirements)
