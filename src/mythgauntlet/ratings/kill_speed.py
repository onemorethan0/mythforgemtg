"""Kill speed as a range, against one player and against the table (B32,
docs/SPEC_deck_scouting_report.md).

One player: from the goldfish runs (after apply_nut_kills, the same runs `avg_kill_turn` reads),
the kill turn's p25 / median / p75 over the games that kill, and the share of ALL games that
have killed by turn 6, 8 and 10. Goldfish means nobody blocks, answers or races, so every figure
is labelled "unopposed".

The table: the measured four-seat result (ratings/pod.py), not a capacity estimate. A pod win
is last player standing; a turn-cap adjudication is a win but not a kill, so it is counted
apart and the win-round figures cover kills alone. Its field is named in the wording ("against
a Bracket 3 field of 176 corpus decks"), and the goldfish capacity (`pod_close_turn`, the turn
cumulative damage reaches table-lethal) stays as the secondary "if unopposed" figure.

Wording rule: every figure says against what, and a deck with no kill reports "no kill in N
games", never a turn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

BY_TURNS = (6, 8, 10)
Z90 = 1.6448536269514722   # two-sided 90%, the same confidence the B30 card intervals use


def quantile(xs: list[int] | tuple[int, ...], q: float) -> float | None:
    """Linear-interpolated quantile of a sample (numpy's default method); None when empty."""
    xs = sorted(xs)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return float(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))


def wilson(k: int, n: int, z: float = Z90) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


@dataclass(frozen=True)
class KillSpeed:
    """One opponent, unopposed (goldfish)."""
    games: int
    horizon: int                     # turns simulated; "no kill" means none by this turn
    killing_games: int
    kill_rate: float
    mean: float | None               # == report.avg_kill_turn (same runs, same filter)
    p25: float | None
    median: float | None
    p75: float | None
    by_turn: dict[int, float]        # share of ALL games killed by turn T (T <= horizon)
    text: str


def compute(runs, horizon: int) -> KillSpeed:
    turns = [r.kill_turn for r in runs if r.kill_turn is not None]
    n = len(runs)
    k = len(turns)
    ks = dict(
        games=n, horizon=horizon, killing_games=k,
        kill_rate=round(k / n, 3) if n else 0.0,
        mean=(sum(turns) / k) if k else None,
        p25=quantile(turns, 0.25), median=quantile(turns, 0.5), p75=quantile(turns, 0.75),
        by_turn={t: round(sum(1 for x in turns if x <= t) / n, 3) for t in BY_TURNS
                 if t <= horizon} if n else {},
    )
    return KillSpeed(**ks, text=describe_one(**ks))


def _num(x: float) -> str:
    return f"{x:.0f}" if float(x).is_integer() else f"{x:.1f}"


def _t(x: float) -> str:
    return "T" + _num(x)


def describe_one(*, games, horizon, killing_games, kill_rate, median, p25, p75, by_turn,
                 **_ignored) -> str:
    if killing_games == 0:
        return f"Unopposed: no kill in {games} games ({horizon}-turn horizon)."
    out = (f"Unopposed, it kills one player in {kill_rate:.0%} of {games} games: median "
           f"{_t(median)}")
    if p25 != p75:
        out += f", middle half {_t(p25)}-{_t(p75)}"
    out += "."
    if by_turn:
        out += " By " + ", ".join(f"T{t}: {s:.0%}" for t, s in by_turn.items()) + "."
    return out


@dataclass(frozen=True)
class TableSpeed:
    """The table: a measured pod, plus the goldfish capacity as the "if unopposed" figure."""
    games: int
    pod_size: int
    field: str                       # e.g. "a Bracket 3 field of 176 corpus decks"
    wins: int
    winrate: float
    winrate_ci90: tuple[float, float]
    baseline: float                  # 1 / pod_size
    kill_wins: int                   # last player standing
    adjudicated_wins: int            # won on the turn cap: a win, not a kill
    win_round_p25: float | None
    win_round_median: float | None
    win_round_p75: float | None
    capacity_turn: float | None      # goldfish pod_close_turn, unopposed
    capacity_rate: float             # goldfish pod_close_rate
    text: str


def table(pod, field: str, capacity_turn: float | None, capacity_rate: float) -> TableSpeed:
    rounds = list(pod.win_rounds)
    ts = dict(
        games=pod.games, pod_size=pod.pod_size, field=field, wins=pod.wins,
        winrate=round(pod.winrate, 3),
        winrate_ci90=tuple(round(x, 3) for x in wilson(pod.wins, pod.games)),
        baseline=round(pod.baseline, 3),
        kill_wins=pod.kill_wins, adjudicated_wins=pod.adjudicated_wins,
        win_round_p25=quantile(rounds, 0.25), win_round_median=quantile(rounds, 0.5),
        win_round_p75=quantile(rounds, 0.75),
        capacity_turn=capacity_turn, capacity_rate=capacity_rate,
    )
    return TableSpeed(**ts, text=describe_table(**ts))


def describe_table(*, games, pod_size, field, wins, winrate, winrate_ci90, baseline, kill_wins,
                   adjudicated_wins, win_round_median, win_round_p25, win_round_p75,
                   capacity_turn, capacity_rate, **_ignored) -> str:
    lo, hi = winrate_ci90
    out = (f"Against {field}, it wins {wins} of {games} {pod_size}-player games ({winrate:.0%}, "
           f"90% interval {lo:.0%}-{hi:.0%}; an even seat is {baseline:.0%}).")
    if kill_wins:
        # "Last player standing", not "eliminated the table": another seat may have done some
        # of the eliminating. Quartiles of a round count read as whole rounds.
        out += f" When it is the last player standing: median round {_num(win_round_median)}"
        lo_r, hi_r = math.floor(win_round_p25 + 0.5), math.floor(win_round_p75 + 0.5)
        if lo_r != hi_r:
            out += f" (middle half {lo_r}-{hi_r})"
        out += f", over {kill_wins} games."
    elif wins:
        out += " None of those wins was by being the last player standing."
    if adjudicated_wins:
        out += f" {adjudicated_wins} of its wins came on the turn cap, not by a kill."
    if capacity_turn is not None:
        out += (f" Unopposed, its damage reaches table-lethal by ~T{capacity_turn:.0f} in "
                f"{capacity_rate:.0%} of goldfish games.")
    else:
        out += " Unopposed, its damage never reaches table-lethal in the goldfish games."
    return out
