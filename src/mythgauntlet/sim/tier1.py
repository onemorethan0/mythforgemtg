"""Tier-1 scripted pressure: the Resilience axis (docs/SIMULATION.md).

The vision's flagship differentiator — "does the deck fold to a board wipe?" — which no
static calculator can answer because it is an emergent property of playing the deck.

Method: paired simulation. Run the T0 goldfish sim twice at the SAME seeds, once clean and
once with a board wipe injected at turn W. Because run i draws from the same stream in both
passes, the two are a matched pair and per-run differencing cancels shuffle variance. The
Resilience score is how much of the deck's board+mana development survives and rebuilds
after the wipe.

MVP scope (documented, honest): one disruption class (board wipe). Targeted removal and
counter pressure are the next disruption classes (SIMULATION.md). The wipe models
"destroy all creatures" — see sim/tier0._run_one for exactly what it resets.
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.sim.tier0 import RunStats, SimConfig, simulate


def default_wipe_turn(turns: int) -> int:
    """A representative board-wipe turn (2-5), clamped to the horizon so it always fires.

    Shared by the CLI and API so both surfaces test the same wipe; without the horizon
    clamp a turns=1 sim would 'wipe' at turn 2 (never reached) and report a false 100.
    """
    return min(turns, min(5, max(2, turns - 1)))


@dataclass
class ResilienceReport:
    runs: int
    wipe_turn: int
    clean_kill_rate: float
    wiped_kill_rate: float
    clean_avg_kill_turn: float | None
    wiped_avg_kill_turn: float | None
    # per-run retained output = wiped(board+mana at horizon) / clean(board+mana), capped 1
    resilience_score: float  # 0-100: 100 = shrugs the wipe off, 0 = never recovers
    kill_delay_turns: float | None  # extra turns to kill after a wipe (None if no clean kills)


def _final_output(run: RunStats) -> float:
    mana = run.mana_available_by_turn[-1] if run.mana_available_by_turn else 0
    return float(run.final_board_power + mana)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_resilience(
    cards: list[tuple[Card, int]], commander: Card | None, cfg: SimConfig, wipe_turn: int
) -> ResilienceReport:
    clean = simulate(cards, commander, cfg)
    wiped = simulate(cards, commander, cfg, board_wipe_turn=wipe_turn)

    retained = []
    for c, w in zip(clean, wiped, strict=True):
        base = _final_output(c)
        if base <= 0:  # deck presents nothing even unopposed — resilience is undefined
            continue
        retained.append(min(1.0, _final_output(w) / base))
    score = 100.0 * _mean(retained) if retained else 0.0

    clean_kills = [r.kill_turn for r in clean if r.kill_turn is not None]
    wiped_kills = [r.kill_turn for r in wiped if r.kill_turn is not None]
    clean_avg = _mean([float(t) for t in clean_kills]) if clean_kills else None
    wiped_avg = _mean([float(t) for t in wiped_kills]) if wiped_kills else None
    delay = (wiped_avg - clean_avg) if (clean_avg is not None and wiped_avg is not None) else None

    n = len(clean)
    return ResilienceReport(
        runs=n,
        wipe_turn=wipe_turn,
        clean_kill_rate=len(clean_kills) / n if n else 0.0,
        wiped_kill_rate=len(wiped_kills) / n if n else 0.0,
        clean_avg_kill_turn=clean_avg,
        wiped_avg_kill_turn=wiped_avg,
        resilience_score=score,
        kill_delay_turns=delay,
    )
