"""Aggregate Tier-0 RunStats into the Consistency/Speed axes (docs/LEARNING.md).

Every number here is a T0 measurement at semantics rung 1 — reports must say so
(invariant #3). The composite score's weights are provisional and documented; they get
re-fit once the labeled reference corpus exists (roadmap Phase 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mythgauntlet.sim.tier0 import RunStats, SimConfig

_SCORE_WEIGHTS = {"keep": 0.25, "lands": 0.35, "curve": 0.30, "dead": 0.10}
_DEAD_CARDS_TOLERANCE = 5.0  # dead cards at horizon before the dead component hits zero


@dataclass
class ConsistencyReport:
    runs: int
    turns: int
    keep_rate: float  # kept the first 7 without mulliganing
    avg_mulligans: float
    avg_kept_hand: float
    land_hit_by_turn: list[float] = field(default_factory=list)  # index 0 = turn 1
    avg_sources_by_turn: list[float] = field(default_factory=list)
    avg_mana_available_by_turn: list[float] = field(default_factory=list)
    avg_mana_spent_by_turn: list[float] = field(default_factory=list)
    curve_efficiency: float = 0.0  # cumulative spent / available over the horizon
    commander_cast_rate: float = 0.0
    avg_commander_turn: float | None = None
    avg_spells_cast: float = 0.0
    avg_cards_drawn: float = 0.0
    avg_dead_cards: float = 0.0
    consistency_score: float = 0.0  # 0-100 composite (provisional weights)
    # Speed axis (goldfish clock vs cfg.goldfish_life, combat damage only — see tier0 caveats)
    goldfish_kill_rate: float = 0.0  # fraction of games that got there within the horizon
    avg_kill_turn: float | None = None
    avg_damage_by_turn: list[float] = field(default_factory=list)


def game_changer_bracket_hint(count: int) -> str:
    """Official bracket gate implication of a deck's Game Changers count."""
    if count == 0:
        return "Brackets 1-2 eligible (0 Game Changers)"
    if count <= 3:
        return f"Bracket 3+ ({count} Game Changers, <=3 allowed in Bracket 3)"
    return f"Bracket 4-5 ({count} Game Changers)"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _per_turn_mean(runs: list[RunStats], attr: str, turns: int) -> list[float]:
    out = []
    for t in range(turns):
        vals = [getattr(r, attr)[t] for r in runs if len(getattr(r, attr)) > t]
        out.append(_mean([float(v) for v in vals]))
    return out


def compute(runs: list[RunStats], cfg: SimConfig) -> ConsistencyReport:
    n = len(runs)
    turns = cfg.turns

    land_hit = _per_turn_mean(runs, "land_drops", turns)
    available = _per_turn_mean(runs, "mana_available_by_turn", turns)
    spent = _per_turn_mean(runs, "mana_spent_by_turn", turns)

    total_available = sum(available)
    curve_efficiency = (sum(spent) / total_available) if total_available else 0.0

    commander_turns = [r.commander_turn for r in runs if r.commander_turn is not None]
    kill_turns = [r.kill_turn for r in runs if r.kill_turn is not None]
    avg_dead = _mean([float(r.dead_cards) for r in runs])

    early = min(4, turns)
    components = {
        "keep": _mean([1.0 if r.mulligans == 0 else 0.0 for r in runs]),
        "lands": _mean(land_hit[:early]),
        "curve": min(1.0, curve_efficiency),
        "dead": max(0.0, 1.0 - avg_dead / _DEAD_CARDS_TOLERANCE),
    }
    score = 100.0 * sum(_SCORE_WEIGHTS[k] * v for k, v in components.items())

    return ConsistencyReport(
        runs=n,
        turns=turns,
        keep_rate=components["keep"],
        avg_mulligans=_mean([float(r.mulligans) for r in runs]),
        avg_kept_hand=_mean([float(r.kept_hand_size) for r in runs]),
        land_hit_by_turn=land_hit,
        avg_sources_by_turn=_per_turn_mean(runs, "sources_by_turn", turns),
        avg_mana_available_by_turn=available,
        avg_mana_spent_by_turn=spent,
        curve_efficiency=curve_efficiency,
        commander_cast_rate=len(commander_turns) / n if n else 0.0,
        avg_commander_turn=_mean([float(t) for t in commander_turns]) if commander_turns else None,
        avg_spells_cast=_mean([float(r.spells_cast) for r in runs]),
        avg_cards_drawn=_mean([float(r.cards_drawn) for r in runs]),
        avg_dead_cards=avg_dead,
        consistency_score=score,
        goldfish_kill_rate=len(kill_turns) / n if n else 0.0,
        avg_kill_turn=_mean([float(t) for t in kill_turns]) if kill_turns else None,
        avg_damage_by_turn=_per_turn_mean(runs, "damage_by_turn", turns),
    )
