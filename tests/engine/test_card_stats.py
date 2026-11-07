"""Per-card goldfish evidence (B30, docs/SPEC_deck_scouting_report.md, ratings/card_stats.py)."""
from __future__ import annotations

import dataclasses

from mythgauntlet.ratings import card_stats
from mythgauntlet.sim.clock import apply_nut_kills
from mythgauntlet.sim.tier0 import RunStats, SimConfig, simulate


# ── pure aggregation ───────────────────────────────────────────────────────────────────

def _run(seen, played, kill):
    return RunStats(seen_turn=dict(seen), played_turn=dict(played), kill_turn=kill)


def test_a_card_that_wins_when_seen_early_ranks_first_and_is_significant():
    runs = []
    for i in range(200):
        early = i % 2 == 0
        runs.append(_run({"Winner": 1 if early else 9, "Filler": i % 12},
                         {"Winner": 2 if early else 10, "Filler": i % 12},
                         5 if early else 10))
    stats = {s.name: s for s in card_stats.compute(runs, turns=12)}
    w = stats["Winner"]
    assert w.early_uplift == 5.0 and card_stats.significant(w)
    assert card_stats.compute(runs, turns=12)[0].name == "Winner"
    assert w.cast_rate == 1.0 and w.avg_cast_turn == 6.0


def test_a_card_never_played_is_fully_stranded_and_an_unkilled_game_is_a_floor():
    runs = [_run({"Brick": 0}, {}, None) for _ in range(40)]
    s = card_stats.compute(runs, turns=12)[0]
    assert s.stranded_rate == 1.0 and s.cast_rate == 0.0 and s.avg_cast_turn is None
    assert s.early_uplift is None            # no "late" group at all: never guessed


def test_too_small_a_sample_gives_no_uplift():
    runs = [_run({"Rare": 1}, {"Rare": 1}, 6)] * 10 + [_run({}, {}, 8)] * 10
    assert card_stats.compute(runs, turns=12, min_group=30)[0].early_uplift is None


def test_lands_are_marked():
    runs = [_run({"Forest": 0}, {"Forest": 1}, 9)]
    assert card_stats.compute(runs, 12, land_names={"Forest"})[0].is_land


# ── telemetry recorded by tier0 ────────────────────────────────────────────────────────

def _deck(make_card):
    forest = make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                       color_identity=("G",))
    bear = make_card("Bear", mana_cost="{1}", type_line="Creature — Bear", colors=("G",),
                     color_identity=("G",))
    bear.power, bear.toughness = "2", "2"
    brick = make_card("Brick", mana_cost="{W}{W}{W}{W}", type_line="Creature — Wall",
                      colors=("W",), color_identity=("W",))     # uncastable off Forests
    brick.power, brick.toughness = "0", "4"
    return [(forest, 40), (bear, 55), (brick, 4)]


CFG = SimConfig(turns=10, runs=200, seed=3)


def test_seen_and_played_turns_are_consistent(make_card):
    runs = simulate(_deck(make_card), None, CFG)
    for r in runs:
        assert all(0 <= t <= CFG.turns for t in r.seen_turn.values())
        for name, p in r.played_turn.items():
            assert name in r.seen_turn and p >= r.seen_turn[name]
    assert any(0 in r.seen_turn.values() for r in runs)      # the opening hand counts


def test_the_uncastable_card_is_stranded_and_the_bears_are_cast(make_card):
    runs = simulate(_deck(make_card), None, CFG)
    apply_nut_kills(runs, _deck(make_card), CFG.turns)
    stats = {s.name: s for s in card_stats.compute(runs, CFG.turns, {"Forest"})}
    assert stats["Brick"].stranded_rate == 1.0
    assert stats["Bear"].cast_rate > 0.95
    assert stats["Forest"].is_land


def test_telemetry_changes_no_other_figure(make_card):
    """Recorded only: the same seed gives identical play with or without reading it."""
    a = simulate(_deck(make_card), None, CFG)
    b = simulate(_deck(make_card), None, CFG)
    strip = lambda r: {k: v for k, v in dataclasses.asdict(r).items()  # noqa: E731
                       if k not in ("seen_turn", "played_turn")}
    assert [strip(r) for r in a] == [strip(r) for r in b]
    assert [r.seen_turn for r in a] == [r.seen_turn for r in b]


def test_analyze_deck_only_computes_card_stats_when_asked(make_card):
    from mythgauntlet.model.deck import Deck, ResolvedDeck
    from mythgauntlet.ratings.analysis import compute_card_stats
    resolved = ResolvedDeck(deck=Deck(), commanders=[], cards=_deck(make_card), missing=[])
    stats = compute_card_stats(resolved, SimConfig(turns=10, runs=50, seed=1), runs=300)
    names = {s.name for s in stats}
    assert {"Forest", "Bear", "Brick"} <= names
