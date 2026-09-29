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

import hashlib
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


def pair_hash(a: str, b: str, seed: int) -> int:
    """Order-independent, position-independent 32-bit hash of a matchup.

    Both the schedule and each job's game seed derive from this rather than from a deck's index
    in the sorted name list, so adding decks to the corpus (the nightly fetch does) leaves every
    existing matchup, its seed and therefore its `--cache` entry untouched."""
    lo, hi = (a, b) if a < b else (b, a)
    digest = hashlib.sha1(f"{seed}|{lo}|{hi}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _nomination_hash(deck: str, foe: str, seed: int) -> int:
    # directional (unlike pair_hash) so the two sides' nominations are independent draws
    return int.from_bytes(hashlib.sha1(f"{seed}>{deck}>{foe}".encode("utf-8")).digest()[:4], "big")


def sample_pairs(names: list[str], opponents_each: int, seed: int) -> list[tuple[str, str]]:
    """Deterministic sparse matchup schedule of ~`opponents_each` foes per deck on average.

    Each deck nominates its ceil(k/2) lowest-hash foes and a pair plays if EITHER side
    nominated it, so the average degree is ~k (same cost as the old schedule) and every deck
    faces at least ceil(k/2).

    Stable under corpus growth: a new deck only displaces an existing deck's foes with
    probability ~k/n, unlike drawing from a positional RNG stream, which reshuffled the whole
    schedule (and every seed) whenever one deck was added."""
    n = len(names)
    if n < 2:
        return []
    k = min(max(1, -(-opponents_each // 2)), n - 1)
    pairs: set[tuple[str, str]] = set()
    for name in names:
        foes = sorted((o for o in names if o != name), key=lambda o: (_nomination_hash(name, o, seed), o))
        for opponent in foes[:k]:
            pairs.add((name, opponent) if name < opponent else (opponent, name))
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
