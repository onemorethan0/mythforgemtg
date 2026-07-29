"""Go-wide / overrun alpha-strike estimator (docs/SIMULATION.md; feeds the Ceiling axis).

A best-case NUT-DRAW model, the sibling of sim/storm.py. The T0 combat clock sees a board swing at
its *current* power; it can't see that a one-shot team pump (Overrun / Craterhoof / End-Raze) turns
a wide board of small creatures into a lethal alpha strike in a single turn. Given the deck's
overrun finisher + the T0 nut go-wide board (RunStats.final_board_power / final_board_creatures),
this asks "does the best draw kill in one swing" -- exactly the Ceiling axis's question.

Deterministic, offline, no RNG. It only fires with BOTH a real one-shot finisher AND a wide board
(>= _MIN_WIDTH creatures), so a fair midrange deck (no finisher, or a narrow board) never trips it.
Simplifications: assumes the finisher grants the evasion to connect (best-case ceiling), ignores
opponents/blockers/interaction, and reads a single representative nut board rather than replaying
the pump turn move-by-move.
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import tags

_LETHAL = 40       # one goldfish opponent
_MIN_WIDTH = 3     # a one-shot pump on 1-2 creatures is not an alpha strike
_SCALE_CAP = 12    # nut-draw cap on the scaling pump's X (a Craterhoof X beyond this is overkill)


@dataclass(frozen=True)
class OverrunReport:
    can_alpha_strike: bool
    alpha_damage: int      # best-case one-swing damage with the finisher online
    nut_creatures: int     # go-wide board width used
    has_finisher: bool


def _best_finisher(cards: list[tuple[Card, int]]) -> tuple[int, bool]:
    """The deck's strongest one-shot team pump: (flat_pump, scales_with_board)."""
    flat = 0
    scales = False
    for card, _count in cards:
        fx = tags.analyze(card)
        if fx.overrun_scales:
            scales = True
        flat = max(flat, fx.overrun_pump)
    return flat, scales


def alpha_strike_damage(flat: int, scales: bool, board_power: int, board_creatures: int) -> int:
    """One-swing damage: base board power + the pump applied to every attacker. A scaling pump
    (Craterhoof: +X/+X, X = creatures you control) adds creatures^2; a flat adds creatures*N."""
    if board_creatures <= 0 or not (flat or scales):
        return board_power
    per_creature = min(board_creatures, _SCALE_CAP) if scales else flat
    return board_power + board_creatures * per_creature


def estimate_overrun(
    cards: list[tuple[Card, int]], board_power: int, board_creatures: int
) -> OverrunReport:
    """Does the nut go-wide board kill in one swing once the overrun finisher fires? `board_power`
    and `board_creatures` are the T0 nut board (a high percentile of the goldfish distribution)."""
    flat, scales = _best_finisher(cards)
    has_finisher = bool(flat or scales)
    dmg = alpha_strike_damage(flat, scales, board_power, board_creatures)
    can = has_finisher and board_creatures >= _MIN_WIDTH and dmg >= _LETHAL
    return OverrunReport(can, dmg, board_creatures, has_finisher)
