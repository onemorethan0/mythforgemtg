"""A swap that targets an under-supplied ROLE: add an owned card that fills it, cut a card from a
role the deck runs MORE than its card target of, and measure the result on every axis.

`advisor.advise` searches by AXIS (resilience, clock, ...), so a role question ("removal 2 vs 7 --
which cards should I cut?") was answered by whatever axis the model picked, and nothing tied the
swap to the role the deck was short on (2026-10-18: Vraska's swap added Swords to Plowshares only
because it happened to move the clock). This module ties them together without inventing a new
score: the add pool is restricted to owned cards that fill the role, the cut pool to cards whose
EVERY applicable role is over its card target (so the cut cannot open a new gap), and the swap is
measured on the role's own axis (`ROLE_AXIS`) plus a cost check on every other axis.

THE COST CHECK IS THE POINT, measured before building it. On Vraska (removal 2/7, ramp 13/12,
finisher 4/2), adding Swords to Plowshares raised interaction 62.0 -> 70.9 whichever card it
replaced, but replacing Craterclaw Colossus cost ceiling -27.3 and replacing Sentinel Sarah Lyons
cost speed -4.0, while replacing Tempered Steel moved nothing else beyond its noise floor. A cut is
"redundant by role count" and still load-bearing on an axis, so a role swap measured only on its
own axis would recommend the -27 one as readily as the free one.

Honest limits: `interaction` (the axis for removal / wipe / counterspell) is closed-form -- it
counts answers weighted by cost and speed -- so any castable answer raises it and the measurement
mostly ranks CHEAP answers above expensive ones. `noncreature_removal` has no axis at all
(`axes.compute_interaction` ignores it), so it gets the role count and the cost check only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterable

from mythgauntlet.model.card import Card
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import advisor, redundancy
from mythgauntlet.ratings.analysis import DeckAnalysis, analyze_deck
from mythgauntlet.ratings.axes import compute_interaction
from mythgauntlet.semantics.commander_lens import CommanderLens
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier0 import SimConfig

# The advisor axis that measures a role. None = no axis reads that role.
ROLE_AXIS: dict[str, str | None] = {
    "removal": "interaction",
    "wipe": "interaction",
    "counterspell": "interaction",
    "noncreature_removal": None,
    "draw": "consistency",
    "tutor": "consistency",
    "ramp": "clock",
    "finisher": "ceiling",
}

# Every axis the cost check reads (the swap's own axis is reported as its gain, not a cost).
COST_AXES: tuple[str, ...] = tuple(advisor.AXES)


def card_role_set(card: Card, lens: CommanderLens | None = None) -> set[str]:
    return set(redundancy.roles_for(card, lens))


@dataclass(frozen=True)
class CutCandidate:
    card: Card
    role: str        # the over-target role it is offered from (the most over)
    cards: int       # how many cards fill that role
    card_target: int


def role_cut_pool(
    resolved: ResolvedDeck,
    role: str,
    card_counts: dict[str, int],
    card_targets: dict[str, int],
    applicable: set[str],
    strength_targets: dict[str, int] | None = None,
    lens: CommanderLens | None = None,
) -> list[CutCandidate]:
    """Nonland deck cards safe to cut for `role`, best first.

    A card qualifies only when it fills at least one applicable role and EVERY applicable role it
    fills is OVER its card target -- so cutting it leaves each of them at or above target, never
    opens a new gap, and never trades away `role` itself. Ordered by how far over its most
    over-supplied role is (in cards), then by `redundancy.rank_redundant`'s order (the existing
    strength-score ranking, cheap cards protected), then name."""
    over = {r for r in applicable
            if card_targets.get(r, 0) > 0 and card_counts.get(r, 0) > card_targets[r]}
    if not over:
        return []
    order = {c.name: i for i, c in enumerate(redundancy.rank_redundant(
        resolved, len(resolved.cards) + 1, targets=strength_targets, lens=lens))}
    out: list[CutCandidate] = []
    seen: set[str] = set()
    flagged = lens.flagged(c for c, _ in resolved.cards) if lens is not None else set()
    for card, _qty in resolved.cards:
        if card.is_land or card.name in seen or card.name in flagged:
            continue
        seen.add(card.name)
        roles = card_role_set(card, lens) & applicable
        if not roles or role in roles or not roles <= over:
            continue
        best = max(sorted(roles), key=lambda r: card_counts[r] - card_targets[r])
        out.append(CutCandidate(card, best, card_counts[best], card_targets[best]))
    out.sort(key=lambda c: (-(c.cards - c.card_target), order.get(c.card.name, 10**6),
                            c.card.name))
    return out


def role_add_pool(resolved: ResolvedDeck, role: str, candidates: Iterable[Card],
                  lens: CommanderLens | None = None) -> list[Card]:
    """Owned candidates that fill `role`, legal in this deck, not already in it."""
    in_deck = {c.name for c, _ in resolved.cards} | {c.name for c in resolved.commanders}
    identity = advisor._commander_identity(resolved)
    out, seen = [], set()
    for c in candidates:
        if c.name in in_deck or c.name in seen or not advisor._is_legal_candidate(c, identity):
            continue
        if role in card_role_set(c, lens):
            seen.add(c.name)
            out.append(c)
    return out


def _order_adds(resolved: ResolvedDeck, adds: list[Card], axis: str | None,
                first_cut: Card | None) -> list[Card]:
    """Most promising add first. `interaction` is closed-form, so it is ranked EXACTLY (the
    variant's interaction score); the simulated axes fall back to the advisor's priors."""
    if axis == "interaction" and first_cut is not None:
        def score(c: Card) -> float:
            variant = advisor._swap_variant(resolved, first_cut, c)
            # Same card list `analyze_deck` scores (partners ride along as library cards).
            cmd = variant.commanders[0] if variant.commanders else None
            cards = list(variant.cards) + [(c, 1) for c in variant.commanders[1:]]
            ident = {ch for c in variant.commanders for ch in c.color_identity}
            return compute_interaction(cards, cmd, ident).score
        scored = [(c, score(c)) for c in adds]
        scored.sort(key=lambda cs: (-cs[1], cs[0].edhrec_rank or 10**9, cs[0].name))
        return [c for c, _ in scored]
    if axis is None:
        return sorted(adds, key=lambda c: (c.edhrec_rank or 10**9, c.name))
    return advisor._prioritize(adds, axis, advisor.commander_wants(resolved.commanders))


@dataclass
class AxisMove:
    axis: str
    before: float
    after: float
    delta: float
    noise_floor: float   # the larger of the axis's seed-to-seed spread and min_delta
    beyond_noise: bool


@dataclass
class RoleSwap:
    add: str
    cut: str
    cut_role: str
    cut_role_cards: int
    cut_role_target: int
    role_cards_before: int
    role_cards_after: int
    gain: AxisMove | None            # the role's own axis; None when no axis reads the role
    moves: list[AxisMove]            # every OTHER axis
    costs: list[str]                 # axes that DROPPED beyond their noise floor


@dataclass
class RoleSwapReport:
    role: str
    axis: str | None
    role_cards: int
    card_target: int
    adds_available: int
    cuts_available: int
    pairs_measured: int
    swap: RoleSwap | None
    rejected: list[RoleSwap] = field(default_factory=list)   # measured, not chosen
    reason: str = ""                 # why there is no swap, when swap is None


def _moves(base: DeckAnalysis, after: DeckAnalysis, runs: int, min_delta: float):
    out = []
    for ax in COST_AXES:
        b, a = advisor.axis_score(base, ax), advisor.axis_score(after, ax)
        floor = max(min_delta, advisor._noise_floor(ax, runs))
        out.append(AxisMove(ax, round(b, 1), round(a, 1), round(a - b, 1), round(floor, 2),
                            abs(a - b) >= floor))
    return out


def role_swap(
    resolved: ResolvedDeck,
    cfg: SimConfig,
    store: SemanticsStore,
    candidates: Iterable[Card],
    *,
    role: str,
    card_targets: dict[str, int],
    applicable: set[str],
    baseline: DeckAnalysis | None = None,
    strength_targets: dict[str, int] | None = None,
    max_eval: int = 1,
    cut_pool: int = 2,
    min_delta: float = 1.0,
    lens: CommanderLens | None = None,
) -> RoleSwapReport:
    """Measure up to `max_eval` x `cut_pool` (add, cut) pairs for `role` and pick one.

    Choice: a pair whose own-axis gain clears its noise floor (any pair, for a role no axis
    reads) and that costs no other axis beyond its noise floor; among those the largest gain.
    When every measured pair carries a cost the one with the smallest total loss is returned
    WITH its costs, never silently -- the caller must say what it costs."""
    counts = redundancy.role_card_counts(resolved, lens)
    axis = ROLE_AXIS.get(role)
    report = RoleSwapReport(role=role, axis=axis, role_cards=counts.get(role, 0),
                            card_target=card_targets.get(role, 0), adds_available=0,
                            cuts_available=0, pairs_measured=0, swap=None)
    adds = role_add_pool(resolved, role, candidates, lens)
    cuts = role_cut_pool(resolved, role, counts, card_targets, applicable, strength_targets, lens)
    report.adds_available, report.cuts_available = len(adds), len(cuts)
    if not adds:
        report.reason = f"no owned, in-colour card outside the deck fills {role}"
        return report
    if not cuts:
        report.reason = ("no role is over its card target with cards that fill only over-target "
                         "roles, so there is no card the role counts say is spare")
        return report
    cuts = cuts[:max(1, cut_pool)]
    adds = _order_adds(resolved, adds, axis, cuts[0].card)[:max(1, max_eval)]
    if baseline is None:
        baseline = analyze_deck(resolved, cfg, store, run_resilience=True)

    measured: list[tuple[RoleSwap, float]] = []
    for add in adds:
        for cut in cuts:
            variant = advisor._swap_variant(resolved, cut.card, add)
            a = analyze_deck(variant, cfg, store, run_resilience=True)
            report.pairs_measured += 1
            moves = _moves(baseline, a, cfg.runs, min_delta)
            gain = next((m for m in moves if m.axis == axis), None)
            others = [m for m in moves if m.axis != axis]
            costs = [m.axis for m in others if m.beyond_noise and m.delta < 0]
            loss = sum(-m.delta for m in others if m.beyond_noise and m.delta < 0)
            after_counts = redundancy.role_card_counts(variant)
            measured.append((RoleSwap(
                add=add.name, cut=cut.card.name, cut_role=cut.role,
                cut_role_cards=cut.cards, cut_role_target=cut.card_target,
                role_cards_before=counts.get(role, 0),
                role_cards_after=after_counts.get(role, 0),
                gain=gain, moves=others, costs=costs), loss))

    def gained(s: RoleSwap) -> bool:
        return s.gain is None or (s.gain.beyond_noise and s.gain.delta > 0)

    viable = [(s, loss) for s, loss in measured if gained(s)]
    if not viable:
        report.rejected = [s for s, _ in measured]
        report.reason = (f"no measured pair raised {axis} beyond its noise floor")
        return report
    viable.sort(key=lambda sl: (sl[1] > 0, sl[1], -(sl[0].gain.delta if sl[0].gain else 0.0),
                                sl[0].add, sl[0].cut))
    report.swap = viable[0][0]
    report.rejected = [s for s, _ in measured if s is not report.swap]
    return report
