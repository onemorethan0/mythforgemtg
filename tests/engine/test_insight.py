"""Deck insight: the deck-specific narrative (archetype / gameplan / why / cards / verdict)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mythgauntlet.mentor import verdicts
from mythgauntlet.ratings import reference
from mythgauntlet.ratings.insight import build_insight


def _analysis(**over):
    """A duck-typed DeckAnalysis with sensible defaults; override per test."""
    base = dict(
        ceiling=SimpleNamespace(has_game_ending_combo=False, fast_kill_turn=8.0, score=0.0),
        combo_profile=None,
        go_off=SimpleNamespace(goes_off=False, earliest_turn=None),
        overrun=SimpleNamespace(can_alpha_strike=False),
        report=SimpleNamespace(avg_kill_turn=8.0, commander_cast_rate=0.97,
                               curve_efficiency=0.79, keep_rate=0.79, goldfish_kill_rate=0.16,
                               avg_commander_turn=3.9, consistency_score=85.0),
        interaction=SimpleNamespace(effective_answers=6.7, breadth=2, score=67.0),
        pod=SimpleNamespace(pod_close_turn=13.0, pod_close_rate=0.78, duel_close_rate=0.99,
                            via_finisher=False, score=45.0),
        resilience=SimpleNamespace(resilience_score=80.0),
        wipe_turn=5,
        bracket=SimpleNamespace(bracket=2, label="Core", plays_up=False),
    )
    base.update(over)
    return SimpleNamespace(**base)


def _resolved(cards, commander=None):
    return SimpleNamespace(cards=cards, commanders=[commander] if commander else [])


def _creature(make_card, name, power=3):
    c = make_card(name, mana_cost="{1}{G}", type_line="Creature - Beast", color_identity=("G",))
    c.power, c.toughness = str(power), str(power)
    return c


def _removal(make_card, name):
    return make_card(name, mana_cost="{1}{B}", type_line="Instant",
                     oracle_text="Destroy target creature.", color_identity=("B",))


def _counter(make_card, name):
    return make_card(name, mana_cost="{U}{U}", type_line="Instant",
                     oracle_text="Counter target spell.", color_identity=("U",))


def _wipe(make_card, name):
    return make_card(name, mana_cost="{2}{W}{W}", type_line="Sorcery",
                     oracle_text="Destroy all creatures.", color_identity=("W",))


def _rock(make_card, name):
    return make_card(name, mana_cost="{1}", type_line="Artifact",
                     oracle_text="{T}: Add {C}{C}.")


def _island(make_card):
    return make_card("Island", type_line="Basic Land - Island",
                     produced_mana=("U",), color_identity=("U",))


# --- archetype detection -----------------------------------------------------------------


def test_creature_aggro_archetype(make_card, forest):
    deck = [(forest, 30), (_creature(make_card, "Beater"), 31)]
    ins = build_insight(_resolved(deck), _analysis())
    assert ins.archetype == "Creature aggro"
    assert "races" in ins.gameplan and "31 creatures" in ins.gameplan


def test_control_archetype(make_card):
    deck = [(_island(make_card), 40)]
    for i in range(4):
        deck.append((_counter(make_card, f"Deny{i}"), 1))
        deck.append((_wipe(make_card, f"Sweep{i}"), 1))
    ins = build_insight(_resolved(deck), _analysis())
    assert ins.archetype == "Control"


def test_combo_archetype_wins_out(make_card, forest):
    deck = [(forest, 30), (_creature(make_card, "Body"), 31)]  # would be aggro...
    a = _analysis(ceiling=SimpleNamespace(
        has_game_ending_combo=True, fast_kill_turn=5.0, score=60.0))
    ins = build_insight(_resolved(deck), a)  # ...but a game-ending combo wins the classification
    assert ins.archetype == "Combo"
    assert "combo" in ins.gameplan.lower()


# --- named cards + why + verdict ---------------------------------------------------------


def test_key_cards_names_the_interaction_and_ramp(make_card, forest):
    deck = [
        (forest, 34),
        (_removal(make_card, "Murder"), 1),
        (_wipe(make_card, "Wrath"), 1),
        (_rock(make_card, "Signet"), 1),
        (_creature(make_card, "Bear"), 20),
    ]
    ins = build_insight(_resolved(deck), _analysis())
    roles = {kc.role: kc.names for kc in ins.key_cards}
    assert "Interaction" in roles and {"Murder", "Wrath"} <= set(roles["Interaction"])
    assert "Ramp" in roles and "Signet" in roles["Ramp"]


def test_ceiling_why_explains_a_zero(make_card, forest):
    ins = build_insight(_resolved([(forest, 40), (_creature(make_card, "X"), 20)]), _analysis())
    why = ins.axis_why["Ceiling"]
    assert "no combo" in why and "combat" in why  # the user's example: explains the 0


def _cell(lo, hi, n=100):
    """A reference cell whose p0..p100 grid runs linearly from lo to hi."""
    q = [lo + (hi - lo) * k / 20 for k in range(21)]
    return {"p25": q[5], "p50": q[10], "p75": q[15], "n": n, "none_count": 0, "thin": False, "q": q}


_METRICS = ("consistency", "interaction", "ceiling", "resilience", "pod")


@pytest.fixture
def peers(monkeypatch):
    """Bracket 2 peers spread 0-100 on every metric (rank == score); Bracket 4 peers 60-100."""
    table = {2: {m: _cell(0, 100) for m in _METRICS}, 4: {m: _cell(60, 100) for m in _METRICS}}
    monkeypatch.setattr(reference, "BRACKET_AXIS_REFERENCE", table)
    return table


def test_strengths_and_weaknesses_are_ranked_against_bracket_peers(make_card, forest, peers):
    deck = [(forest, 40), (_creature(make_card, "X"), 20)]
    ins = build_insight(_resolved(deck), _analysis())   # bracket 2: cons 85, inter 67, ceiling 0
    assert ("Consistency: consistent (85/100), better than 85% of Bracket 2 decks -- "
            "commander lands ~T4") \
        in ins.strengths
    assert not any(s.startswith("Interaction") for s in ins.strengths + ins.weaknesses)  # rank 67
    assert any(w.startswith("Ceiling: below all 100 Bracket 2 decks measured (0/100) -- no fast "
                            "finish") for w in ins.weaknesses)
    assert "Wipe resilience: resilient (80/100), higher than 80% of Bracket 2 decks" \
        in ins.strengths
    # the same deck measured at Bracket 4: consistency 85 is only better than 62.5% of peers
    a4 = _analysis(bracket=SimpleNamespace(bracket=4, label="Optimized", plays_up=False))
    ins4 = build_insight(_resolved(deck), a4)
    assert not any(s.startswith("Consistency") for s in ins4.strengths)
    # thin among Bracket 4 peers, yet deep on the absolute band -- both true, both said
    assert ("Interaction: deep (67/100), thinner than 82% of Bracket 4 decks -- 0 answers, "
            "light on removal/counters") in ins4.weaknesses


def test_no_peer_reference_means_no_ranked_lines_but_facts_stay(make_card, forest, monkeypatch):
    monkeypatch.setattr(reference, "BRACKET_AXIS_REFERENCE", {})
    a = _analysis(pod=SimpleNamespace(pod_close_turn=None, pod_close_rate=0.0,
                                      duel_close_rate=0.5, via_finisher=False, score=0.0))
    ins = build_insight(_resolved([(forest, 40)]), a)
    assert ins.strengths == []
    assert ins.weaknesses == ["No multiplayer closing power -- can't pressure a full table"]


def test_a_combo_is_named_only_on_a_peer_ranked_ceiling(make_card, forest, peers):
    combo = SimpleNamespace(has_game_ending_combo=True, fast_kill_turn=5.0, score=90.0)
    ins = build_insight(_resolved([(forest, 40)]), _analysis(ceiling=combo))
    assert "Ceiling: higher than 90% of Bracket 2 decks (90/100) -- a real game-ending combo" \
        in ins.strengths
    # among Bracket 4 peers a combo deck at 70 is ordinary: no ceiling line at all
    combo.score = 70.0
    a4 = _analysis(ceiling=combo, bracket=SimpleNamespace(bracket=4, label="Optimized",
                                                          plays_up=False))
    ins4 = build_insight(_resolved([(forest, 40)]), a4)
    assert not any(t.startswith("Ceiling") for t in ins4.strengths + ins4.weaknesses)


def test_a_peer_line_carries_the_absolute_word_and_never_contradicts_it(make_card, forest, peers):
    """Peer rank and absolute band are both true and are said together: a deck worse than most
    Bracket 4 peers at 51/100 resilience is still MODERATE on its own, and the line must say so
    -- the bare peer rank read to the mentor as "vulnerable to board wipes" (bench 2026-11-08)."""
    a = _analysis(resilience=SimpleNamespace(resilience_score=51.0),
                  bracket=SimpleNamespace(bracket=4, label="Optimized", plays_up=False))
    ins = build_insight(_resolved([(forest, 40)]), a)
    line = next(w for w in ins.weaknesses if w.startswith("Wipe resilience"))
    assert line.startswith("Wipe resilience: moderate (51/100), ") \
        and "vulnerable" not in line
    for verdict_line in ins.strengths + ins.weaknesses:
        assert not verdict_line.lower().startswith(
            ("resilient", "consistent engine", "deep interaction", "shaky", "folds"))
    top = build_insight(_resolved([(forest, 40)]), _analysis())
    assert {verdicts.strength_topic(s) for s in top.strengths} == {"consistency", "resilience"}


def test_absolute_band_is_the_mentors_band():
    from mythgauntlet.ratings.insight import absolute_band
    for axis, band in (("resilience", verdicts.resilience_band),
                       ("consistency", verdicts.consistency_band),
                       ("interaction", verdicts.interaction_band)):
        for score in (0, 29.9, 30, 41.9, 42, 44.9, 45, 54.9, 55, 59.9, 60, 79.9, 80, 100):
            assert absolute_band(axis, score) == band(score), (axis, score)


def test_rank_in_grid_interpolates_and_splits_plateaus():
    grid = [float(5 * k) for k in range(21)]
    assert reference.rank_in_grid(grid, 42.5) == 42.5
    assert reference.rank_in_grid(grid, -1) == 0.0 and reference.rank_in_grid(grid, 101) == 100.0
    flat = [0.0] * 5 + [10.0] * 11 + [20.0] * 5           # p25..p75 all score 10
    assert reference.rank_in_grid(flat, 10.0) == 50.0     # a tie is the plateau's middle
    assert reference.rank_in_grid(flat, 15.0) == 77.5


def test_percentile_rank_orients_lower_is_better_and_declines_thin_cells():
    table = {3: {"avg_kill_turn": _cell(7, 11), "pod": dict(_cell(0, 100), thin=True),
                 "speed": {"p25": 1, "p50": 2, "p75": 3, "n": 50, "thin": False}}}
    fast = reference.percentile_rank(3, "avg_kill_turn", 8.0, table)
    assert fast["rank"] == 25.0 and fast["better_than"] == 75.0
    assert reference.percentile_rank(3, "pod", 50, table) is None       # thin
    assert reference.percentile_rank(3, "speed", 2, table) is None      # pre-B37 cell, no grid
    assert reference.percentile_rank(3, "avg_kill_turn", None, table) is None


def test_the_baked_reference_carries_a_grid_for_every_cell():
    for bracket, cells in reference.BRACKET_AXIS_REFERENCE.items():
        for metric, cell in cells.items():
            assert len(cell["q"]) == 21 and cell["q"] == sorted(cell["q"]), (bracket, metric)


def test_insight_is_deterministic(make_card, forest):
    deck = [(forest, 30), (_creature(make_card, "Beater"), 31), (_removal(make_card, "Kill"), 8)]
    a, b = _analysis(), _analysis()
    assert build_insight(_resolved(deck), a) == build_insight(_resolved(deck), b)


# --- pod fit (casual placement) ----------------------------------------------------------


def test_pod_read_core(make_card, forest):
    ins = build_insight(_resolved([(forest, 40)]), _analysis())  # bracket 2, no plays_up
    assert "Bracket 2" in ins.pod_read and "Core" in ins.pod_read
    assert "leaning Upgraded" not in ins.pod_read


def test_pod_read_core_playing_up(make_card, forest):
    a = _analysis(bracket=SimpleNamespace(bracket=2, label="Core", plays_up=True))
    ins = build_insight(_resolved([(forest, 40)]), a)
    assert "Bracket 2-3" in ins.pod_read and "leaning Upgraded" in ins.pod_read


def test_pod_read_exhibition_playing_up(make_card, forest):
    """plays_up = the strength score sits just under the next bracket's cut (since
    2026-10-18): a Bracket-1 deck that plays up is at the CORE line, and must not read as
    flatly "casual and unoptimized" when the engine itself flagged the ambiguity."""
    a = _analysis(bracket=SimpleNamespace(bracket=1, label="Exhibition", plays_up=True))
    ins = build_insight(_resolved([(forest, 40)]), a)
    assert "Bracket 1" in ins.pod_read
    assert "casual and unoptimized" not in ins.pod_read
    assert "Core" in ins.pod_read


def test_pod_read_upgraded_playing_up_names_the_optimized_line(make_card, forest):
    a = _analysis(bracket=SimpleNamespace(bracket=3, label="Upgraded", plays_up=True))
    ins = build_insight(_resolved([(forest, 40)]), a)
    assert "Bracket 3-4" in ins.pod_read and "Optimized" in ins.pod_read


def test_pod_read_scales_with_bracket(make_card, forest):
    for br, needle in [(1, "Bracket 1"), (3, "Bracket 3"), (4, "Bracket 4"), (5, "cEDH")]:
        a = _analysis(bracket=SimpleNamespace(bracket=br, label="x", plays_up=False))
        ins = build_insight(_resolved([(forest, 40)]), a)
        assert needle in ins.pod_read


def _wall(make_card, name, p, t):
    c = make_card(name, mana_cost="{3}{G}", type_line="Creature - Wall", color_identity=("G",))
    c.power, c.toughness = str(p), str(t)
    return c


def test_key_cards_name_what_the_commander_rewards(make_card):
    # Live 2026-10-23: a Doran, Besieged by Time deck's key cards were Sol Ring / Farseek /
    # Rampant Growth / Swords - nothing Doran rewards. Its walls lead now, biggest gain first.
    doran = make_card("Doran, Besieged by Time", mana_cost="{1}{W}{B}{G}",
                      type_line="Legendary Creature - Treefolk Druid",
                      oracle_text=("Each creature spell you cast with toughness greater than its "
                                   "power costs {1} less to cast.\nWhenever a creature you "
                                   "control attacks or blocks, it gets +X/+X until end of turn, "
                                   "where X is the difference between its power and toughness."))
    blackthorn, druid, bear = (_wall(make_card, "Blighted Blackthorn", 3, 7),
                               _wall(make_card, "Great Forest Druid", 0, 4),
                               _creature(make_card, "Bear", 2))
    ins = build_insight(_resolved([(blackthorn, 1), (druid, 1), (bear, 1)], doran), _analysis())
    first = ins.key_cards[0]
    assert first.role == "Commander synergy"
    assert set(first.names[:2]) == {"Blighted Blackthorn", "Great Forest Druid"}   # +4 each
    assert "Bear" not in first.names
    wins = next(k for k in ins.key_cards if k.role == "Win conditions")
    assert "Blighted Blackthorn" in wins.names                  # hits for 7 under Doran


def test_no_synergy_group_without_a_commander_rule(make_card):
    ins = build_insight(_resolved([(_creature(make_card, "Bear", 2), 1)]), _analysis())
    assert all(k.role != "Commander synergy" for k in ins.key_cards)


# --- the Borg-deck comparison with Archidekt (2026-11-12) -----------------------------------


def test_the_gameplan_counts_ramp_the_way_the_role_table_does(make_card, forest):
    """A cost reducer is ramp as a player counts it (the Breakdown's ramp role) but the old
    sentence count skipped it, so the page said 10 ramp in one place and 14 in another."""
    reducer = make_card("Cost Cutter", mana_cost="{3}", type_line="Artifact",
                        oracle_text="Artifact spells you cast cost {1} less to cast.")
    deck = [(forest, 30), (_creature(make_card, "Body"), 20),
            (_rock(make_card, "Rock A"), 1), (_rock(make_card, "Rock B"), 1), (reducer, 1)]
    ins = build_insight(_resolved(deck), _analysis())
    assert "3 ramp" in ins.gameplan


def _artifact_creature(make_card, name):
    c = make_card(name, mana_cost="{2}", type_line="Artifact Creature - Borg")
    c.power, c.toughness = "2", "2"
    return c


def test_wipes_that_spare_the_decks_own_creatures_do_not_make_it_a_control_deck(make_card):
    spare_type = make_card("Kindred Judgment", mana_cost="{5}{W}{W}", type_line="Sorcery",
                           oracle_text="Choose a creature type. Destroy all creatures that aren't of the chosen type.")
    spare_art = make_card("Battle of Wolf 359", mana_cost="{3}{B}{B}", type_line="Sorcery",
                          oracle_text="All nonartifact creatures get -X/-X until end of turn, "
                                      "where X is the number of artifact creatures you control.")
    deck = [(_island(make_card), 30)]
    deck += [(_artifact_creature(make_card, f"Drone {i}"), 1) for i in range(8)]
    deck += [(_counter(make_card, f"Deny{i}"), 1) for i in range(4)]
    deck += [(spare_type, 1), (spare_art, 1), (_wipe(make_card, "Sweep"), 1)]
    ins = build_insight(_resolved(deck), _analysis())
    assert ins.archetype != "Control"          # 4 counters + 3 wipes was 7; 2 of those wipes spare the Borg


def test_the_same_wipes_still_make_control_in_a_deck_not_built_on_what_they_spare(make_card):
    spare_art = make_card("Battle of Wolf 359", mana_cost="{3}{B}{B}", type_line="Sorcery",
                          oracle_text="All nonartifact creatures get -X/-X until end of turn, "
                                      "where X is the number of artifact creatures you control.")
    deck = [(_island(make_card), 30)]
    deck += [(_counter(make_card, f"Deny{i}"), 1) for i in range(4)]
    deck += [(spare_art, 1), (_wipe(make_card, "Sweep A"), 1), (_wipe(make_card, "Sweep B"), 1)]
    ins = build_insight(_resolved(deck), _analysis())
    assert ins.archetype == "Control"          # no artifact creatures: nothing here is spared
