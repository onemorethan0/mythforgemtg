"""Unit tests for the pure ISMCTS tree + UCB selection (agents/mcts_tree.py)."""

from __future__ import annotations

from mythgauntlet.agents.mcts_tree import Node, backprop, best_child_key, select


def _const_rand(value=0.0):
    return lambda: value


def test_mean_and_backprop():
    n = Node()
    assert n.mean() == 0.0
    backprop([n], 1.0)
    backprop([n], 0.0)
    assert n.visits == 2 and n.reward_sum == 1.0 and n.mean() == 0.5


def test_backprop_updates_whole_path():
    a, b, c = Node(), Node(), Node()
    backprop([a, b, c], 2.0)
    assert all(node.visits == 1 and node.reward_sum == 2.0 for node in (a, b, c))


def test_select_prefers_unvisited():
    root = Node()
    root.children = {"x": Node(), "y": Node()}
    root.children["y"].visits = 5  # y explored, x never
    root.children["y"].reward_sum = 5.0
    chosen = select(root, ["x", "y"], exploration=1.4, rand=_const_rand(0.0))
    assert chosen == "x"
    # availability incremented for every legal child, whether or not chosen
    assert root.children["x"].avail == 1 and root.children["y"].avail == 1


def test_select_exploits_highest_mean_with_zero_exploration():
    root = Node()
    root.children = {"hi": Node(), "lo": Node()}
    for k, r in (("hi", 1.0), ("lo", 0.0)):
        root.children[k].visits = 1
        root.children[k].reward_sum = r
        root.children[k].avail = 1
    assert select(root, ["hi", "lo"], exploration=0.0, rand=_const_rand()) == "hi"


def test_select_exploration_pulls_toward_less_visited():
    root = Node()
    root.children = {"much": Node(), "few": Node()}
    root.children["much"].visits = 100
    root.children["much"].reward_sum = 60.0  # mean 0.6
    root.children["much"].avail = 100
    root.children["few"].visits = 1
    root.children["few"].reward_sum = 0.5  # mean 0.5 but barely explored
    root.children["few"].avail = 100
    # with a big exploration constant the under-explored child wins despite lower mean
    assert select(root, ["much", "few"], exploration=5.0, rand=_const_rand()) == "few"


def test_best_child_key_is_most_visited_ties_by_insertion():
    root = Node()
    root.children = {"first": Node(), "second": Node()}
    root.children["first"].visits = 3
    root.children["second"].visits = 3  # tie -> first inserted wins
    assert best_child_key(root) == "first"
    root.children["second"].visits = 4
    assert best_child_key(root) == "second"
