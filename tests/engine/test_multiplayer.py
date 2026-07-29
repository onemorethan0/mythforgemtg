"""4-player (pod) adversarial games: the N-player Tier-2 engine (offline, synthetic).

The 1v1 engine is byte-identical (test_tier2_golden guards that); these exercise the N>2
paths: turn rotation over living seats, elimination, last-standing / adjudicated win, a full
4-player game driven by GreedyAgents, and multi-opponent "each" effect scaling (drains/draw/
mass damage/wipes hit the whole table; single-target effects hit the primary opponent).
"""

from __future__ import annotations

import json

from mythgauntlet.agents.greedy import GreedyAgent
from mythgauntlet.semantics.interpreter import ResolvedEffect
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.game import (
    MAIN,
    CastSpell,
    GameState,
    _adjudicate,
    _register_deaths,
    _to_next_halfturn,
    advance,
    apply,
    play_table,
)
from mythgauntlet.sim.rng import SeededRng
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import (
    DeathEffect,
    DuelConfig,
    _apply_resolved,
    _kill,
    _Permanent,
    _Player,
    build_game_cards,
    make_game_card,
)


def _creature(make_card, name, power, cost="{1}{G}"):
    c = make_card(name, mana_cost=cost, type_line="Creature - Beast", color_identity=("G",))
    c.power, c.toughness = str(power), str(power)
    return c


def _greedy_agents(n: int) -> dict[str, object]:
    return {chr(ord("a") + i): GreedyAgent() for i in range(n)}


def _seat(make_card, forest, big=3):
    beast = _creature(make_card, "Beast", big)
    return build_game_cards([(forest, 24), (beast, 36)], None), None, ()


def _do_nothing(make_card, forest):
    return build_game_cards([(forest, 60)], None), None, ()


# --- state helpers (unit) ----------------------------------------------------------------


def _player(key, life=40, score_power=0):
    p = _Player(name=key, library=[], life=life)
    if score_power:
        p.battlefield.append(
            _Permanent(name="body", power=score_power, toughness=score_power,
                       is_creature=True, sick=False)
        )
    return p


def _state(keys, **kw):
    players = {k: _player(k, **kw.pop(k, {})) for k in keys}
    return GameState(players=players, order=list(keys), cfg=DuelConfig(max_turns=30),
                     active=keys[0], **kw)


def test_primary_opponent_is_the_biggest_threat():
    # active 'a'; opponents b (small), c (big board), d (small) -> primary is c.
    players = {
        "a": _player("a"), "b": _player("b", score_power=1),
        "c": _player("c", score_power=9), "d": _player("d", score_power=1),
    }
    st = GameState(players=players, order=["a", "b", "c", "d"], cfg=DuelConfig(), active="a")
    assert st.other == "c"
    assert {p.name for p in st.opponents_of("a")} == {"b", "c", "d"}


def test_register_deaths_eliminates_and_finishes():
    players = {k: _player(k) for k in "abcd"}
    players["b"].life = 0
    players["c"].life = -3
    st = GameState(players=players, order=list("abcd"), cfg=DuelConfig(), active="a", turn=5)
    assert _register_deaths(st) is False  # b, c out; a and d remain -> game continues
    assert st.eliminated == {"b", "c"}
    players["d"].life = 0
    assert _register_deaths(st) is True  # only a remains
    assert st.result == ("a", 5, "eliminated")


def test_turn_rotation_skips_eliminated_seats():
    st = _state("abcd")
    st.eliminated = {"b"}
    st.pos, st.active, st.phase = 0, "a", "next"
    _to_next_halfturn(st)
    assert st.active == "c"  # b is skipped
    assert st.turn == 1


def test_turn_increments_after_a_full_round():
    st = _state("abcd")
    st.pos, st.active, st.phase = 3, "d", "next"  # last seat -> wrap to a, turn++
    _to_next_halfturn(st)
    assert st.active == "a" and st.turn == 2


def test_adjudicate_picks_highest_score_survivor():
    players = {
        "a": _player("a", score_power=2), "b": _player("b", score_power=9),
        "c": _player("c", score_power=1),
    }
    st = GameState(players=players, order=list("abc"), cfg=DuelConfig(max_turns=30), active="a")
    _adjudicate(st)
    assert st.result[0] == "b" and st.result[2] == "adjudicated"


# --- multi-opponent "each" effect scaling (stage 2) --------------------------------------


def test_each_opponent_drain_scales_to_all_pod_opponents():
    me, o1, o2, o3 = _player("a"), _player("b"), _player("c"), _player("d")
    eff = ResolvedEffect(op="lose_life", params={"who": "each_opponent", "amount": 3})
    _apply_resolved(eff, me, o1, None, others=(o2, o3))
    assert o1.life == o2.life == o3.life == 37  # every opponent drained
    assert me.life == 40  # the caster does not drain itself


def test_single_target_drain_hits_only_the_primary_opponent():
    me, o1, o2, o3 = _player("a"), _player("b"), _player("c"), _player("d")
    eff = ResolvedEffect(op="lose_life", params={"who": "opponent", "amount": 3})
    _apply_resolved(eff, me, o1, None, others=(o2, o3))
    assert o1.life == 37 and o2.life == 40 and o3.life == 40  # primary only


def test_each_opponent_draw_and_damage_scale():
    me, o1, o2, o3 = _player("a"), _player("b"), _player("c"), _player("d")
    for p in (o1, o2, o3):
        p.library = [None] * 3  # something to draw
    _apply_resolved(ResolvedEffect(op="draw", params={"who": "each_opponent", "count": 1}),
                    me, o1, None, others=(o2, o3))
    assert len(o1.hand) == len(o2.hand) == len(o3.hand) == 1
    _apply_resolved(
        ResolvedEffect(op="deal_damage", params={"amount": 2, "target": {"type": "opponent",
                       "count": "all"}}), me, o1, None, others=(o2, o3))
    assert o1.life == o2.life == o3.life == 38


def test_board_wipe_clears_every_pod_opponents_board():
    me, o1, o2, o3 = _player("a"), _player("b"), _player("c"), _player("d")
    for p in (me, o1, o2, o3):
        p.battlefield.append(
            _Permanent(name="body", power=2, toughness=2, is_creature=True, sick=False)
        )
    _apply_resolved(
        ResolvedEffect(op="destroy", params={"target": {"type": "creature", "count": "all"}}),
        me, o1, None, others=(o2, o3))
    assert all(not p.creatures() for p in (me, o1, o2, o3))  # the whole table is swept


def test_drain_deck_wins_a_four_player_pod(make_card, forest, tmp_path):
    # a seat whose permanents drain EACH opponent should race a pod of do-nothing decks: the
    # drain must hit all three or it can't close before the turn cap.
    wastes = make_card("Wastes", type_line="Basic Land", produced_mana=("C",))
    drainer = make_card("Table Drainer", mana_cost="{1}", type_line="Enchantment")
    (tmp_path / "authored").mkdir()
    (tmp_path / "authored" / "table-drainer.json").write_text(json.dumps({
        "card": {"name": "Table Drainer"},
        "ccm": {"name": "Table Drainer", "ccm_version": 1, "cost": {"mana": "{1}"},
                "abilities": [{"kind": "triggered", "trigger": {"event": "upkeep"},
                               "effects": [{"op": "lose_life", "amount": 3,
                                            "who": "each_opponent"}]}]},
    }), encoding="utf-8")
    store = SemanticsStore(authored=tmp_path / "authored", compiled=tmp_path / "none")
    drain_deck = build_game_cards([(wastes, 20), (drainer, 20)], store)
    seats = [(drain_deck, None, ())] + [_do_nothing(make_card, forest) for _ in range(3)]
    cfg = DuelConfig(max_turns=40, start_life=20)
    winner, _turns, _reason = play_table(seats, cfg, SeededRng(5), _greedy_agents(4))
    assert winner == "a"  # only the drainer can end the game


# --- stage 3: death drains + opponent-cast fan-out ---------------------------------------


def test_death_drain_scales_to_all_pod_opponents():
    # An aristocrat (Blood Artist class) dying drains EACH of its controller's opponents.
    me, o1, o2, o3 = _player("a"), _player("b"), _player("c"), _player("d")
    aristocrat = _Permanent(name="Blood Artist", power=0, toughness=1, is_creature=True,
                            death=DeathEffect(drain=1))
    me.battlefield.append(aristocrat)
    _kill(me, aristocrat, o1, others=(o2, o3))  # combat/removal pass the owner's other opponents
    assert o1.life == o2.life == o3.life == 39  # every opponent drained
    assert me.life == 40  # the owner is not drained


def test_death_drain_single_target_in_1v1_unchanged():
    me, opp = _player("a"), _player("b")
    aristocrat = _Permanent(name="Blood Artist", power=0, toughness=1, is_creature=True,
                            death=DeathEffect(drain=2))
    me.battlefield.append(aristocrat)
    _kill(me, aristocrat, opp)  # no `others` -> 1v1 behaviour identical
    assert opp.life == 38


def _taxer_perm():
    ability = {"kind": "triggered", "trigger": {"event": "opponent_casts_spell"},
               "effects": [{"op": "deal_damage", "amount": 2, "target": {"type": "opponent"}}]}
    return _Permanent(name="Taxer", power=0, toughness=2, is_creature=True, sick=False,
                      triggers=(("opponent_casts_spell", ability),))


def test_opponent_cast_taxers_fan_out_to_every_opponent(make_card):
    # b and c each have a "whenever an opponent casts, deal 2 to them" taxer; d does not.
    # When a casts, BOTH taxers punish the caster -> a takes 4.
    beast = make_game_card(_creature(make_card, "Beast", 4), None)
    a = _Player(name="a", library=[], hand=[beast],
                sources=[_Source(frozenset({"G"})), _Source(frozenset({"G"}))], life=40)
    b = _Player(name="b", library=[], battlefield=[_taxer_perm()], life=40)
    c = _Player(name="c", library=[], battlefield=[_taxer_perm()], life=40)
    d = _Player(name="d", library=[], life=40)
    st = GameState(players={"a": a, "b": b, "c": c, "d": d}, order=list("abcd"),
                   cfg=DuelConfig(max_turns=30), active="a", phase=MAIN)
    st.land_played = True
    advance(st)
    apply(st, CastSpell(beast))
    assert a.life == 36  # two taxers x 2 damage each


# --- full games (integration) ------------------------------------------------------------


def test_four_player_game_completes_with_a_living_winner(make_card, forest):
    seats = [_seat(make_card, forest) for _ in range(4)]
    cfg = DuelConfig(max_turns=30, start_life=40)
    winner, turns, _reason = play_table(seats, cfg, SeededRng(7), _greedy_agents(4))
    assert winner in {"a", "b", "c", "d", "draw"}
    assert 1 <= turns <= 30


def test_aggro_seat_wins_a_pod_of_do_nothing(make_card, forest):
    # seat 'a' can attack; b/c/d are pure lands -> a eliminates the table and wins.
    seats = [
        (build_game_cards([(forest, 20), (_creature(make_card, "Hasty", 6), 40)], None), None, ()),
        _do_nothing(make_card, forest),
        _do_nothing(make_card, forest),
        _do_nothing(make_card, forest),
    ]
    cfg = DuelConfig(max_turns=40, start_life=20)
    winner, _turns, _reason = play_table(seats, cfg, SeededRng(3), _greedy_agents(4))
    assert winner == "a"


def test_pod_game_is_deterministic(make_card, forest):
    seats = [_seat(make_card, forest) for _ in range(4)]
    cfg = DuelConfig(max_turns=30, start_life=40)
    r1 = play_table(seats, cfg, SeededRng(11), _greedy_agents(4))
    # rebuild seats (play_table shuffles the libraries it's given in place via rng)
    seats2 = [_seat(make_card, forest) for _ in range(4)]
    r2 = play_table(seats2, cfg, SeededRng(11), _greedy_agents(4))
    assert r1 == r2
