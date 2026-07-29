"""ISMCTSAgent — Information Set Monte Carlo Tree Search with determinization (Phase 7).

Single-observer ISMCTS (Cowling/Ward): each iteration samples one concrete world consistent with
what the deciding player can see (sim/game.determinize), then runs one MCTS
selection->expansion->rollout->backprop over a tree that branches ONLY on the root player's own
decisions. Whenever it is the opponent's decision (during selection or rollout), the fixed
rollout policy (GreedyAgent) acts -- a standard, honest MVP: the search plans the root player's
line against a greedy opponent. Rollouts are truncated at `rollout_depth` decisions and evaluated
with the adjudication-score differential (sim/game.score_reward).

This is what lets the agent make the planning decisions the greedy value function cannot:
deliberately holding mana up for a counter/removal (Phase-6 note; docs/SIMULATION.md), and — now
that reactions are searched decisions (COUNTER_WINDOW / INSTANT_WINDOW, 2026-07-21) — choosing
whether to actually spend a counter/removal or hold it, including countering a spell the greedy
value gate would let resolve. Those windows are ordinary decision nodes here: when it is the root
player's reaction, search branches on it; otherwise the greedy rollout policy reacts.

Determinism (invariant #1): all sampling comes from the per-game SeededRng sub-stream handed to
the agent; same seed => same play.
"""

from __future__ import annotations

from mythgauntlet.agents.greedy import GreedyAgent
from mythgauntlet.agents.mcts_tree import Node, backprop, best_child_key, select
from mythgauntlet.sim.game import (
    action_key,
    advance,
    apply,
    determinize,
    legal_actions,
    score_reward,
    terminal_reward,
)
from mythgauntlet.sim.rng import SeededRng


class ISMCTSAgent:
    name = "mcts"

    def __init__(
        self,
        iterations: int,
        rng: SeededRng,
        rollout_depth: int = 40,
        determinizations: int = 1,  # reserved (SO-ISMCTS re-determinizes every iteration)
        exploration: float = 1.4,
        rollout_policy: object | None = None,
    ) -> None:
        self.iterations = max(1, iterations)
        self.rng = rng
        self.rollout_depth = rollout_depth
        self.exploration = exploration
        self.rollout_policy = rollout_policy or GreedyAgent()
        self._nonce = 0

    def decide(self, state) -> object:
        root_player = state.pending.player
        real_legal = legal_actions(state)
        if len(real_legal) <= 1:  # nothing to search
            return real_legal[0] if real_legal else self.rollout_policy.decide(state)

        root = Node()
        for _ in range(self.iterations):
            self._nonce += 1
            world = determinize(state, root_player, self.rng.spawn(self._nonce))
            self._simulate(world, root, root_player)

        best = best_child_key(root)
        for action in real_legal:  # map the chosen key back to a real, applicable action
            if action_key(action) == best:
                return action
        return self.rollout_policy.decide(state)  # pragma: no cover - key always maps back

    def _simulate(self, world, root: Node, root_player: str) -> None:
        node = root
        path = [root]
        while not world.terminal:
            advance(world)
            if world.terminal:
                break
            if world.pending.player != root_player:  # opponent plays the fixed rollout policy
                apply(world, self.rollout_policy.decide(world))
                continue
            keymap: dict = {}
            for action in legal_actions(world):
                keymap.setdefault(action_key(action), action)
            keys = list(keymap)
            untried = [k for k in keys if k not in node.children]
            if untried:  # EXPANSION: add one child, then roll out
                k = untried[min(len(untried) - 1, int(self.rng.random() * len(untried)))]
                node.children[k] = Node()
                apply(world, keymap[k])
                node = node.children[k]
                path.append(node)
                break
            k = select(node, keys, self.exploration, self.rng.random)  # SELECTION (UCB)
            apply(world, keymap[k])
            node = node.children[k]
            path.append(node)

        backprop(path, self._rollout(world, root_player))

    def _rollout(self, world, root_player: str) -> float:
        steps = 0
        while not world.terminal and steps < self.rollout_depth:
            advance(world)
            if world.terminal:
                break
            apply(world, self.rollout_policy.decide(world))
            steps += 1
        if not world.terminal:
            advance(world)  # settle any trailing deterministic phase (may end the game)
        if world.terminal:
            return terminal_reward(world, root_player)
        return score_reward(world, root_player)
