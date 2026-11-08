"""Table-contract dials (D3): each band, its edges, and the reasons that name why."""
from __future__ import annotations

from types import SimpleNamespace as NS

from mythgauntlet.ratings import dials
from mythgauntlet.ratings.denial import DeckDenial, Lock


def _den(locks=0, counters=0, theft=0, extra=0, mld=0):
    return DeckDenial(locks=[Lock(f"Lock {i}", "attack", "x") for i in range(locks)],
                      counterspells=counters, theft=theft, extra_turn_cards=extra,
                      mass_land_denial=[f"Moon {i}" for i in range(mld)])


def test_denial_bands_and_edges():
    assert dials.denial_dial(_den()).band == "Low"
    assert dials.denial_dial(_den(counters=3)).band == "Low"
    assert dials.denial_dial(_den(locks=1, counters=1)).band == "Medium"      # 4 points
    assert dials.denial_dial(_den(counters=7)).band == "Medium"
    assert dials.denial_dial(_den(counters=8)).band == "High"                # "tons of counters"
    assert dials.denial_dial(_den(locks=2, counters=2)).band == "High"
    d = dials.denial_dial(_den(locks=1, counters=9, theft=1))
    assert d.reasons == ["1 lock piece (Lock 0)", "9 counterspells", "1 theft card"]
    assert d.value == 13.0
    assert dials.denial_dial(_den()).reasons == ["nothing that stops other players from playing"]


def _ks(by6, by10, horizon=12):
    return NS(by_turn={"6": by6, "8": (by6 + by10) / 2, "10": by10}, horizon=horizon)


def test_pace_bands():
    assert dials.pace_dial(_ks(0.25, 0.9), None).band == "Fast"      # Bracket 3's six turns
    assert dials.pace_dial(_ks(0.24, 0.9), None).band == "Typical"
    assert dials.pace_dial(_ks(0.0, 0.5), None).band == "Typical"
    slow = dials.pace_dial(_ks(0.0, 0.49), None)
    assert slow.band == "Long"
    assert slow.reasons[0] == "ends 0% of games by T6 and 49% by T10 (by damage, unopposed)"


def test_pace_reads_the_combined_clock_when_combos_ran():
    clock = NS(by_turn={6: 0.31, 10: 0.71})
    fast = dials.pace_dial(_ks(0.0, 0.14), clock)       # damage alone would read Long
    assert fast.band == "Fast" and "by damage or combo" in fast.reasons[0]


def _clock(first, games=100, lead=("A", "B")):
    return NS(games=games, combo_first_games=first, lead_combo=lead)


def test_inevitability_bands():
    hi = dials.inevitability_dial(_clock(50), NS(total=1), tutors=0, combos_checked=True)
    assert hi.band == "High"
    assert hi.reasons[0] == "a combo wins before damage in 50% of games (most often A + B)"
    assert dials.inevitability_dial(_clock(25), NS(total=1), 3, True).band == "High"
    assert dials.inevitability_dial(_clock(25), NS(total=1), 2, True).band == "Medium"
    # many tutors + a combo: the same win, even when the clock can't time it
    assert dials.inevitability_dial(_clock(0), NS(total=2), 6, True).band == "High"
    assert dials.inevitability_dial(_clock(0), NS(total=2), 5, True).band == "Medium"
    assert dials.inevitability_dial(None, None, tutors=6, combos_checked=True).band == "Medium"
    assert dials.inevitability_dial(None, None, tutors=4, combos_checked=True).band == "Medium"
    low = dials.inevitability_dial(None, None, tutors=1, combos_checked=False)
    assert low.band == "Low" and low.reasons == ["1 tutor", "combos not checked"]
