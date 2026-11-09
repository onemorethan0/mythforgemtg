"""Kill-method attribution (B34): tier0 per-card / per-source damage, nut-kill methods, T2
combat vs noncombat wins, and the ratings/kill_methods aggregate."""
from __future__ import annotations

import dataclasses

from mythgauntlet.ratings import kill_methods
from mythgauntlet.sim import clock
from mythgauntlet.sim.tier0 import RunStats, SimConfig, simulate

CFG = SimConfig(turns=12, runs=150, seed=5)


def _forest(make_card):
    return make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                     color_identity=("G",))


def _bear(make_card, name="Bear", power="2"):
    c = make_card(name, mana_cost="{1}{G}", type_line="Creature — Bear", colors=("G",),
                  color_identity=("G",))
    c.power, c.toughness = power, "2"
    return c


def _anthem(make_card):
    return make_card("Banner", mana_cost="{2}", type_line="Enchantment",
                     oracle_text="Creatures you control get +1/+1.")


def _check_sums(runs):
    for r in runs:
        total = r.damage_by_turn[-1] if r.damage_by_turn else 0
        assert sum(r.damage_by_card.values()) == total
        assert sum(r.damage_by_source.values()) == total


def test_attribution_sums_to_the_games_own_damage(make_card):
    deck = [(_forest(make_card), 38), (_bear(make_card), 55), (_anthem(make_card), 3)]
    runs = simulate(deck, None, CFG)
    _check_sums(runs)
    assert any(r.damage_by_card.get("Banner") for r in runs)      # anthem gets its share


def test_attribution_survives_a_board_wipe(make_card):
    deck = [(_forest(make_card), 38), (_bear(make_card), 55), (_anthem(make_card), 3)]
    _check_sums(simulate(deck, None, CFG, board_wipe_turn=5))


def test_commander_damage_is_its_own_source_and_lethal_turn_is_recorded(make_card):
    cmdr = make_card("Big Boss", mana_cost="{2}{G}", type_line="Legendary Creature — Giant",
                     colors=("G",), color_identity=("G",))
    cmdr.power, cmdr.toughness = "8", "8"
    deck = [(_forest(make_card), 40), (_bear(make_card, "Squirrel", "1"), 59)]
    runs = simulate(deck, cmdr, CFG)
    _check_sums(runs)
    assert sum(r.damage_by_source.get("commander", 0) for r in runs) > 0
    assert any(r.commander_lethal_turn is not None for r in runs)
    km = kill_methods.compute(runs, "Big Boss")
    assert km.top_damage_cards[0]["name"] == "Big Boss" and km.top_damage_cards[0]["commander"]
    # CR 704.5a: an 8/8 commander reaches 21 before the deck reaches 40, so 21 is the kill
    assert km.method_share.get("commander_damage", 0) > 0.5
    for r in runs:
        if r.kill_method == "commander_damage":
            assert r.kill_turn == r.commander_lethal_turn
            assert r.damage_by_turn[r.kill_turn - 1] < 40


def test_a_damage_kill_names_its_largest_source(make_card):
    deck = [(_forest(make_card), 38), (_bear(make_card), 61)]
    runs = simulate(deck, None, CFG)
    killed = [r for r in runs if r.kill_turn is not None]
    assert killed and all(r.kill_method == "combat" for r in killed)
    km = kill_methods.compute(runs)
    assert km.method_share == {"combat": 1.0}
    assert abs(sum(km.damage_share.values()) - 1) < 1e-6


def test_a_nut_kill_records_its_detector(monkeypatch):
    run = RunStats(kill_turn=9, kill_method="combat", mana_available_by_turn=[1] * 12,
                   board_power_by_turn=[0] * 12, board_creatures_by_turn=[0] * 12)
    tie = RunStats(kill_turn=4, kill_method="combat", mana_available_by_turn=[1] * 12,
                   board_power_by_turn=[0] * 12, board_creatures_by_turn=[0] * 12)
    go = type("G", (), {"earliest_turn": 4})()
    monkeypatch.setattr(clock, "estimate_go_off", lambda *a, **k: go)
    monkeypatch.setattr(clock, "earliest_alpha_strike_turn", lambda *a, **k: None)
    clock.apply_nut_kills([run, tie], [], 12)
    assert (run.kill_turn, run.kill_method) == (4, "storm")
    assert (tie.kill_turn, tie.kill_method) == (4, "combat")      # a tie stays a damage kill


def test_duel_reports_how_each_side_won(make_card, forest):
    from mythgauntlet.sim.tier2 import DuelConfig, duel
    deck = [(forest, 40), (_bear(make_card), 59)]
    lands = [(forest, 99)]                 # never blocks, never attacks: bears must win by combat
    res = duel(deck, None, lands, None, DuelConfig(games=20, seed=3))
    assert res.wins_a == 20 and res.win_methods_a == {"combat": 20}
    assert sum(res.win_methods_a.values()) == res.wins_a
    assert sum(res.win_methods_b.values()) == res.wins_b
    assert set(res.win_methods_a) | set(res.win_methods_b) <= {
        "combat", "noncombat", "commander_damage", "combo", "decked", "adjudicated", "poison"}
    assert "combat" in res.win_methods_a or "combat" in res.win_methods_b
    assert "win_methods_a" in dataclasses.asdict(res)


def test_finish_splits_life_by_what_dealt_it():
    from mythgauntlet.sim.game import GameState, _finish
    from mythgauntlet.sim.tier2 import _Player
    a = _Player(name="a", library=[], life=10)
    b = _Player(name="b", library=[], life=-1)
    b.combat_damage_taken, b.noncombat_damage_taken = 6, 35
    state = GameState(players={"a": a, "b": b}, order=["a", "b"], cfg=None, active="a")
    _finish(state, "a", "life")
    assert state.kill_method == "noncombat" and state.result[2] == "life"
