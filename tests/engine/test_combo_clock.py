"""Combos on the clock (B33): assembly by turn from the goldfish's own draws, Spellbook's
per-piece zones and states, tutors as gated outs, prerequisites, and the combined clock."""
from __future__ import annotations

import random
from math import comb

import pytest

from mythgauntlet.data.spellbook import Combo, _variant_to_combo, classify_combo
from mythgauntlet.ratings import combo_clock
from mythgauntlet.semantics.combo_rules import DeterminismVerdict
from mythgauntlet.sim.tier0 import SimConfig, simulate

KEEP_ALL = dict(mulligan_min_lands=0, mulligan_max_lands=7)


def _land(make_card):
    return make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                     color_identity=("G",))


def _filler(make_card, name="Filler"):
    return make_card(name, mana_cost="{9}", type_line="Sorcery")     # never cast early


def _combo(cards, zones, *, mv=0, produces=("Win the game",), untapped=None, other=None,
           templates=(), quantities=None, notable="", easy=""):
    n = len(cards)
    return Combo(id="t", cards=tuple(cards), produces=tuple(produces), bracket_tag=None,
                 mana_needed="", popularity=None, mana_value=mv,
                 notable_prerequisites=notable, easy_prerequisites=easy,
                 zones=tuple(tuple(z) for z in zones),
                 needs_untapped=tuple(untapped or [False] * n),
                 other_state=tuple(other or [False] * n),
                 quantities=tuple(quantities or [1] * n), templates=tuple(templates))


def _run(deck, cfg, commander=None):
    return simulate(deck, commander, cfg)


def _clock(runs, combos, deck, commanders=(), horizon=10, det=None):
    grades = [classify_combo(c, frozenset(x.name for x in commanders), determinism=det)
              for c in combos]
    return combo_clock.compute(runs, grades, [c for c, _n in deck], list(commanders), horizon)


def test_assembly_matches_the_exact_draw_probability(make_card):
    """Spec accept: within 2 points of a direct Monte-Carlo draw over the same deck (draws
    only). Two zero-cost hand pieces, no draw engines, every hand kept: by turn T the deck has
    seen 7 + T of its 99 cards, so P(both) = k(k-1) / (99*98) exactly."""
    a = make_card("Piece A", mana_cost="{0}", type_line="Instant")
    b = make_card("Piece B", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 40), (_filler(make_card), 57), (a, 1), (b, 1)]
    cfg = SimConfig(turns=10, runs=2000, seed=3, **KEEP_ALL)
    runs = _run(deck, cfg)
    tc = _clock(runs, [_combo(["Piece A", "Piece B"], [["H"], ["H"]])], deck).combos[0]
    rng = random.Random(7)
    names = ["x"] * 97 + ["A", "B"]
    mc = {}
    for t in combo_clock.REPORT_TURNS:
        hits = 0
        for _ in range(4000):
            top = rng.sample(names, 7 + t)
            hits += "A" in top and "B" in top
        mc[t] = hits / 4000
    for t, share in tc.by_turn.items():
        k = 7 + t
        exact = comb(97, k - 2) / comb(99, k)
        assert abs(share - exact) < 0.02, (t, share, exact)
        assert abs(share - mc[t]) < 0.03, (t, share, mc[t])


def test_a_battlefield_piece_waits_for_its_mana(make_card):
    big = make_card("Big Engine", mana_cost="{6}", type_line="Artifact")
    key = make_card("Key", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 40), (_filler(make_card), 57), (big, 1), (key, 1)]
    runs = _run(deck, SimConfig(turns=12, runs=400, seed=5, **KEEP_ALL))
    combo = _combo(["Big Engine", "Key"], [["B"], ["H"]])
    pieces, _ = combo_clock._pieces(classify_combo(combo), {"big engine": big, "key": key}, set())
    hit = 0
    for r in runs:
        t = combo_clock.assemble_turn(r, pieces, [], 0, 12)
        if t is None:
            continue
        hit += 1
        assert r.seen_turn["Key"] <= t and r.seen_turn["Big Engine"] <= t
        assert any(r.mana_available_by_turn[d - 1] >= 6
                   for d in range(r.seen_turn["Big Engine"] or 1, t + 1))
    assert hit > 0


def test_without_summoning_sickness_means_an_earlier_turn(make_card):
    dork = make_card("Tapper", mana_cost="{1}", type_line="Creature — Elf", power="1",
                     toughness="1")
    key = make_card("Key", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 40), (_filler(make_card), 57), (dork, 1), (key, 1)]
    runs = _run(deck, SimConfig(turns=12, runs=300, seed=9, **KEEP_ALL))
    by = {"tapper": dork, "key": key}
    fresh, _ = combo_clock._pieces(classify_combo(_combo(["Tapper", "Key"], [["B"], ["H"]])),
                                   by, set())
    sick, _ = combo_clock._pieces(classify_combo(
        _combo(["Tapper", "Key"], [["B"], ["H"]], untapped=[True, False])), by, set())
    later = 0
    for r in runs:
        a = combo_clock.assemble_turn(r, fresh, [], 0, 12)
        b = combo_clock.assemble_turn(r, sick, [], 0, 12)
        if b is not None:
            # never earlier; later exactly when the creature was the last piece to land
            assert a is not None and b >= a
            later += b > a
    assert later > 0


def test_the_commander_needs_no_draw(make_card):
    cmdr = make_card("Boss", mana_cost="{2}{G}", type_line="Legendary Creature — Elf",
                     power="2", toughness="2", color_identity=("G",))
    key = make_card("Key", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 40), (_filler(make_card), 58), (key, 1)]
    runs = _run(deck, SimConfig(turns=10, runs=300, seed=2, **KEEP_ALL), commander=cmdr)
    tc = _clock(runs, [_combo(["Boss", "Key"], [["C"], ["H"]])], deck, [cmdr]).combos[0]
    seen_by_5 = sum(1 for r in runs if r.seen_turn.get("Key", 99) <= 5) / len(runs)
    assert tc.by_turn[5] == pytest.approx(seen_by_5, abs=1e-3)   # by_turn is rounded


def test_tutors_are_outs_only_for_what_they_can_find(make_card):
    a = make_card("Piece A", mana_cost="{0}", type_line="Creature — Elf", power="1",
                  toughness="1")
    b = make_card("Piece B", mana_cost="{0}", type_line="Instant")
    demonic = make_card("Demonic Tutor", mana_cost="{1}{B}", type_line="Sorcery",
                        oracle_text="Search your library for a card, put that card into your "
                                    "hand, then shuffle.")
    mystical = make_card("Mystical Tutor", mana_cost="{U}", type_line="Instant",
                         oracle_text="Search your library for an instant or sorcery card, "
                                     "reveal it, then shuffle and put that card on top.")
    combo = _combo(["Piece A", "Piece B"], [["H"], ["H"]])
    cfg = SimConfig(turns=10, runs=600, seed=4, **KEEP_ALL)
    base = [(_land(make_card), 40), (_filler(make_card), 53), (a, 1), (b, 1)]
    plain = _clock(_run(base + [(_filler(make_card, "F2"), 4)], cfg), [combo], base).combos[0]
    with_demonic = base + [(demonic, 1), (_filler(make_card, "F2"), 3)]
    tc = _clock(_run(with_demonic, cfg), [combo], with_demonic).combos[0]
    assert tc.tutors == ("Demonic Tutor",)
    assert tc.by_turn[10] > plain.by_turn[10] + 0.03
    with_mystical = base + [(mystical, 1), (_filler(make_card, "F2"), 3)]
    tm = _clock(_run(with_mystical, cfg), [combo], with_mystical).combos[0]
    assert tm.tutors == ("Mystical Tutor",)       # it can find Piece B, the instant, not A


def test_a_top_tutored_piece_arrives_next_turn(make_card):
    from mythgauntlet.sim.tier0 import RunStats
    from mythgauntlet.semantics.tutor_reach import tutor_reach

    a = make_card("Piece A", mana_cost="{0}", type_line="Instant")
    b = make_card("Piece B", mana_cost="{0}", type_line="Instant")
    vamp = make_card("Vampiric Tutor", mana_cost="{B}", type_line="Instant",
                     oracle_text="Search your library for a card, then shuffle and put that "
                                 "card on top. You lose 2 life.")
    pieces, _ = combo_clock._pieces(classify_combo(_combo(["Piece A", "Piece B"],
                                                          [["H"], ["H"]])),
                                    {"piece a": a, "piece b": b}, set())
    run = RunStats(seen_turn={"Piece A": 0, "Vampiric Tutor": 2},
                   mana_available_by_turn=[1, 2, 3, 4, 5])
    assert combo_clock.assemble_turn(run, pieces, [tutor_reach(vamp)], 0, 5) == 3
    run2 = RunStats(seen_turn={"Piece A": 0, "Vampiric Tutor": 2},
                    mana_available_by_turn=[0, 0, 0, 0, 0])
    assert combo_clock.assemble_turn(run2, pieces, [tutor_reach(vamp)], 0, 5) is None


@pytest.mark.parametrize("kw,why", [
    (dict(templates=("Persist Creature",)), "Persist Creature"),
    (dict(zones=[["G"], ["H"]]), "graveyard"),
    (dict(other=[True, False]), "board state"),
    (dict(quantities=[2, 1]), "2 copies"),
])
def test_what_the_clock_cannot_model_is_not_timed_and_says_why(make_card, kw, why):
    a = make_card("Piece A", mana_cost="{0}", type_line="Instant")
    b = make_card("Piece B", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 40), (_filler(make_card), 57), (a, 1), (b, 1)]
    runs = _run(deck, SimConfig(turns=10, runs=50, seed=1, **KEEP_ALL))
    zones = kw.pop("zones", [["H"], ["H"]])
    cc = _clock(runs, [_combo(["Piece A", "Piece B"], zones, **kw)], deck)
    tc = cc.combos[0]
    assert not tc.timed and why in tc.not_timed and "not timed" in tc.text
    assert cc.combo_first_games == 0 and cc.text == "No combo could be timed."


def test_hand_built_combo_without_zones_is_not_timed(make_card):
    a = make_card("Piece A", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 40), (a, 1)]
    runs = _run(deck, SimConfig(turns=5, runs=10, seed=1, **KEEP_ALL))
    combo = Combo(id="x", cards=("Piece A",), produces=("Win the game",), bracket_tag=None,
                  mana_needed="", popularity=None)
    tc = _clock(runs, [combo], deck).combos[0]
    assert not tc.timed and tc.not_timed == "no per-piece zone data"


def test_prerequisites_are_read_or_kept_as_assumptions():
    c = _combo(["Krenko, Mob Boss", "Skirk Prospector"], [["B"], ["B"]],
               easy="Krenko does not have summoning sickness.",
               notable="You control a number of Goblins that is equal to or greater than six "
                       "plus Krenko's commander tax.\nYou have a way to give it lifelink.\n"
                       "Your life total is at least 51.\nYour life total is at least 2.\n"
                       "You have enough mana available to cast Blasphemous Act.")
    pre = combo_clock._prereqs(c, list(c.cards))
    assert pre.untapped == frozenset({"krenko, mob boss"})
    assert pre.board == ((6, "goblin"),)
    assert pre.assumed == ("You have a way to give it lifelink.",
                           "Your life total is at least 51.")
    assert combo_clock._prereqs(
        _combo(["A"], [["H"]], notable="You control at least X Goblins."), ["A"]).assumed


def test_a_board_requirement_is_counted_from_cast_cards(make_card):
    gob = make_card("Goblin Grunt", mana_cost="{1}", type_line="Creature — Goblin", power="1",
                    toughness="1")
    key = make_card("Key", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 40), (gob, 30), (key, 1), (_filler(make_card), 28)]
    runs = _run(deck, SimConfig(turns=10, runs=300, seed=6, **KEEP_ALL))
    free = _clock(runs, [_combo(["Key"], [["H"]])], deck).combos[0]
    needy = _clock(runs, [_combo(["Key"], [["H"]],
                                 notable="You control at least three Goblins.")], deck).combos[0]
    assert needy.assumes == ()
    assert all(needy.by_turn[t] <= free.by_turn[t] for t in free.by_turn)
    assert needy.by_turn[3] < free.by_turn[3]


def test_only_deterministic_unassumed_kills_enter_the_combined_clock(make_card):
    a = make_card("Piece A", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 40), (_filler(make_card), 58), (a, 1)]
    runs = _run(deck, SimConfig(turns=10, runs=200, seed=8, **KEEP_ALL))
    kill = _combo(["Piece A"], [["H"]])
    clean = _clock(runs, [kill], deck)
    assert clean.combo_first_games > 0 and clean.lead_combo == ("Piece A",)
    assert "a combo kills first in" in clean.text
    nd = DeterminismVerdict(deterministic=False, reason="coin", rule="CR 705", markers=("flip",))
    assert _clock(runs, [kill], deck, det=nd).combo_first_games == 0
    adv = _combo(["Piece A"], [["H"]], produces=("Infinite colorless mana",))
    a_tc = _clock(runs, [adv], deck)
    assert a_tc.combo_first_games == 0 and "needs an outlet" in a_tc.combos[0].text
    assumed = _combo(["Piece A"], [["H"]], notable="You have a way to give it lifelink.")
    s = _clock(runs, [assumed], deck)
    assert s.combo_first_games == 0 and "Not counted as a kill" in s.combos[0].text


def test_infinite_tokens_without_haste_kill_the_turn_after(make_card):
    a = make_card("Piece A", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 40), (_filler(make_card), 58), (a, 1)]
    runs = _run(deck, SimConfig(turns=10, runs=200, seed=8, **KEEP_ALL))
    hasty = _clock(runs, [_combo(["Piece A"], [["H"]],
                                 produces=("Infinite creature tokens with haste",))], deck)
    slow = _clock(runs, [_combo(["Piece A"], [["H"]],
                                produces=("Infinite creature tokens",))], deck)
    assert hasty.combos[0].kind == "kill" and slow.combos[0].kind == "kill_next_turn"
    # no damage kill in this deck, so the combined clock is the combo alone, one turn later
    for t in range(4, 11):
        assert slow.by_turn[t] == hasty.by_turn[t - 1]


def test_combined_clock_is_the_earlier_of_damage_and_combo(make_card):
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature — Bear", power="2",
                     toughness="2")
    key = make_card("Key", mana_cost="{0}", type_line="Instant")
    deck = [(_land(make_card), 38), (bear, 53), (key, 8)]
    runs = _run(deck, SimConfig(turns=12, runs=300, seed=10))
    cc = _clock(runs, [_combo(["Key"], [["H"]])], deck, horizon=12)
    tc = cc.combos[0]
    damage = sorted(r.kill_turn for r in runs if r.kill_turn is not None)
    assert cc.killing_games >= len(damage)
    assert cc.median <= damage[len(damage) // 2]
    assert 0 < cc.combo_first_games <= len(runs)
    assert tc.turn_25 is not None and tc.turn_25 <= tc.turn_50


def test_spellbook_variant_keeps_zones_states_and_templates():
    v = {"id": 1, "manaValueNeeded": 0, "produces": [{"feature": {"name": "Win the game"}}],
         "uses": [
             {"card": {"name": "A"}, "zoneLocations": ["B"],
              "battlefieldCardState": "without summoning sickness", "quantity": 1},
             {"card": {"name": "B"}, "zoneLocations": ["H", "G"],
              "battlefieldCardState": "with a +1/+1 counter on it", "quantity": 1},
             {"card": {"name": "C"}, "zoneLocations": ["B"],
              "battlefieldCardState": "without summoning sickness and with power 3 or greater"}],
         "requires": [{"template": {"name": "Haste Enabler"}}]}
    c = _variant_to_combo(v)
    assert c.zones == (("B",), ("H", "G"), ("B",))
    assert c.needs_untapped == (True, False, True)
    assert c.other_state == (False, True, True)
    assert c.quantities == (1, 1, 1) and c.templates == ("Haste Enabler",)
