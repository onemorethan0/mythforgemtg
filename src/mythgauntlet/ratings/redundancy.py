"""Redundancy-based cut candidates: what the deck has too MUCH of.

The advisor needs a pool of cards worth cutting. The obvious heuristic — cut the
least-played card — is a trap. What sits at the bottom of a popularity ranking is pet
cards, silver bullets and utility the deck chose on purpose; those are the cards you
least want to lose. The cards actually worth cutting are the *redundant* ones: the
eleventh ramp piece in a deck that wanted ten.

So redundancy here is a property of the DECK, not of the card. A card is a cut candidate
when the functional role it fills is over-supplied relative to that role's target, and it
is a weak contributor to that role. A card with no recognised functional role is
`protected`: it can never be redundant, and it sorts to the back of the pool.

Gold set (spec: docs/SPEC_redundancy.md; role strengths are measured against the real
`tags.analyze`, not assumed). Deck context: ramp supply 18.0 (target 10 -> oversupply 8.0),
removal supply 5.0 (target 7 -> oversupply 0.0).

| card (abridged oracle text)                            | role    | over | within | score |
|--------------------------------------------------------|---------|------|--------|-------|
| Llanowar Elves "{T}: Add {G}."                           | ramp    | 8.0  | 1.0    | 4.00  |
| Worn Powerstone "enters tapped. {T}: Add {C}{C}."        | ramp    | 8.0  | 2.0    | 2.67  |
| Cultivate "Search ... two basic land cards ... tapped"   | ramp    | 8.0  | 3.0    | 2.00  |
| Swords to Plowshares "Exile target creature."            | removal | 0.0  | 1.0    | 0.00  |
| pet card "Whenever a face-down creature ... scry 1."     | None    | 0.0  | 0.0    | 0.00  |

Cut order: Llanowar Elves, Worn Powerstone, Cultivate, Swords to Plowshares, pet card —
monotone in within-role strength across the three ramp spells. The last two rows are the
point: under the old popularity rule the pet card was the FIRST cut.
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.model import EffectVector

# Typical count of each functional role in a 100-card casual Commander deck.
# ramp/draw/removal/wipe come from the builder's own numbers (playstyle.DEFAULT_SLOTS) and
# finisher from its default finisher slot, so the advisor cuts against the same shape the
# builder builds to.
#
# `counterspell` and `tutor` are ESTIMATES — the builder has no slot for either, and they
# are flagged rather than dressed up as derived numbers. This role is named `counterspell`,
# NOT `protection`: the builder's protection slot also buys ward, hexproof and
# indestructible, but the rung-1 EffectVector has no field for those, so calling it
# protection would claim a measurement that isn't happening. Ward/hexproof is not measured
# here at all — an honest under-count, per this module's stance on unreadable cards.
#
# KNOWN GAP (naming is fixed, the number is not): 3 is the protection slot's figure, and a
# blue control deck legitimately runs more counterspells than that. Corpus deck
# archidekt-10354152 supplies 24.0 against it. Its counterspells don't currently top that
# deck's cut pool, but a counterspell-heavy deck with a tighter draw count would see its
# interaction offered as redundant. Needs its own calibration.
ROLE_TARGETS: dict[str, int] = {
    "ramp": 10,
    "draw": 10,
    "removal": 7,
    "wipe": 4,
    "counterspell": 3,
    "finisher": 3,
    "tutor": 3,
}


def card_roles(ev: EffectVector) -> dict[str, float]:
    """The functional roles a card fills, and how strongly it fills each.

    An empty dict means the card has no role this module recognises — a pet card, a
    silver bullet, or something the rung-1 EffectVector simply can't see. That is treated
    as "never redundant", not as "worthless": the honest under-count, not a confident
    guess (see `score_card`).
    """
    roles = {
        "ramp": float(ev.ramp_sources) + (2.0 if ev.fetches_land else 0.0),
        "draw": float(ev.draw_cards) + 1.5 * ev.engine_draw,
        "removal": float(ev.removal),
        "wipe": 3.0 if ev.board_wipe else 0.0,
        "counterspell": 3.0 if ev.counterspell else 0.0,
        "tutor": 2.0 if ev.tutor else 0.0,
        "finisher": (
            2.0 * ev.overrun_pump
            + (3.0 if ev.overrun_scales else 0.0)
            + (3.0 if ev.grants_storm else 0.0)
            + (2.0 if ev.scaling_burn else 0.0)
            + (2.0 if ev.cheats_creatures else 0.0)
        ),
    }
    return {role: strength for role, strength in roles.items() if strength > 0.0}


def role_supply(resolved: ResolvedDeck) -> dict[str, float]:
    """How much of each role the deck's nonland spells supply, counts included.

    Commanders are excluded on purpose: the commander is never a cut candidate, and
    counting it would inflate the very role it defines, making the deck look over-supplied
    in its own strategy.
    """
    supply: dict[str, float] = {}
    for card, count in resolved.cards:
        if card.is_land:
            continue
        for role, strength in card_roles(tags.analyze(card)).items():
            supply[role] = supply.get(role, 0.0) + strength * count
    return supply


@dataclass(frozen=True)
class RedundancyScore:
    """Why one card is (or isn't) a cut candidate."""

    card: Card
    role: str | None       # the role it is most over-supplied in; None when roleless
    oversupply: float      # supply[role] - target[role], clamped at 0.0
    within_role: float     # this card's own strength in that role
    score: float           # higher = better cut candidate
    protected: bool        # roleless: never redundant, sorts last


def score_card(
    card: Card,
    supply: dict[str, float],
    targets: dict[str, int] | None = None,
) -> RedundancyScore:
    """Score one card's redundancy against the deck's role supply.

    The card is judged on the role it is MOST over-supplied in. The score combines two
    ideas that pull in opposite directions:

      score = oversupply / (1 + within_role)

    Oversupply raises it — a role the deck has ten too many of is where cuts should come
    from. Within-role strength LOWERS it, because once you've decided ramp is over-served
    you cut the worst ramp spell, not the best one. Multiplying by strength (the obvious
    formulation) inverts that and recommends cutting your Cultivate before your worst
    mana rock, which is a defect, not an approximation.

    A card whose roles are all at or under target scores 0.0 — correctly, it is not
    redundant at all.
    """
    if targets is None:            # `or` would silently ignore a deliberate empty dict
        targets = ROLE_TARGETS
    roles = card_roles(tags.analyze(card))
    if not roles:
        return RedundancyScore(card, None, 0.0, 0.0, 0.0, protected=True)

    # Highest oversupply wins; ties break on role name so the choice is deterministic.
    best_role, best_over, best_within = None, -1.0, 0.0
    for role in sorted(roles):
        over = max(0.0, supply.get(role, 0.0) - float(targets.get(role, 0)))
        if over > best_over:
            best_role, best_over, best_within = role, over, roles[role]

    return RedundancyScore(
        card=card,
        role=best_role,
        oversupply=best_over,
        within_role=best_within,
        score=best_over / (1.0 + best_within),
        protected=False,
    )


def _rank_key(card: Card) -> int:
    """EDHREC rank for tie-breaking, with unknown treated as least-played.

    `card.edhrec_rank or 10**9` reads the same and is wrong: it maps rank 0 to unknown.
    Same bug the collection pool already fixed once.
    """
    return card.edhrec_rank if card.edhrec_rank is not None else 10**9


def rank_redundant(
    resolved: ResolvedDeck,
    k: int,
    *,
    targets: dict[str, int] | None = None,
) -> list[Card]:
    """The deck's `k` best cut candidates, most redundant first.

    Ordering: redundant cards by score (descending), then — among cards the deck is
    equally over-served by — the least-played one first, since that is the safest of a
    set of interchangeable pieces. Protected (roleless) cards always sort last and are
    only returned when there aren't enough scored cards to fill `k`, so a deck of pure
    pet cards still yields a pool rather than nothing.

    Deterministic: equal scores and equal ranks fall through to card name.
    """
    k = max(1, k)
    supply = role_supply(resolved)

    scored: list[RedundancyScore] = []
    seen: set[str] = set()             # Card is a mutable dataclass -> unhashable; key by name
    for card, _count in resolved.cards:
        if card.is_land or card.name in seen:
            continue
        seen.add(card.name)
        scored.append(score_card(card, supply, targets))

    candidates = [s for s in scored if not s.protected]
    protected = [s for s in scored if s.protected]
    candidates.sort(key=lambda s: (-s.score, -_rank_key(s.card), s.card.name))
    protected.sort(key=lambda s: s.card.name)

    return [s.card for s in (candidates + protected)[:k]]
