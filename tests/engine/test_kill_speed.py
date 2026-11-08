"""Kill speed as a range (B32): one player unopposed from the goldfish runs, the table from a
measured pod, and the wording rule (always say against what; no kill reads "no kill in N")."""
from __future__ import annotations

import pytest

from mythgauntlet.ratings import kill_speed, metrics
from mythgauntlet.ratings.pod import PodRating, pod_winrate
from mythgauntlet.sim.tier0 import RunStats, SimConfig, simulate
from mythgauntlet.sim.tier2 import DuelConfig, build_game_cards


def _runs(turns):
    return [RunStats(kill_turn=t) for t in turns]


def test_quantile_matches_numpys_linear_default():
    xs = [5, 7, 8, 8, 9, 12]
    assert kill_speed.quantile(xs, 0.25) == 7.25
    assert kill_speed.quantile(xs, 0.5) == 8.0
    assert kill_speed.quantile(xs, 0.75) == 8.75
    assert kill_speed.quantile([], 0.5) is None
    assert kill_speed.quantile([6], 0.25) == 6.0


def test_range_and_by_turn_shares_are_over_the_right_denominators():
    ks = kill_speed.compute(_runs([6, 7, 8, 8, 10, None, None, None]), horizon=12)
    assert (ks.games, ks.killing_games, ks.kill_rate) == (8, 5, 0.625)
    assert (ks.p25, ks.median, ks.p75) == (7.0, 8.0, 8.0)
    assert ks.mean == pytest.approx(7.8)
    # by-turn shares count ALL games, so a deck that often never kills cannot look fast
    assert ks.by_turn == {6: 0.125, 8: 0.5, 10: 0.625}
    assert ks.text.startswith("Unopposed, it kills one player in 62% of 8 games: median T8")
    assert "middle half T7-T8" in ks.text and "By T6: 12%, T8: 50%, T10: 62%" in ks.text


def test_a_deck_with_no_kill_never_reports_a_turn():
    ks = kill_speed.compute(_runs([None] * 40), horizon=12)
    assert ks.median is None and ks.mean is None and ks.by_turn == {6: 0.0, 8: 0.0, 10: 0.0}
    assert ks.text == "Unopposed: no kill in 40 games (12-turn horizon)."
    assert "T" not in ks.text.replace("Unopposed", "")


def test_by_turn_omits_turns_past_the_horizon():
    assert kill_speed.compute(_runs([5, 7]), horizon=8).by_turn == {6: 0.5, 8: 1.0}


def test_mean_reproduces_the_reports_avg_kill_turn(make_card):
    forest = make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                       color_identity=("G",))
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature — Bear", colors=("G",),
                     color_identity=("G",))
    bear.power, bear.toughness = "2", "2"
    cfg = SimConfig(turns=12, runs=150, seed=11)
    runs = simulate([(forest, 38), (bear, 61)], None, cfg)
    report = metrics.compute(runs, cfg)
    ks = kill_speed.compute(runs, cfg.turns)
    assert ks.killing_games > 0
    assert ks.mean == pytest.approx(report.avg_kill_turn)
    assert ks.kill_rate == pytest.approx(report.goldfish_kill_rate, abs=1e-3)


def test_pod_records_kill_rounds_apart_from_turn_cap_wins(make_card, forest):
    hasty = make_card("Hasty", mana_cost="{1}{G}", type_line="Creature - Beast",
                      color_identity=("G",))
    hasty.power, hasty.toughness = "6", "6"
    aggro = (build_game_cards([(forest, 20), (hasty, 40)], None), None, ())
    dud = (build_game_cards([(forest, 60)], None), None, ())
    r = pod_winrate(aggro, [dud], DuelConfig(max_turns=40, start_life=20), games=8, seed=1)
    assert r.kill_wins + r.adjudicated_wins == r.wins
    assert len(r.win_rounds) == r.kill_wins and r.kill_wins > 0
    assert all(1 <= t <= 40 for t in r.win_rounds) and list(r.win_rounds) == sorted(r.win_rounds)


def _pod(wins, games, rounds, adjudicated=0):
    return PodRating(games=games, wins=wins, pod_size=4, winrate=wins / games, baseline=0.25,
                     lift=wins / games - 0.25, kill_wins=len(rounds),
                     adjudicated_wins=adjudicated, win_rounds=tuple(rounds))


def test_table_names_its_field_and_carries_its_game_count():
    ts = kill_speed.table(_pod(30, 100, [8, 9, 9, 10] * 7, adjudicated=2),
                          "a field of 176 Bracket 3 corpus decks", 9.0, 0.71)
    assert ts.games == 100 and ts.kill_wins == 28 and ts.win_round_median == 9.0
    lo, hi = ts.winrate_ci90
    assert lo < 0.30 < hi
    assert ts.text.startswith("Against a field of 176 Bracket 3 corpus decks, it wins 30 of 100 "
                              "4-player games (30%")
    assert "last player standing: median round 9" in ts.text and "over 28 games" in ts.text
    assert "2 of its wins came on the turn cap" in ts.text
    assert "Unopposed, its damage reaches table-lethal by ~T9 in 71%" in ts.text


def test_table_quartiles_read_as_whole_rounds():
    ts = kill_speed.table(_pod(4, 40, [13, 17, 17, 21]), "a field of 9 corpus decks", None, 0.0)
    assert (ts.win_round_p25, ts.win_round_p75) == (16.0, 18.0)
    ts = kill_speed.table(_pod(4, 40, [14, 16, 17, 23]), "a field of 9 corpus decks", None, 0.0)
    assert ts.win_round_p25 == 15.5 and ts.win_round_p75 == 18.5
    assert "(middle half 16-19)" in ts.text          # half rounds up, never banker's rounding


def test_table_with_no_win_reports_no_round():
    ts = kill_speed.table(_pod(0, 50, []), "a field of 3 corpus decks", None, 0.0)
    assert ts.win_round_median is None and "round" not in ts.text
    assert "never reaches table-lethal" in ts.text


def test_wilson_interval_is_sane():
    lo, hi = kill_speed.wilson(0, 40)
    assert lo == 0.0 and 0 < hi < 0.1
    lo, hi = kill_speed.wilson(20, 40)
    assert lo < 0.5 < hi and hi - lo < 0.3
