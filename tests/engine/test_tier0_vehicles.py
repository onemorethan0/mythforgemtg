"""Vehicles (crew, CR 702.122), Spacecraft (station, CR 702.184) and printed haste (CR 702.10)
in the goldfish sim. Gold set: the real cards' printed text."""
from __future__ import annotations

from mythgauntlet.sim.tier0 import (SimConfig, _crew_cost, _has_own_haste, _station_threshold,
                                    simulate)

CFG = SimConfig(turns=12, runs=150, seed=5)
RAMMER = ("When this Spacecraft enters, create a 2/2 colorless Robot artifact creature token.\n"
          "Station (Tap another creature you control: Put charge counters equal to its power on "
          "this Spacecraft. Station only as a sorcery. It's an artifact creature at 9+.)\n"
          "9+ | Flying, first strike")
ELEVATOR = ("{T}: Add {C}{C}{C}.\nStation (Tap another creature you control: Put charge counters "
            "equal to its power on this Spacecraft. Station only as a sorcery.)\n20+ | {T}: Add X "
            "mana of any one color, where X is the number of charge counters on The Eternity "
            "Elevator.")


def test_parsers_gold_set():
    assert _crew_cost("Artifact — Vehicle", "Crew 3 (Tap any number of untapped creatures you "
                                            "control with total power 3 or more: This Vehicle "
                                            "becomes an artifact creature until end of turn.)") == 3
    assert _crew_cost("Artifact — Vehicle", "Flying\nCrew 1") == 1
    assert _crew_cost("Artifact", "Crew 1") is None
    assert _station_threshold("Artifact — Spacecraft", RAMMER) == 9
    assert _station_threshold("Legendary Artifact — Spacecraft", ELEVATOR) is None
    assert _has_own_haste("Haste")
    assert _has_own_haste("Flying, haste")
    assert not _has_own_haste("Other creatures you control have haste.")
    assert not _has_own_haste("{R}: This creature gains haste until end of turn.")


def _forest(make_card):
    return make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                     color_identity=("G",))


def _creature(make_card, name, text="", power="2", toughness="2", cost="{1}{G}"):
    c = make_card(name, mana_cost=cost, type_line="Creature — Bear", colors=("G",),
                  color_identity=("G",), oracle_text=text)
    c.power, c.toughness = power, toughness
    return c


def _sums(runs):
    for r in runs:
        total = r.damage_by_turn[-1] if r.damage_by_turn else 0
        assert sum(r.damage_by_card.values()) == total
        assert sum(r.damage_by_source.values()) == total


def _mean_kill(runs):
    return sum(r.kill_turn or 99 for r in runs) / len(runs)


def test_haste_creatures_kill_sooner(make_card):
    slow = simulate([(_forest(make_card), 40), (_creature(make_card, "Bear"), 59)], None, CFG)
    fast = simulate([(_forest(make_card), 40),
                     (_creature(make_card, "Raging Bear", "Haste"), 59)], None, CFG)
    _sums(fast)
    assert _mean_kill(fast) < _mean_kill(slow)


def _vehicle(make_card, crew=1, power="6"):
    v = make_card("Battle Wagon", mana_cost="{2}", type_line="Artifact — Vehicle",
                  oracle_text=f"Trample\nCrew {crew}")
    v.power, v.toughness = power, "6"
    return v


def test_a_crewed_vehicle_attacks(make_card):
    deck = [(_forest(make_card), 40), (_creature(make_card, "Bear", power="1"), 50)]
    with_v = simulate(deck + [(_vehicle(make_card), 9)], None, CFG)
    _sums(with_v)
    assert sum(r.damage_by_card.get("Battle Wagon", 0) for r in with_v) > 0
    without = simulate(deck + [(_creature(make_card, "Dud", power="0", cost="{2}"), 9)],
                       None, CFG)
    assert _mean_kill(with_v) < _mean_kill(without)


def test_a_vehicle_with_no_crew_never_attacks(make_card):
    rock = make_card("Rock", mana_cost="{1}", type_line="Artifact", oracle_text="Draw a card.")
    runs = simulate([(_forest(make_card), 40), (rock, 50), (_vehicle(make_card), 9)], None, CFG)
    assert all(r.damage_by_card.get("Battle Wagon", 0) == 0 for r in runs)


def _ship(make_card, text=RAMMER, name="Wedgelight Rammer"):
    s = make_card(name, mana_cost="{3}", type_line="Artifact — Spacecraft", oracle_text=text)
    s.power, s.toughness = "3", "4"
    return s


def test_a_spacecraft_attacks_once_stationed(make_card):
    deck = [(_forest(make_card), 40), (_creature(make_card, "Ox", power="3"), 50),
            (_ship(make_card), 9)]
    runs = simulate(deck, None, CFG)
    _sums(runs)
    assert sum(r.damage_by_card.get("Wedgelight Rammer", 0) for r in runs) > 0


def test_a_spacecraft_without_creatures_or_threshold_never_attacks(make_card):
    rock = make_card("Rock", mana_cost="{1}", type_line="Artifact", oracle_text="Draw a card.")
    # (the real Rammer's ETB Robot token could station it -- this one has no ETB)
    bare = _ship(make_card, RAMMER.split("\n", 1)[1], "Bare Rammer")
    alone = simulate([(_forest(make_card), 40), (rock, 50), (bare, 9)], None, CFG)
    assert all(r.damage_by_card.get("Bare Rammer", 0) == 0 for r in alone)
    elevator = _ship(make_card, ELEVATOR, "The Eternity Elevator")
    runs = simulate([(_forest(make_card), 40), (_creature(make_card, "Ox", power="3"), 50),
                     (elevator, 9)], None, CFG)
    assert all(r.damage_by_card.get("The Eternity Elevator", 0) == 0 for r in runs)


def test_stationed_spacecraft_die_in_a_wipe_but_counters_and_vehicles_survive(make_card):
    deck = [(_forest(make_card), 40), (_creature(make_card, "Ox", power="3"), 45),
            (_ship(make_card), 5), (_vehicle(make_card), 5)]
    _sums(simulate(deck, None, CFG, board_wipe_turn=6))
