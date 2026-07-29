"""Agent strength ladder (docs/SIMULATION.md, Phase 7).

Pits agent levels head-to-head on a fixed matchup (a deck mirror by default) to verify the search
ladder is MONOTONE: more search beats less, and MCTS beats the greedy baseline. Ratings are
measured *at* an agent level (docs/LEARNING.md), so this is the check that an agent upgrade is a
real improvement before the gauntlet is re-based under it.

Fairness: within each duel the first player alternates game-by-game (tier2.duel_prepared), so on
a mirror the only asymmetry is agent skill. Deterministic given the seed (invariant #1).
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.sim.tier2 import DuelConfig, PreparedDeck, duel_prepared


@dataclass(frozen=True)
class LadderMatch:
    strong: str  # the stronger agent level (played side a)
    weak: str
    strong_wins: int
    weak_wins: int
    draws: int
    games: int

    @property
    def strong_winrate(self) -> float:
        return self.strong_wins / self.games if self.games else 0.0


def run_ladder(
    a: PreparedDeck, b: PreparedDeck, levels: list[str], games: int, seed: int,
    max_turns: int = 25, rollout_depth: int = 14,
) -> list[LadderMatch]:
    """Round-robin `levels` (ordered weakest -> strongest) on the a-vs-b matchup. For each pair the
    stronger level plays side a, the weaker side b. Deterministic given the seed."""
    matches: list[LadderMatch] = []
    for i in range(len(levels)):
        for j in range(i + 1, len(levels)):
            weak, strong = levels[i], levels[j]
            cfg = DuelConfig(
                games=games, seed=seed, max_turns=max_turns,
                agent_a=strong, agent_b=weak, rollout_depth=rollout_depth,
            )
            r = duel_prepared(a, b, cfg)
            matches.append(LadderMatch(strong, weak, r.wins_a, r.wins_b, r.draws, r.games))
    return matches


def is_monotone(matches: list[LadderMatch], threshold: float = 0.55) -> bool:
    """True iff every stronger level beat every weaker level with win rate >= threshold."""
    return all(m.strong_winrate >= threshold for m in matches)
