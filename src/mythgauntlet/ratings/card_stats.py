"""Per-card evidence from the goldfish games (B30, docs/SPEC_deck_scouting_report.md).

tier0 already draws and casts every card hundreds of times per analysis and used to throw the
detail away; the report could say "0.57 dead cards a game" but not which card. `RunStats`
now records, per card name, the turn it was first seen in hand and first played. This module
turns that into figures a report can name a card on:

  drawn          games in which the card was seen at all (the sample size)
  cast_rate      played / seen                      (lands: dropped / seen)
  avg_cast_turn  mean first-play turn, over the games it was played
  stranded_rate  seen but never played, over the horizon (the "dead card")
  early_uplift   mean kill turn when NOT seen by `early_turn`, minus mean kill turn when it
                 was. Positive = the deck kills sooner when this card shows up early.

Why the uplift is a fair comparison: which cards a game sees early is decided by the shuffle,
so "seen early" vs "not" is close to a randomised split. Two known biases, both stated in the
report rather than corrected silently: the mulligan keeps hands by land count (so lands and
cheap spells are conditioned on), and a draw engine makes every OTHER card more likely to be
seen early (so draw engines' partners inherit a little of their uplift).

A game with no kill inside the horizon counts as kill turn `turns + 1`. That is a floor, not a
measurement, so for a deck that often fails to kill the uplift is a lower bound; the count of
such games is reported (`no_kill_games`) beside every figure.

The interval is a normal-approximation 90% interval on the difference of two means (Welch),
not the bootstrap the spec first named: a per-card bootstrap over 70 cards x 300 runs costs
seconds per analysis for the same answer at these sample sizes. It is only reported where both
groups hold at least `min_group` games; below that the uplift is None, never a guess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARLY_TURN = 3      # "seen early" = in the kept opening hand or drawn by turn 3
MIN_GROUP = 30      # each side of the split needs this many games for an uplift
Z90 = 1.6449


@dataclass(frozen=True)
class CardStat:
    name: str
    is_land: bool
    drawn: int                    # games in which the card was seen
    cast_rate: float
    avg_cast_turn: float | None
    stranded_rate: float
    early_uplift: float | None    # turns faster when seen early (None: sample too small)
    uplift_ci: tuple[float, float] | None
    n_early: int
    n_late: int


def _mean_var(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1) if n > 1 else 0.0
    return m, v


def compute(runs, turns: int, land_names: set[str] | frozenset[str] = frozenset(),
            early_turn: int = EARLY_TURN, min_group: int = MIN_GROUP) -> list[CardStat]:
    """`runs` are tier0 RunStats AFTER apply_nut_kills (so kill turns include storm/overrun
    kills). `land_names` marks lands, whose 'stranded' means 'never dropped'."""
    kill = [r.kill_turn if r.kill_turn is not None else turns + 1 for r in runs]
    names = sorted({n for r in runs for n in r.seen_turn})
    out: list[CardStat] = []
    for name in names:
        seen = played = 0
        cast_turns: list[int] = []
        early: list[float] = []
        late: list[float] = []
        for r, k in zip(runs, kill):
            t = r.seen_turn.get(name)
            if t is not None:
                seen += 1
                p = r.played_turn.get(name)
                if p is not None:
                    played += 1
                    cast_turns.append(p)
            (early if t is not None and t <= early_turn else late).append(k)
        uplift = ci = None
        if len(early) >= min_group and len(late) >= min_group:
            me, ve = _mean_var(early)
            ml, vl = _mean_var(late)
            uplift = ml - me
            se = math.sqrt(ve / len(early) + vl / len(late))
            ci = (round(uplift - Z90 * se, 2), round(uplift + Z90 * se, 2))
            uplift = round(uplift, 2)
        out.append(CardStat(
            name=name, is_land=name in land_names, drawn=seen,
            cast_rate=round(played / seen, 3) if seen else 0.0,
            avg_cast_turn=round(sum(cast_turns) / len(cast_turns), 2) if cast_turns else None,
            stranded_rate=round((seen - played) / seen, 3) if seen else 0.0,
            early_uplift=uplift, uplift_ci=ci, n_early=len(early), n_late=len(late)))
    out.sort(key=lambda c: (c.early_uplift is None, -(c.early_uplift or 0.0), c.name))
    return out


def significant(stat: CardStat) -> bool:
    """The interval excludes zero: the only uplift a report may name a card on."""
    return stat.uplift_ci is not None and (stat.uplift_ci[0] > 0 or stat.uplift_ci[1] < 0)
