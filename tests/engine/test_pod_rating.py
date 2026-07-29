"""Pod meta-rating (ratings/pod.py): a deck's win share in 4-player games (offline, synthetic)."""

from __future__ import annotations

import json

import pytest

from mythgauntlet.ratings.pod import PodRating, pod_winrate, prepare_seat
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier2 import DuelConfig, build_game_cards


def _aggro_seat(make_card, forest, power=6):
    hasty = make_card("Hasty", mana_cost="{1}{G}", type_line="Creature - Beast",
                      color_identity=("G",))
    hasty.power, hasty.toughness = str(power), str(power)
    return build_game_cards([(forest, 20), (hasty, 40)], None), None, ()


def _do_nothing_seat(make_card, forest):
    return build_game_cards([(forest, 60)], None), None, ()


def _cfg():
    return DuelConfig(max_turns=40, start_life=20)


def test_aggro_deck_wins_more_than_its_fair_share(make_card, forest):
    aggro = _aggro_seat(make_card, forest)
    field = [_do_nothing_seat(make_card, forest)]
    r = pod_winrate(aggro, field, _cfg(), games=8, seed=1)
    assert isinstance(r, PodRating)
    assert r.games == 8 and r.pod_size == 4
    assert r.baseline == 0.25
    assert r.winrate > 0.5 and r.lift > 0  # a real deck beats a table of do-nothing


def test_do_nothing_deck_underperforms_the_baseline(make_card, forest):
    dud = _do_nothing_seat(make_card, forest)
    field = [_do_nothing_seat(make_card, forest)]
    r = pod_winrate(dud, field, _cfg(), games=8, seed=2)
    assert r.winrate <= r.baseline  # never out-races a mirror of nothing (games go to a draw)


def test_stronger_deck_out_rates_a_weaker_one_in_the_same_field(make_card, forest):
    strong = _aggro_seat(make_card, forest, power=8)
    weak = _aggro_seat(make_card, forest, power=2)
    field = [_do_nothing_seat(make_card, forest)]
    rs = pod_winrate(strong, field, _cfg(), games=8, seed=3)
    rw = pod_winrate(weak, field, _cfg(), games=8, seed=3)
    assert rs.winrate >= rw.winrate


def test_pod_winrate_is_deterministic(make_card, forest):
    aggro = _aggro_seat(make_card, forest)
    field = [_do_nothing_seat(make_card, forest), _aggro_seat(make_card, forest, power=3)]
    a = pod_winrate(aggro, field, _cfg(), games=6, seed=9)
    b = pod_winrate(aggro, field, _cfg(), games=6, seed=9)
    assert a == b


def test_pod_winrate_requires_opponents(make_card, forest):
    with pytest.raises(ValueError):
        pod_winrate(_aggro_seat(make_card, forest), [], _cfg(), games=4, seed=1)


def test_prepare_seat_builds_a_reusable_seat(make_card, tmp_path):
    (tmp_path / "authored").mkdir()
    store = SemanticsStore(authored=tmp_path / "authored", compiled=tmp_path / "none")
    forest = make_card("Forest", type_line="Basic Land - Forest", produced_mana=("G",))
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature - Bear")
    bear.power, bear.toughness = "2", "2"
    commander = make_card("Cmdr", mana_cost="{2}{G}", type_line="Legendary Creature - Elf")
    commander.power, commander.toughness = "3", "3"
    deck, cmdr, combos = prepare_seat([(forest, 30), (bear, 29)], commander, store)
    assert len(deck) == 59 and cmdr is not None and cmdr.card.name == "Cmdr"
    assert combos == ()


def test_pod_rating_wired_into_a_json_roundtrip():
    # PodRating is a plain dataclass -> serializable for the API / reports.
    from dataclasses import asdict
    r = PodRating(games=10, wins=4, pod_size=4, winrate=0.4, baseline=0.25, lift=0.15)
    assert json.loads(json.dumps(asdict(r)))["lift"] == 0.15
