"""Would THIS card help or hurt THIS deck, and why.

The advisor answers "what should I add" from a pool. This answers the question a player
actually asks mid-conversation: "is <card> good in my deck?" — one named card, a verdict,
and the reasoning.

Three things make the answer honest rather than a vibe:

1. **Legality is checked first and is disqualifying.** A card outside the commander's colour
   identity, or banned in Commander, is a hard no regardless of how strong it is — and that
   is a far more useful answer than a power score.

2. **Every axis is measured, not one.** "Positive or negative effect" is a whole-deck
   question. A card can buy Speed and cost Consistency, and saying so is the point.

3. **A delta under the axis's own measurement noise is reported as NO effect.** The
   seed-to-seed spread is speed 1.73, ceiling 2.31, consistency 0.94, resilience and
   interaction 0.00 (same deck, 8 seeds, runs=150). Calling a +1.0 Speed move an improvement
   would be reporting a coin flip as a finding, so `_AXIS_NOISE_FLOOR` gates every verdict.

The measurement is an ablation, like the advisor's: swap the card in for each of the deck's
weakest cards, re-run the full analysis, and keep the pairing that comes out best overall.
That matters because a 100-card deck is fixed-size — adding a card always means cutting one,
and the honest question is "better than the worst thing you are already playing?"
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mythgauntlet.model.card import Card
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings.advisor import (
    AXES,
    _AXIS_NOISE_FLOOR,
    _commander_identity,
    _swap_variant,
    _weakest_cuts,
    axis_score,
    commander_wants,
)
from mythgauntlet.ratings.analysis import analyze_deck
from mythgauntlet.semantics import tags
from mythgauntlet.sim.tier0 import SimConfig


@dataclass
class AxisMove:
    axis: str
    label: str
    before: float
    after: float
    floor: float

    @property
    def delta(self) -> float:
        return self.after - self.before

    @property
    def meaningful(self) -> bool:
        """Clears the axis's own run-to-run spread, so it is a move and not a re-roll."""
        return abs(self.delta) >= self.floor and self.floor > 0 or (
            self.floor == 0 and self.delta != 0
        )


@dataclass
class CardImpact:
    card: str
    verdict: str                    # positive | negative | neutral | illegal
    headline: str
    reasons: list[str] = field(default_factory=list)
    cut: str | None = None
    axes: list[AxisMove] = field(default_factory=list)
    legal: bool = True
    already_in_deck: bool = False


def _describe(card: Card) -> list[str]:
    """What the card actually does, from its own rules text — not from popularity."""
    fx = tags.analyze(card)
    out: list[str] = []
    if fx.ramp_sources:
        out.append(f"adds {fx.ramp_sources} net mana")
    if fx.fetches_land:
        out.append("fetches a land")
    if fx.draw_cards:
        out.append(f"draws {fx.draw_cards}")
    if fx.engine_draw:
        out.append("draws repeatedly")
    if fx.removal:
        out.append("removes a creature")
    if fx.board_wipe:
        out.append("sweeps the board")
    if fx.counterspell:
        out.append("counters a spell")
    if fx.cheats_creatures:
        out.append("cheats creatures into play")
    if card.game_changer:
        out.append("is on the Game Changers list (bracket-relevant)")
    return out


def assess_card(
    resolved: ResolvedDeck,
    card: Card,
    cfg: SimConfig,
    store,
    *,
    cut_pool: int = 3,
) -> CardImpact:
    """Measure what adding `card` does to `resolved`, and say why."""
    name = card.name

    if any(c.name == name for c, _ in resolved.cards) or any(
        c.name == name for c in resolved.commanders
    ):
        return CardImpact(
            card=name, verdict="neutral", already_in_deck=True,
            headline=f"{name} is already in this deck.",
            reasons=["Nothing to measure — it is part of the current list."],
        )

    identity = _commander_identity(resolved)
    if not card.commander_legal:
        return CardImpact(
            card=name, verdict="illegal", legal=False,
            headline=f"{name} is not legal in Commander.",
            reasons=["Banned, or never legal in the format. Power is beside the point."],
        )
    outside = set(card.color_identity or ()) - identity
    if outside:
        pretty = "".join(sorted(outside))
        return CardImpact(
            card=name, verdict="illegal", legal=False,
            headline=f"{name} is outside your colour identity ({{{pretty}}}).",
            reasons=[
                "CR 903.4: a card's colour identity must fit the commander's. "
                f"This deck is {{{''.join(sorted(identity)) or 'colourless'}}}.",
            ],
        )

    baseline = analyze_deck(resolved, cfg, store, run_resilience=True)
    cuts = _weakest_cuts(resolved, max(1, cut_pool))
    if not cuts:
        return CardImpact(
            card=name, verdict="neutral",
            headline=f"Could not measure {name} — the deck has no cuttable card.",
            reasons=["Every nonland slot is already accounted for."],
        )

    # Try each weak cut; keep the pairing with the best total meaningful movement.
    best: tuple[float, Card, list[AxisMove]] | None = None
    for cut in cuts:
        variant = _swap_variant(resolved, cut, card)
        after = analyze_deck(variant, cfg, store, run_resilience=True)
        moves = [
            AxisMove(
                axis=ax, label=AXES[ax][1],
                before=axis_score(baseline, ax), after=axis_score(after, ax),
                floor=_AXIS_NOISE_FLOOR.get(ax, 0.0),
            )
            for ax in AXES
        ]
        total = sum(m.delta for m in moves if m.meaningful)
        if best is None or total > best[0]:
            best = (total, cut, moves)

    total, cut, moves = best
    # Biggest movers first: the headline names the largest change, and the reasons read in
    # order of significance. Sorting by axis order instead named Consistency +1.9 while
    # Speed +8.3 went unmentioned, which is a true sentence that misses the point.
    gains = sorted((m for m in moves if m.meaningful and m.delta > 0),
                   key=lambda m: -m.delta)
    losses = sorted((m for m in moves if m.meaningful and m.delta < 0),
                    key=lambda m: m.delta)

    if gains and not losses:
        verdict = "positive"
        headline = f"{name} improves this deck."
    elif losses and not gains:
        verdict = "negative"
        headline = f"{name} makes this deck worse."
    elif gains and losses:
        verdict = "positive" if total > 0 else "negative"
        headline = f"{name} is a trade-off — it buys {gains[0].label.lower()} and costs {losses[0].label.lower()}."
    else:
        verdict = "neutral"
        headline = f"{name} makes no measurable difference to this deck."

    reasons: list[str] = []
    does = _describe(card)
    if does:
        reasons.append(f"What it does: {'; '.join(does)}.")
    for m in gains:
        reasons.append(f"{m.label} {m.before:.1f} → {m.after:.1f} (+{m.delta:.1f}).")
    for m in losses:
        reasons.append(f"{m.label} {m.before:.1f} → {m.after:.1f} ({m.delta:.1f}).")
    if verdict == "neutral":
        flat = ", ".join(f"{m.label} ±{m.floor:.1f}" for m in moves if m.floor > 0)
        reasons.append(
            "Every axis moved less than its own measurement noise, so this is a re-roll "
            f"rather than a change ({flat}). It may still matter for reasons the "
            "simulation does not model — politics, a combo line, or a card you enjoy."
        )
    reasons.append(f"Measured by swapping it in for {cut.name}, the weakest slot it beat.")

    wants = commander_wants(resolved.commanders)
    if wants.cheats_creatures and card.is_creature and wants.wants_big:
        reasons.append("Your commander can cheat creatures into play, which favours big bodies.")

    return CardImpact(
        card=name, verdict=verdict, headline=headline, reasons=reasons,
        cut=cut.name, axes=moves,
    )
