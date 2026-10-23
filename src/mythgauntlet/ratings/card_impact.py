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

3. **A move must clear two bars to count.** `_AXIS_NOISE_FLOOR` is the axis's own
   seed-to-seed spread — speed 1.73, ceiling 2.31, consistency 0.94, resilience and
   interaction 0.00 (same deck, 8 seeds, runs=150) — and under it a delta is an RNG re-roll,
   not a change. `MIN_SIGNIFICANT` sits on top, because the two deterministic axes have zero
   variance, so a -0.1 was "real" and headlined "costs resilience" off a tenth of a point.
   Reproducibly trivial is still trivial.

The measurement is an ablation, like the advisor's: swap the card in for each of a small
pool of cut candidates, re-run the full analysis, and keep the pairing that comes out best
overall. That matters because a 100-card deck is fixed-size — adding a card always means
cutting one, and the honest question is "better than the thing it would displace?"

WHICH CARDS IT IS TESTED AGAINST, and why this changed. That pool used to come from
`advisor._weakest_cuts` — the deck's LEAST-PLAYED cards — long after the advisor itself
stopped using that rule. It is the rule this project measured as actively wrong: the
least-played cards in a deck are its pet cards and silver bullets, the ones the pilot put
there on purpose, so "is <card> good in my deck?" was answered by displacing the deck's most
obscure card. On the corpus Shelob deck the pool was Supper for Spiders / Gloomwidow's Feast
/ Eaten by Spiders — the deck's whole reason for existing. It now uses `redundancy`, like
the advisor, so the candidate is tested against what the deck has too MUCH of. Measured over
40 (deck, card) cases: the recommended cut changes on 95% and the final verdict on 30%, so
this was never cosmetic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from mythgauntlet.model.card import Card
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.ratings import redundancy
from mythgauntlet.ratings.advisor import (
    EMPTY_SLOT,
    AXES,
    PROFILE_AXES,
    _AXIS_NOISE_FLOOR,
    _commander_identity,
    _swap_variant,
    axis_score,
    commander_wants,
)
from mythgauntlet.ratings.analysis import analyze_deck
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.commander_lens import CommanderLens, build_lens
from mythgauntlet.sim.tier0 import SimConfig


# Smallest move worth reporting on a 0-100 axis, on top of each axis's noise floor.
# Guards the deterministic axes (resilience/interaction, sim variance 0.00), where any
# nonzero delta is technically real but a tenth of a point is not a finding.
MIN_SIGNIFICANT = 0.5



def _axis_scales() -> dict[str, float]:
    """How far apart two SIMILAR real decks sit on each axis: the mean within-bracket
    interquartile range of the generated corpus reference. Derived, not restated, so a
    re-baked reference moves it too."""
    from mythgauntlet.ratings.reference import BRACKET_AXIS_REFERENCE

    scales: dict[str, float] = {}
    for ax in PROFILE_AXES:
        iqrs = [cell[ax]["p75"] - cell[ax]["p25"] for cell in BRACKET_AXIS_REFERENCE.values()
                if ax in cell and not cell[ax].get("thin") and cell[ax].get("p75") is not None]
        if iqrs:
            scales[ax] = sum(iqrs) / len(iqrs)
    return scales


AXIS_SCALE = _axis_scales()
_DEFAULT_SCALE = 20.0
# |net| below this many typical-deck-gaps is reported as "mixed" (see assess_card).
MIXED_BAND = 0.1


def _score(moves: list["AxisMove"]) -> float:
    """Net movement across the axes, each delta in units of that axis's spread among real
    decks (`AXIS_SCALE`), counting only `meaningful` moves.

    It used to divide by the axis's NOISE floor (`max(floor, MIN_SIGNIFICANT)`). Noise says
    whether a move is real, not how much it matters - and Interaction is closed-form with a
    floor of 0, so it was divided by 0.5 and one interaction point outweighed 5.7
    consistency points. A Chaos Warp that gained Interaction +2.6 while costing Consistency
    -7.5 and Speed -2.5 was labelled "positive" (found 2026-10-23). `meaningful` still
    gates on noise; this only weighs what passes the gate.
    """
    return sum(m.delta / AXIS_SCALE.get(m.axis, _DEFAULT_SCALE) for m in moves if m.meaningful)


@dataclass
class AxisMove:
    axis: str
    label: str
    before: float
    after: float
    floor: float
    # The swap split in two against an empty slot (advisor.EMPTY_SLOT), same seeds:
    # `own` = what the added card does in that slot, `cut_value` = what the cut card was
    # doing there. own - cut_value == delta exactly. None when not measured.
    own: float | None = None
    cut_value: float | None = None

    @property
    def delta(self) -> float:
        return self.after - self.before

    def _big(self, value: float | None) -> bool:
        return value is not None and abs(value) >= max(self.floor, MIN_SIGNIFICANT)

    @property
    def own_meaningful(self) -> bool:
        return self._big(self.own)

    @property
    def cut_meaningful(self) -> bool:
        return self._big(self.cut_value)

    @property
    def meaningful(self) -> bool:
        """Big enough to be both REAL and worth saying out loud.

        Two bars, because they answer different questions. `floor` is the axis's own
        seed-to-seed spread — under it, a move is a re-roll of the RNG. `MIN_SIGNIFICANT` is
        a floor on top of that, because determinism only makes a move reproducible, not
        important: Resilience and Interaction have zero sim variance, so a -0.1 counted as a
        finding and produced the headline "costs resilience" off a tenth of a point on a
        0-100 axis. Reproducibly trivial is still trivial.
        """
        return abs(self.delta) >= max(self.floor, MIN_SIGNIFICANT)


@dataclass
class CardImpact:
    card: str
    verdict: str                    # positive | negative | mixed | neutral | illegal
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


def _cut_sentence(cut: Card, supply: dict, targets: dict, lens=None) -> str:
    """Name the slot the card displaced, and say honestly why THAT slot.

    The line this replaced read "the weakest slot it beat", which was never what was
    measured: the pool came from the least-played rule, and least-played is close to the
    OPPOSITE of weakest in a deck someone built on purpose. Now the pool is redundancy, so
    the sentence can be true — but only when there is redundancy to point at.

    A deck that over-supplies nothing has no redundant card, and `rank_redundant` still owes
    its caller `k` of them, so it falls through to its tiebreak. On 9.0% of corpus decks that
    is the whole pool. Claiming redundancy there would be the same over-claim in a new coat,
    so the sentence says what actually happened instead.
    """
    score = redundancy.score_card(cut, supply, targets, lens)
    if score.oversupply > 0 and score.role:
        return (
            f"Measured by swapping it in for {cut.name} — this deck's most over-supplied "
            f"role is {score.role}, by {score.oversupply:.1f} cards' worth."
        )
    return (
        f"Measured by swapping it in for {cut.name}. This deck over-supplies no role "
        f"against what real decks run, so there is no redundant card to displace and that "
        f"slot is the least-played one carrying a role — treat the pairing, not the cut, "
        f"as the finding."
    )


def assess_card(
    resolved: ResolvedDeck,
    card: Card,
    cfg: SimConfig,
    store,
    *,
    cut_pool: int = 3,
    themes: Sequence[str] = (),
    lift: dict[str, float] | None = None,
    lens: CommanderLens | None = None,
) -> CardImpact:
    """Measure what adding `card` does to `resolved`, and say why.

    `themes` are the deck's own detected archetypes, as plain strings — they raise the
    redundancy targets for roles that archetype really plays, so a spellslinger deck is not
    offered its counterspells as the slot to displace. See `redundancy.targets_for`.

    `lift` is a `{card name: EDHREC synergy}` map for this commander (see
    `redundancy.rank_redundant`) — it refines the cut pool's ORDER when nothing is
    over-supplied (S12), so a card's fair pairing is a generic staple rather than the
    deck's own signature piece. Omitting it keeps the pre-existing ordering.
    """
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
    if lens is None:
        # The baseline analysis's lens carries the sim context (X credit), so this agrees
        # with list_deck_cards / Deck Breakdown; the no-context lens is only a fallback.
        lens = getattr(baseline, "lens", None) or build_lens(resolved.commanders)
    supply = redundancy.role_supply(resolved, lens)
    targets = redundancy.targets_for(themes)
    cuts = redundancy.rank_redundant(resolved, max(1, cut_pool), targets=targets, lift=lift, lens=lens)
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
            for ax in PROFILE_AXES  # not the `clock` lens: card verdicts predate it
        ]
        total = _score(moves)
        if best is None or total > best[0]:
            best = (total, cut, moves)

    total, cut, moves = best
    # One more run, for the chosen cut only: the deck with that slot left empty.
    empty = analyze_deck(_swap_variant(resolved, cut, EMPTY_SLOT), cfg, store, run_resilience=True)
    for m in moves:
        e = axis_score(empty, m.axis)
        m.own, m.cut_value = m.after - e, m.before - e
    own_gains = sorted((m for m in moves if m.own_meaningful and m.own > 0), key=lambda m: -m.own)
    cut_costs = sorted((m for m in moves if m.cut_meaningful and m.cut_value > 0),
                       key=lambda m: -m.cut_value)
    # Biggest movers first: the headline names the largest change, and the reasons read in
    # order of significance. Sorting by axis order instead named Consistency +1.9 while
    # Speed +8.3 went unmentioned, which is a true sentence that misses the point.
    gains = sorted((m for m in moves if m.meaningful and m.delta > 0),
                   key=lambda m: -m.delta)
    losses = sorted((m for m in moves if m.meaningful and m.delta < 0),
                    key=lambda m: m.delta)

    if gains and not losses:
        verdict = "positive"
        headline = f"{name} improves this deck (in place of {cut.name})."
    elif losses and not gains:
        verdict = "negative"
        # Say WHICH half lost: a good card into the wrong slot reads very differently from
        # a card that does nothing here.
        headline = (f"{name} adds {own_gains[0].label.lower()}, but {cut.name} is worth more "
                    f"in this deck." if own_gains
                    else f"{name} makes this deck worse in place of {cut.name}.")
    elif gains and losses:
        # A trade-off whose net is a sliver of a typical deck gap is a coin flip, not a
        # verdict: over a 75-case corpus sweep, 12 such cases sat within +/-0.1 and their sign
        # flipped with the weighting rule alone (Path to Exile: +5.3 consistency, +3.3 speed,
        # -6.6 resilience, +1.7 interaction nets -0.015). Say "mixed" and let the axes speak.
        verdict = ("mixed" if abs(total) < MIXED_BAND
                   else "positive" if total > 0 else "negative")
        headline = (f"{name} in place of {cut.name} is a trade-off — it buys "
                    f"{gains[0].label.lower()} and costs {losses[0].label.lower()}.")
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
    # The split. Without it the numbers above read as a property of the card when they are
    # often mostly the cut (Smaug: every removal spell "cost 4.7 consistency" because the cut
    # ramp creature was worth +6.0 of it).
    if own_gains:
        reasons.append("On its own (against an empty slot), " + name + " adds: "
                       + ", ".join(f"{m.label} +{m.own:.1f}" for m in own_gains) + ".")
    else:
        reasons.append(f"On its own (against an empty slot), {name} moves no axis beyond noise: "
                       "the simulation does not see what it does (protection, politics, "
                       "most static effects), or the deck already has it covered.")
    if cut_costs:
        reasons.append(f"{cut.name} was worth: "
                       + ", ".join(f"{m.label} +{m.cut_value:.1f}" for m in cut_costs)
                       + " — that is the price of the slot.")
    if verdict == "neutral":
        flat = ", ".join(f"{m.label} ±{m.floor:.1f}" for m in moves if m.floor > 0)
        reasons.append(
            "Every axis moved less than its own measurement noise, so this is a re-roll "
            f"rather than a change ({flat}). It may still matter for reasons the "
            "simulation does not model — politics, a combo line, or a card you enjoy."
        )
    reasons.append(_cut_sentence(cut, supply, targets, lens))

    wants = commander_wants(resolved.commanders)
    if wants.cheats_creatures and card.is_creature and wants.wants_big:
        reasons.append("Your commander can cheat creatures into play, which favours big bodies.")

    return CardImpact(
        card=name, verdict=verdict, headline=headline, reasons=reasons,
        cut=cut.name, axes=moves,
    )
