"""Agent protocol (docs/SIMULATION.md "Agents (Layer 3)").

An agent is queried at each decision point of the Tier-2 state machine (sim/game.py) and returns
one legal action. Agent strength is part of the measurement instrument: ratings are always
reported *at* an agent level, and the gauntlet is re-based when the agent changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Agent(Protocol):
    """Chooses one action for `state.pending`. Must not mutate `state`."""

    name: str

    def decide(self, state) -> object:
        ...
