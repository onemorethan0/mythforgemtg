"""ISMCTS tree + UCB selection (docs/SIMULATION.md, Phase 7).

Pure data structure and math — no engine coupling, no randomness of its own (a `rand` callable is
passed in). Children are keyed by a hashable action key (sim/game.action_key), so the same choice
is poolable across the different determinizations an ISMCTS iteration samples.

UCB follows the ISMCTS variant (Cowling et al. 2012): the exploration term uses each child's
*availability* count (how many selections it was legal for), not the parent's visit count, since
an action isn't legal in every determinization.
"""

from __future__ import annotations

from math import log, sqrt
from typing import Any


class Node:
    """One ISMCTS tree node. `children` maps an action key to a child Node."""

    __slots__ = ("children", "visits", "reward_sum", "avail")

    def __init__(self) -> None:
        self.children: dict[Any, Node] = {}
        self.visits: int = 0           # n: times on a backprop path
        self.reward_sum: float = 0.0   # W: summed rewards, root player's perspective
        self.avail: int = 0            # times this node's action was legal at a selection

    def mean(self) -> float:
        return self.reward_sum / self.visits if self.visits else 0.0


def select(node: Node, legal_keys, exploration: float, rand) -> Any:
    """ISMCTS UCB1 selection among children whose key is in `legal_keys` (all must already exist).

    Increments availability for every legal child, prefers any unvisited child, else returns the
    key maximizing mean + exploration*sqrt(ln(avail)/visits). Ties broken uniformly via `rand`.
    """
    children = node.children
    for key in legal_keys:
        children[key].avail += 1

    unvisited = [key for key in legal_keys if children[key].visits == 0]
    if unvisited:
        return unvisited[int(rand() * len(unvisited))]

    def score(key):
        child = children[key]
        return child.mean() + exploration * sqrt(log(child.avail) / child.visits)

    scores = [(score(k), k) for k in legal_keys]
    best_score = max(s for s, _ in scores)
    candidates = [k for s, k in scores if abs(s - best_score) < 1e-12]
    return candidates[int(rand() * len(candidates))]


def backprop(path: list[Node], reward: float) -> None:
    """Add one simulation's reward to every node on the descent path."""
    for node in path:
        node.visits += 1
        node.reward_sum += reward


def best_child_key(node: Node) -> Any:
    """The robust final choice: the child key with the most visits (insertion order breaks ties)."""
    return max(node.children.items(), key=lambda item: item[1].visits)[0]
