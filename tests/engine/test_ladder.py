"""Agent strength ladder (ratings/ladder.py) + CLI wiring for agent levels. Offline/synthetic.

The full ladder (greedy < mcts:100 < mcts:1000) is a CLI run at real budgets; here we assert the
machinery and the core property cheaply -- a modestly-budgeted ISMCTS decisively beats the greedy
baseline on a decision-rich control mirror, deterministically. (Very small budgets, e.g. mcts:12,
can UNDERperform greedy -- search needs enough iterations to pay off; hence the CLI default starts
at mcts:100.)
"""

from __future__ import annotations

from mythgauntlet.cli import build_parser
from mythgauntlet.ratings.ladder import LadderMatch, is_monotone, run_ladder
from mythgauntlet.sim.tier2 import prepare_deck


def _control_mirror(make_card):
    """A U control deck: lands + counters + a cheap threat + a bomb. In a mirror the only edge is
    agent skill (sequencing threats, holding counter mana)."""
    isl = make_card("Island", type_line="Basic Land - Island",
                    produced_mana=("U",), color_identity=("U",))
    drake = make_card("Storm Drake", mana_cost="{2}{U}", type_line="Creature - Drake",
                      color_identity=("U",))
    drake.power, drake.toughness = "3", "3"
    counter = make_card("Counterspell", mana_cost="{U}{U}", type_line="Instant",
                        color_identity=("U",), oracle_text="Counter target spell.")
    bomb = make_card("Colossus", mana_cost="{4}{U}", type_line="Creature - Giant",
                     color_identity=("U",))
    bomb.power, bomb.toughness = "7", "7"
    deck = [(isl, 26), (counter, 14), (drake, 12), (bomb, 8)]
    return prepare_deck("a", deck, None, None), prepare_deck("b", deck, None, None)


def test_is_monotone_thresholds():
    good = [LadderMatch("mcts:1000", "greedy", 7, 3, 0, 10),
            LadderMatch("mcts:100", "greedy", 6, 4, 0, 10)]
    assert is_monotone(good, threshold=0.55) is True
    bad = good + [LadderMatch("mcts:10", "greedy", 4, 6, 0, 10)]  # one pairing below 55%
    assert is_monotone(bad, threshold=0.55) is False


def test_ladder_search_beats_greedy(make_card):
    a, b = _control_mirror(make_card)
    matches = run_ladder(a, b, ["greedy", "mcts:40"], games=12, seed=3,
                         max_turns=20, rollout_depth=10)
    assert len(matches) == 1
    m = matches[0]
    assert m.strong == "mcts:40" and m.weak == "greedy"
    assert m.strong_winrate >= 0.55  # search decisively outplays the greedy baseline


def test_ladder_is_deterministic(make_card):
    a, b = _control_mirror(make_card)
    r1 = run_ladder(a, b, ["greedy", "mcts:20"], games=8, seed=1, max_turns=18, rollout_depth=8)
    a2, b2 = _control_mirror(make_card)
    r2 = run_ladder(a2, b2, ["greedy", "mcts:20"], games=8, seed=1, max_turns=18, rollout_depth=8)
    key = lambda ms: [(m.strong_wins, m.weak_wins, m.draws) for m in ms]  # noqa: E731
    assert key(r1) == key(r2)


def test_cli_parser_accepts_agent_flags():
    p = build_parser()
    d = p.parse_args(["duel", "a.txt", "b.txt", "--agent-a", "mcts:200",
                      "--agent-b", "greedy", "--mcts-iters", "50"])
    assert d.agent_a == "mcts:200" and d.agent_b == "greedy" and d.mcts_iters == 50
    g = p.parse_args(["gauntlet", "--agent", "mcts", "--mcts-iters", "100"])
    assert g.agent == "mcts" and g.mcts_iters == 100
    lad = p.parse_args(["ladder", "deck.txt", "--levels", "greedy,mcts:100", "--games", "20"])
    assert lad.levels == "greedy,mcts:100" and lad.deck_b is None
