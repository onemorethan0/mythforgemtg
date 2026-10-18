"""Aggregate Tier-0 RunStats into the Consistency/Speed axes (docs/LEARNING.md).

Every number here is a T0 measurement at semantics rung 1 — reports must say so
(invariant #3).

CONSISTENCY = THE SHARE OF GAMES THAT GO SMOOTHLY (re-modelled 2026-10-18). A game is smooth
when all three of these hold in that run:
  * mana on track -- 4 mana sources by turn 4 (lands + ramp) OR every land drop turns 1-3;
  * the deck has plays -- it spends >= 60% of the mana it has over turns 2-6 (low use is
    flood, a hand of uncastables, or colour screw: `_can_pay` matches pips exactly);
  * the commander lands on time -- cast by turn max(MV, 2) + 1 (one turn of slack; a deck
    without a commander in the sim skips this check).
The score is 100 x that rate. It used to be a weighted mean of four per-deck averages
(keep 0.25, lands 0.35, curve 0.30, dead 0.10), which over the 619 labelled corpus decks gave
p10/p50/p90 = 71/79/82 and 91% of decks >= 70 ("consistent"). Measured why: the two heaviest
components barely move -- land drops hit turns 1-4 ~0.9 on every deck and "no mulligan" ~0.8
(and it counted the FREE first mulligan as a failure) -- so ~51 of every deck's points were a
constant, and averaging soft components across runs hid the bad games a player remembers.
Counting games that pass every check keeps those failures visible: p10/p50/p90 = 45/74/88; by
label B1 68 / B2 77 / B3 78 / B4 73 / B5 55. B5 sits low because T0 sees a cEDH deck's low
land count but not most of its fast mana or any tutors -- the same T0 ceiling the old score
had (B5 69 there). Bands (ratings/insight.py) re-cut to consistent >= 80 (37.2% of decks) /
shaky < 45 (9.5%). A pass/fail rate is noisier than a mean of averages -- seed-to-seed noise
2.83 at runs=150, was 0.92 -- but the spread grew more (p10-p90 43 points, was 11), so signal
to noise rose from ~12x to ~15x. Dead cards at the horizon are deliberately NOT a check: at
turn 12 they read flood and clunky top-end as the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mythgauntlet.sim.tier0 import RunStats, SimConfig

# Smooth-game checks (see module docstring). Each is a per-run pass/fail.
_ON_TRACK_TURN = 4  # mana on track: this many sources by this turn ...
_EARLY_LAND_TURNS = 3  # ... or every land drop through this turn
_PLAYS_TURNS = (2, 6)  # inclusive turn span the mana-use check reads
_PLAYS_MIN_USE = 0.6  # share of available mana spent over that span
_COMMANDER_SLACK = 1  # turns past max(MV, 2) the commander may land and still be "on time"


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
    consistency_score: float = 0.0  # 0-100: share of smooth games (see module docstring)
    smooth_game_rate: float = 0.0  # games passing all three checks below
    mana_on_track_rate: float = 0.0
    has_plays_rate: float = 0.0
    commander_on_time_rate: float | None = None  # None when the sim has no commander
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


def _mana_on_track(run: RunStats) -> bool:
    sources = run.sources_by_turn
    if len(sources) >= _ON_TRACK_TURN and sources[_ON_TRACK_TURN - 1] >= _ON_TRACK_TURN:
        return True
    early = run.land_drops[:_EARLY_LAND_TURNS]
    return len(early) == _EARLY_LAND_TURNS and all(early)


def _has_plays(run: RunStats) -> bool:
    first, last = _PLAYS_TURNS
    available = sum(run.mana_available_by_turn[first - 1:last])
    if available <= 0:
        return False
    return sum(run.mana_spent_by_turn[first - 1:last]) / available >= _PLAYS_MIN_USE


def _commander_on_time(run: RunStats, commander_mv: int) -> bool:
    return run.commander_turn is not None and (
        run.commander_turn <= max(commander_mv, 2) + _COMMANDER_SLACK)


def compute(
    runs: list[RunStats], cfg: SimConfig, commander_mv: int | None = None,
) -> ConsistencyReport:
    """`commander_mv` is the LEAD commander's mana value, the one the sim casts from the
    command zone. None skips the on-time check (no commander in the sim, or a caller that
    does not know it) rather than guessing."""
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

    on_track = [_mana_on_track(r) for r in runs]
    plays = [_has_plays(r) for r in runs]
    on_time = [_commander_on_time(r, commander_mv) for r in runs] if commander_mv is not None else None
    smooth = [
        a and b and (on_time[i] if on_time is not None else True)
        for i, (a, b) in enumerate(zip(on_track, plays))
    ]
    smooth_rate = _mean([1.0 if s else 0.0 for s in smooth])
    score = 100.0 * smooth_rate

    return ConsistencyReport(
        runs=n,
        turns=turns,
        keep_rate=_mean([1.0 if r.mulligans == 0 else 0.0 for r in runs]),
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
        smooth_game_rate=smooth_rate,
        mana_on_track_rate=_mean([1.0 if x else 0.0 for x in on_track]),
        has_plays_rate=_mean([1.0 if x else 0.0 for x in plays]),
        commander_on_time_rate=(
            _mean([1.0 if x else 0.0 for x in on_time]) if on_time is not None else None),
        goldfish_kill_rate=len(kill_turns) / n if n else 0.0,
        avg_kill_turn=_mean([float(t) for t in kill_turns]) if kill_turns else None,
        avg_damage_by_turn=_per_turn_mean(runs, "damage_by_turn", turns),
    )
