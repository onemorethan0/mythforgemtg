"""Agents (docs/SIMULATION.md "Agents (Layer 3)").

`make_agent` maps a config name to an Agent instance; the Tier-2 driver builds one per player so
matchups can pit different agent strengths against each other (the strength ladder, Phase 7).
"""

from __future__ import annotations

from mythgauntlet.agents.base import Agent
from mythgauntlet.agents.greedy import GreedyAgent

__all__ = ["Agent", "GreedyAgent", "make_agent"]


def make_agent(
    name: str, cfg: object | None = None, player: str | None = None, rng: object | None = None
) -> Agent:
    """Build the agent named by `name`. `rng` is a per-game SeededRng sub-stream (used by search
    agents for determinization; ignored by the deterministic GreedyAgent).

    "greedy" -> GreedyAgent. "mcts" -> ISMCTSAgent, sized from the DuelConfig (mcts_iterations,
    rollout_depth, mcts_determinizations); iterations default to 200 when the config leaves it 0.
    """
    key = (name or "greedy").lower()
    if key == "greedy":
        return GreedyAgent()
    if key == "mcts" or key.startswith("mcts:"):
        from mythgauntlet.agents.ismcts import ISMCTSAgent
        from mythgauntlet.sim.rng import SeededRng

        # "mcts:1000" pins the iteration budget inline (the strength ladder pits levels);
        # bare "mcts" falls back to DuelConfig.mcts_iterations, or 200.
        _, _, tail = key.partition(":")
        iters = int(tail) if tail else (getattr(cfg, "mcts_iterations", 0) or 200)
        return ISMCTSAgent(
            iterations=iters,
            rng=rng if isinstance(rng, SeededRng) else SeededRng(0),
            rollout_depth=getattr(cfg, "rollout_depth", 40),
            determinizations=getattr(cfg, "mcts_determinizations", 1),
        )
    raise ValueError(f"unknown agent {name!r}")
