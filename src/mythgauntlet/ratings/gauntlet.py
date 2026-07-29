"""Gauntlet ratings: pairwise duel results -> Bradley-Terry strengths (docs/LEARNING.md).

Bradley-Terry models P(i beats j) = w_i / (w_i + w_j). We fit by the classic
minorization-maximization iteration, with one virtual draw against a fixed w=1 opponent
per deck as regularization (keeps undefeated/winless decks finite — the standard trick).
Draws count half a win each. Ratings are reported on an Elo-like scale
(1500 + 400*log10(w)) purely for readability.

A rating is a measurement BY an instrument: results carry the engine config with them,
and ratings from different engine/agent versions must never be mixed (docs/LEARNING.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mythgauntlet.sim.rng import SeededRng

ELO_BASE = 1500.0
ELO_SCALE = 400.0


@dataclass(frozen=True)
class PairResult:
    a: str
    b: str
    wins_a: int
    wins_b: int
    draws: int = 0


def sample_pairs(names: list[str], opponents_each: int, seed: int) -> list[tuple[str, str]]:
    """Deterministic sparse matchup schedule: ~opponents_each distinct foes per deck."""
    rng = SeededRng(seed)
    pairs: set[tuple[str, str]] = set()
    n = len(names)
    if n < 2:
        return []
    for i, name in enumerate(names):
        others = names[:i] + names[i + 1 :]
        for _ in range(min(opponents_each, n - 1) * 2):  # oversample; dedupe below
            opponent = rng.choice(others)
            pair = (name, opponent) if name < opponent else (opponent, name)
            pairs.add(pair)
            if sum(1 for p in pairs if name in p) >= opponents_each:
                break
    return sorted(pairs)


def fit_bradley_terry(
    results: list[PairResult], iterations: int = 500, tolerance: float = 1e-10
) -> dict[str, float]:
    """MM fit -> {deck name: Elo-like rating}. Deterministic."""
    names = sorted({r.a for r in results} | {r.b for r in results})
    if not names:
        return {}
    index = {name: i for i, name in enumerate(names)}
    n = len(names)

    # score[i] = total "wins" incl. half-draws + the regularizing virtual half-win
    score = [0.5] * n  # virtual draw vs w=1: half a win...
    virtual_games = [1.0] * n  # ...over one game
    matches: dict[tuple[int, int], float] = {}  # games between real pairs
    for r in results:
        i, j = index[r.a], index[r.b]
        games = r.wins_a + r.wins_b + r.draws
        if games == 0:
            continue
        score[i] += r.wins_a + 0.5 * r.draws
        score[j] += r.wins_b + 0.5 * r.draws
        key = (min(i, j), max(i, j))
        matches[key] = matches.get(key, 0.0) + games

    w = [1.0] * n
    for _ in range(iterations):
        denom = [virtual_games[i] / (w[i] + 1.0) for i in range(n)]
        for (i, j), games in matches.items():
            shared = games / (w[i] + w[j])
            denom[i] += shared
            denom[j] += shared
        new_w = [score[i] / denom[i] if denom[i] > 0 else w[i] for i in range(n)]
        log_mean = sum(math.log(x) for x in new_w) / n  # normalize: geometric mean 1
        new_w = [math.exp(math.log(x) - log_mean) for x in new_w]
        delta = max(abs(new_w[i] - w[i]) for i in range(n))
        w = new_w
        if delta < tolerance:
            break

    return {name: ELO_BASE + ELO_SCALE * math.log10(w[index[name]]) for name in names}
