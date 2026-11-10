"""ONE answer to "what should I cut?", shared by the weak-card verdicts, Advise's cut pool and the
mentor's role swaps (2026-11-10).

Before this the three surfaces each picked cuts their own way -- role bookkeeping, an early-game
metric biased toward cheap cards, whichever pair cleared a noise floor -- and the owner saw them
contradict each other at a glance (Controvert / Rewind / Disallow; Ambulatory Reactor offered as
"spare ramp"). The method is the one players use (EDHREC's new-player guide, TappedOut's "EDH
deck building process: cutting cards"): protect the plan and the core role floors first, then cut
what does not help the deck win, then trim the most over-full category. What a player judges by
eye, this measures:

PROTECTED, never offered as a cut
  commander synergy   the commander lens shows the commander changing what the card does
  combo piece         a card in a graded game-ending combo the deck holds
  plan lord           a typed lord whose type covers a real share of the deck's creatures
  role floor          it fills a core role the deck is at or under its card target in --
                      cutting it opens a gap (draw, ramp, removal ...)
  load-bearing        paired drawn-games ablation (ratings/card_ablation): the deck kills
                      measurably sooner with it. Counts even for a card the goldfish only
                      partly reads: a measured help is real.

CUT ORDER for the rest, first = best cut
  1 drag       fully read by the goldfish (sim/legibility) and the deck kills measurably LATER
               with it in the games it is drawn
  2 surplus    every role it fills is over its card target (the most over-full category first,
               the redundancy model's most replaceable first). The only way an interaction card
               or a partly-read card is ever offered: a goldfish cannot value either.
  3 idle       fully read, no measurable effect in the games it is drawn (lowest shrunk value
               first)
  Partly-read cards with no surplus role are not offered at all: there is nothing to say about
  them that is not a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import card_ablation, redundancy
from mythgauntlet.sim.legibility import fully_read
from mythgauntlet.sim.tier0 import SimConfig

DRAG, SURPLUS, IDLE = "drag", "surplus", "idle"
_BUCKET = {DRAG: 0, SURPLUS: 1, IDLE: 2}


@dataclass(frozen=True)
class Cut:
    name: str
    kind: str                         # drag | surplus | idle
    why: str                          # one sentence, every number measured or counted
    value: card_ablation.CardValue | None = None
    role: str | None = None
    role_cards: int = 0
    card_target: int = 0


@dataclass
class CutRanking:
    cuts: list[Cut] = field(default_factory=list)          # best cut first
    protected: dict[str, str] = field(default_factory=dict)  # name -> why it is kept
    unjudged: list[str] = field(default_factory=list)      # partly read, no surplus role
    values: dict[str, card_ablation.CardValue] = field(default_factory=dict)

    def names(self) -> list[str]:
        return [c.name for c in self.cuts]


def rank_cuts(
    resolved: ResolvedDeck,
    cfg: SimConfig,
    *,
    lens=None,
    themes=(),
    combo_names=(),
    only=None,
) -> CutRanking:
    """Rank the deck's nonland, non-commander cards as cuts (see the module docstring).

    `only` restricts the MEASUREMENT (and the result) to these names -- a caller that needs a
    handful of candidates (a role swap) skips simulating the rest."""
    identity = sorted({ch for c in resolved.commanders for ch in c.color_identity})
    card_targets = redundancy.card_targets_for(themes, color_identity=identity)
    counts = redundancy.role_card_counts(resolved, lens)
    applicable = {r for r, t in card_targets.items() if t > 0}
    zone = {c.name for c in resolved.commanders}
    flagged = set(lens.flagged(c for c, _ in resolved.cards)) if lens is not None else set()
    lords = redundancy.plan_lords(resolved)
    combos = set(combo_names or ())
    out = CutRanking()

    pool, seen = [], set()
    for card, _n in resolved.cards:
        if card.is_land or card.name in zone or card.name in seen:
            continue
        if only is not None and card.name not in only:
            continue
        seen.add(card.name)
        pool.append(card)

    roles_of = {c.name: set(redundancy.roles_for(c, lens)) & applicable for c in pool}
    for card in pool:
        why = None
        if card.name in flagged:
            why = "the commander changes what it does (commander lens)"
        elif card.name in combos:
            why = "a piece of a game-ending combo the deck holds"
        elif card.name in lords:
            why = "a lord for a type the deck is built around"
        else:
            floor = sorted(r for r in roles_of[card.name]
                           if counts.get(r, 0) <= card_targets.get(r, 0))
            if floor:
                r = floor[0]
                why = (f"it fills {r}, which the deck runs {counts.get(r, 0)} of against a "
                       f"typical {card_targets.get(r, 0)}: cutting it opens a gap")
        if why:
            out.protected[card.name] = why

    rest = [c for c in pool if c.name not in out.protected]
    if rest:
        base = card_ablation.baseline(resolved, cfg)
        out.values = card_ablation.drawn_value(resolved, cfg, [c.name for c in rest], base=base)
    order = {c.name: i for i, c in enumerate(redundancy.rank_redundant(
        resolved, len(resolved.cards) + 1,
        targets=redundancy.targets_for(themes, color_identity=identity), lens=lens))}

    cuts: list[tuple[tuple, Cut]] = []
    for card in rest:
        v = out.values.get(card.name)
        if v is not None and v.load_bearing:
            out.protected[card.name] = (f"the deck kills {v.turns_sooner:g} turns sooner with it "
                                        f"in the {v.games} games it is drawn (paired simulation)")
            continue
        legible = fully_read(card)
        roles = roles_of[card.name]
        surplus = bool(roles) and all(counts.get(r, 0) > card_targets.get(r, 0) for r in roles)
        if legible and v is not None and v.drag:
            cuts.append(((0, v.shrunk, card.name), Cut(
                card.name, DRAG, f"the deck kills {-v.turns_sooner:g} turns later with it in "
                f"the {v.games} games it is drawn (paired simulation)", v)))
        elif surplus:
            r = max(sorted(roles), key=lambda x: counts.get(x, 0) - card_targets.get(x, 0))
            cuts.append(((1, -(counts.get(r, 0) - card_targets.get(r, 0)),
                          order.get(card.name, 10**6), card.name), Cut(
                card.name, SURPLUS, f"the deck runs {counts.get(r, 0)} {r} cards against a "
                f"typical {card_targets.get(r, 0)}, and the role model ranks this one among the "
                f"most replaceable", v, r, counts.get(r, 0), card_targets.get(r, 0))))
        elif legible and v is not None:
            cuts.append(((2, v.shrunk, card.name), Cut(
                card.name, IDLE, f"no measurable effect on the kill in the {v.games} games it "
                f"is drawn (paired simulation)", v)))
        else:
            out.unjudged.append(card.name)
    out.cuts = [c for _k, c in sorted(cuts, key=lambda kc: kc[0])]
    return out
