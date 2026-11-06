"""Bracket 1-2 combo repair (docs/DECKBUILD_REVIEW.md P1a). The engine is faked; what is under test is
Forge's own logic: which cards get cut, that the commander never does, that the library stays exactly
the size it was, that cut cards are not drafted back, and that every failure mode degrades to "ship the
build unchanged"."""
from __future__ import annotations

import pytest

import bracket_repair as br
import deck_builder
from bracket import BracketFilter
from deck_builder import DeckBuilder

_MANA = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}


@pytest.fixture(autouse=True)
def stub_basics():
    saved = dict(deck_builder._BASIC_LAND_CACHE)
    for name, sym in _MANA.items():
        deck_builder._BASIC_LAND_CACHE[name] = {
            "name": name, "type_line": f"Basic Land — {name}", "mana_cost": "", "cmc": 0.0,
            "oracle_text": "", "colors": [], "color_identity": [sym], "produced_mana": [sym]}
    yield
    deck_builder._BASIC_LAND_CACHE.clear()
    deck_builder._BASIC_LAND_CACHE.update(saved)


def _spell(name, cmc=3):
    return {"name": name, "type_line": "Artifact", "mana_cost": "{%d}" % cmc, "cmc": float(cmc),
            "oracle_text": "", "colors": [], "color_identity": []}


class _Client:
    """Hands the builder a fixed replacement pool; no network."""

    def __init__(self, pool):
        self.pool = pool
        self.queries = 0

    def search_cards_paged(self, query, max_results=60):
        self.queries += 1
        return list(self.pool)

    def search_cards(self, query):
        return {"data": []}

    def get_cards_collection(self, names):
        return {}


class _Profile:
    color_identity = ["R"]
    is_colorless = False
    color_id_str = "R"
    mana_value = 4
    card = {"name": "Krenko", "type_line": "Legendary Creature", "mana_cost": "{2}{R}{R}",
            "oracle_text": "", "cmc": 4}


def _builder(deck_names, pool_names, bracket=2):
    b = DeckBuilder(_Client([_spell(n) for n in pool_names]))
    b._deck = [_spell(n) for n in deck_names]
    b._names = set(deck_names) | {"Krenko"}
    b._commander_name = "Krenko"
    b._bracket_filter = BracketFilter(bracket)
    b._owned, b._owned_cards, b._pool, b._lifts = set(), [], None, {}
    b._card_source = deck_builder.SOURCE_SCRYFALL
    b._library_size = len(deck_names)
    b._curve_target = {k: 99 for k in range(0, 8)}
    return b


COMMANDER = {"name": "Krenko"}


def _fake_engine(table):
    """analyze(text, name) -> the combo report for whatever deck text it is shown."""
    calls = []

    def analyze(text, name):
        calls.append(text)
        return table(text)
    analyze.calls = calls
    return analyze


def _report(*combos):
    return {"checked": True, "total": len(combos), "items": [{"cards": list(c)} for c in combos]}


# -- pick_cuts -------------------------------------------------------------------------------------------

def test_pick_cuts_takes_the_card_that_breaks_the_most_combos():
    items = [{"cards": ["Krenko", "Prospector", "Warchief"]},
             {"cards": ["Krenko", "Prospector", "Chieftain"]},
             {"cards": ["Taunter", "Reservoir"]}]
    cuts = br.pick_cuts(items, {"Krenko"}, ["Taunter", "Reservoir", "Prospector", "Warchief", "Chieftain"], 6)
    assert cuts[0] == "Prospector" and len(cuts) == 2           # one card kills two combos; one more for the third


def test_pick_cuts_never_picks_the_commander_or_partner():
    items = [{"cards": ["Krenko", "Tymna", "Sol Ring"]}]
    assert br.pick_cuts(items, {"Krenko", "Tymna"}, ["Sol Ring"], 6) == ["Sol Ring"]


def test_a_combo_of_only_protected_cards_cannot_be_cut():
    assert br.pick_cuts([{"cards": ["Krenko", "Tymna"]}], {"Krenko", "Tymna"}, [], 6) == []


def test_pick_cuts_ties_go_to_the_card_drafted_later_and_respect_the_limit():
    items = [{"cards": ["A", "B"]}, {"cards": ["C", "D"]}, {"cards": ["E", "F"]}]
    cuts = br.pick_cuts(items, set(), ["A", "B", "C", "D", "E", "F"], 2)
    assert cuts == ["F", "D"]                                   # latest-drafted of each tied pair


# -- swap_out ------------------------------------------------------------------------------------------------

def test_swap_out_keeps_the_library_size_and_does_not_redraft_the_cut_card():
    b = _builder(["A", "B", "C", "D"], ["B", "X", "Y"])      # the pool offers B straight back
    added = b.swap_out({"B"}, _Profile())
    names = [c["name"] for c in b._deck]
    assert len(names) == 4 and "B" not in names
    assert added and set(added) <= {"X", "Y"}


def test_swap_out_pads_with_basics_when_the_pool_is_dry():
    b = _builder(["A", "B", "C"], [])
    b.swap_out({"B"}, _Profile())
    names = [c["name"] for c in b._deck]
    assert len(names) == 3 and "Mountain" in names


def test_swap_out_never_removes_the_commander_name():
    b = _builder(["A", "Krenko"], ["X"])
    assert b.swap_out({"Krenko"}, _Profile()) == [] and len(b._deck) == 2


# -- the loop --------------------------------------------------------------------------------------------------

def test_only_brackets_1_and_2_are_repaired_and_the_engine_is_not_asked_otherwise():
    b = _builder(["A", "B"], ["X"], bracket=3)
    engine = _fake_engine(lambda t: _report(["A", "B"]))
    r = br.repair_combos(b, _Profile(), COMMANDER, [], 3, analyze=engine)
    assert r["applicable"] is False and engine.calls == [] and r["passes"] == 0


def test_a_combo_is_cut_and_replaced_then_confirmed_gone():
    b = _builder(["A", "B", "C"], ["X", "Y"])

    def table(text):
        return _report(["A", "B"]) if ("1 A" in text and "1 B" in text) else _report()

    r = br.repair_combos(b, _Profile(), COMMANDER, [], 2, analyze=_fake_engine(table))
    names = [c["name"] for c in b._deck]
    assert r["combos_before"] == 1 and r["combos_after"] == 0 and r["passes"] == 1
    assert len(r["removed"]) == 1 and r["removed"][0] in {"A", "B"} and r["removed"][0] not in names
    assert len(names) == 3 and r["added"] and r["skipped"] is None


def test_the_loop_is_bounded_when_replacements_keep_making_combos():
    b = _builder(["A", "B", "C", "D"], [f"P{i}" for i in range(40)])
    # every deck always has some combo among whatever two cards come first
    engine = _fake_engine(lambda t: _report([n for n in ["A", "B", "C", "D"] + [f"P{i}" for i in range(40)]
                                             if f"1 {n}\n" in t + "\n"][:2]))
    r = br.repair_combos(b, _Profile(), COMMANDER, [], 1, analyze=engine)
    assert r["passes"] <= br.MAX_PASSES and len(r["removed"]) <= br.MAX_CUTS_TOTAL
    assert r["combos_after"] == 1                               # honest: it did not manage to clear it
    assert len(b._deck) == 4


def test_an_unreachable_engine_leaves_the_build_untouched_and_says_so():
    b = _builder(["A", "B"], ["X"])
    r = br.repair_combos(b, _Profile(), COMMANDER, [], 1, analyze=lambda t, n: None)
    assert r["skipped"] == "strength engine unreachable" and r["passes"] == 0
    assert [c["name"] for c in b._deck] == ["A", "B"]


def test_engine_dropping_out_mid_repair_is_reported():
    b = _builder(["A", "B", "C"], ["X", "Y"])
    answers = iter([_report(["A", "B"]), None])
    r = br.repair_combos(b, _Profile(), COMMANDER, [], 2, analyze=lambda t, n: next(answers))
    assert "mid-repair" in r["skipped"] and r["passes"] == 1


def test_commander_only_combos_are_reported_not_chased():
    b = _builder(["A", "B"], ["X"])
    r = br.repair_combos(b, _Profile(), {"name": "Krenko"}, [{"name": "Tymna"}], 1,
                         analyze=lambda t, n: _report(["Krenko", "Tymna"]))
    assert r["passes"] == 0 and "commander" in r["skipped"]


# -- decklist text / engine call -----------------------------------------------------------------------------

def test_decklist_text_lists_commander_partners_and_quantities():
    text = br.decklist_text("Tymna", [{"name": "Thrasios"}],
                            [{"name": "Plains"}, {"name": "Plains"}, {"name": "Sol Ring"}])
    assert text.splitlines() == ["Commander:", "1 Tymna", "1 Thrasios", "", "Deck:", "2 Plains", "1 Sol Ring"]


def test_engine_combos_handles_http_errors_and_unchecked_reports(monkeypatch):
    class R:
        def __init__(self, code, body):
            self.status_code, self._b = code, body

        def json(self):
            return self._b

    monkeypatch.setattr(br.requests, "post", lambda *a, **k: R(500, {}))
    assert br.engine_combos("x", "n") is None
    monkeypatch.setattr(br.requests, "post", lambda *a, **k: R(200, {"combos": {"checked": False}}))
    assert br.engine_combos("x", "n") is None                  # Spellbook outage: not "zero combos"
    monkeypatch.setattr(br.requests, "post", lambda *a, **k: R(200, {"combos": {"checked": True, "total": 2}}))
    assert br.engine_combos("x", "n")["total"] == 2

    def boom(*a, **k):
        raise ConnectionError

    monkeypatch.setattr(br.requests, "post", boom)
    assert br.engine_combos("x", "n") is None


# -- power trim (P2) ---------------------------------------------------------------------------------------------

def _tutor(name):
    c = _spell(name)
    c["oracle_text"] = "Search your library for a card, put it into your hand."
    return c


def _est(table):
    calls = []

    def f(text, name):
        calls.append(text)
        return table(text)
    f.calls = calls
    return f


def test_is_tutor_ignores_land_fetch_and_lands():
    assert br.is_tutor(_tutor("T"))
    land_fetch = _spell("Rampant Growth")
    land_fetch["oracle_text"] = "Search your library for a basic land card."
    assert not br.is_tutor(land_fetch)


def test_power_trim_only_applies_at_bracket_1():
    b = _builder(["Sol Ring", "B"], ["X"], bracket=2)
    e = _est(lambda t: 3)
    r = br.repair_power(b, _Profile(), COMMANDER, [], 2, estimate=e)
    assert r["applicable"] is False and e.calls == []


def test_power_trim_swaps_fast_mana_and_tutors_until_estimate_drops():
    b = _builder(["Sol Ring", "B", "C"], ["X", "Y"], bracket=1)
    b._deck.append(_tutor("Mystical"))
    b._library_size = 4
    r = br.repair_power(b, _Profile(), COMMANDER, [], 1,
                        estimate=_est(lambda t: 2 if "Sol Ring" in t or "Mystical" in t else 1))
    names = [c["name"] for c in b._deck]
    assert r["estimate_before"] == 2 and r["estimate_after"] == 1 and r["passes"] == 1
    assert set(r["removed"]) == {"Sol Ring", "Mystical"} and len(names) == 4 and "Sol Ring" not in names


def test_power_trim_reverts_when_the_estimate_gets_worse():
    b = _builder(["Sol Ring", "B"], ["X"], bracket=1)
    answers = iter([2, 3])
    r = br.repair_power(b, _Profile(), COMMANDER, [], 1, estimate=lambda t, n: next(answers))
    assert [c["name"] for c in b._deck] == ["Sol Ring", "B"] and r["passes"] == 0
    assert "worse" in r["skipped"]


def test_power_trim_without_engine_or_candidates_leaves_build_alone():
    b = _builder(["A", "B"], ["X"], bracket=1)
    assert br.repair_power(b, _Profile(), COMMANDER, [], 1, estimate=lambda t, n: None)["skipped"] \
        == "strength engine unreachable"
    r = br.repair_power(b, _Profile(), COMMANDER, [], 1, estimate=lambda t, n: 2)
    assert r["skipped"] == "no fast mana or tutors left to cut" and len(b._deck) == 2


def test_repair_build_merges_both_reports(monkeypatch):
    monkeypatch.setattr(br, "POWER_TRIM", True)
    b = _builder(["Sol Ring", "A", "B"], ["X", "Y"], bracket=1)
    combos = lambda t, n: _report() if "Sol Ring" not in t else _report(["A", "B"])
    r = br.repair_build(b, _Profile(), COMMANDER, [], 1, analyze=combos,
                        estimate=lambda t, n: 2 if "Sol Ring" in t else 1)
    assert "Sol Ring" in r["removed"] and "Sol Ring" not in [c["name"] for c in b._deck]
    assert r["power"]["estimate_after"] == 1
    r2 = br.repair_build(_builder(["A"], ["X"], bracket=3), _Profile(), COMMANDER, [], 3)
    assert r2["passes"] == 0 and r2["power"]["applicable"] is False


def test_power_trim_is_off_by_default(monkeypatch):
    monkeypatch.setattr(br, "POWER_TRIM", False)
    e = _est(lambda t: 2)
    r = br.repair_build(_builder(["Sol Ring", "A"], ["X"], bracket=1), _Profile(), COMMANDER, [], 1,
                        analyze=lambda t, n: _report(), estimate=e)
    assert e.calls == [] and r["power"]["applicable"] is False
