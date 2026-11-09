"""Draw-go (2026-11-08): the end-of-turn window. The next seat in turn order -- the one that
untaps next -- may cast instant-speed spells that aren't counterspells in the active player's
end step, spending the mana it held up."""
from __future__ import annotations

from mythgauntlet.agents.greedy import GreedyAgent
from mythgauntlet.sim.game import (
    EOT_WINDOW,
    MAIN,
    CastSpell,
    Decision,
    GameState,
    Pass,
    advance,
    apply,
    eot_castable,
    instant_speed,
)
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import DuelConfig, _Player, make_game_card


def _gc(make_card, name, cost, type_line, text="", **kw):
    return make_game_card(make_card(name, mana_cost=cost, type_line=type_line,
                                    oracle_text=text, **kw), None)


def _draw_two(make_card, name="Think Twice"):
    return _gc(make_card, name, "{1}{U}", "Instant", "Draw two cards.", color_identity=("U",))


def _flash_bear(make_card):
    gc = _gc(make_card, "Ambush Bear", "{1}{G}", "Creature - Bear", "Flash", color_identity=("G",))
    gc.card.power = gc.card.toughness = "3"
    return gc


def _player(key, hand=(), mana=0, color="U", library=0):
    p = _Player(name=key, library=[], life=40)
    p.hand.extend(hand)
    p.sources.extend(_Source(frozenset({color}), ready=True) for _ in range(mana))
    return p


def test_instant_speed_reads_the_type_and_a_flash_line_only(make_card):
    assert instant_speed(_draw_two(make_card))
    assert instant_speed(_flash_bear(make_card))
    flashback = _gc(make_card, "Think Again", "{1}{U}", "Sorcery",
                    "Draw two cards.\nFlashback {3}{U}")
    assert not instant_speed(flashback)
    assert not instant_speed(_gc(make_card, "Bear", "{1}{G}", "Creature - Bear"))


def test_counterspells_are_never_offered_at_end_of_turn(make_card):
    counter = _gc(make_card, "Counterspell", "{U}{U}", "Instant", "Counter target spell.")
    p = _player("b", [counter, _draw_two(make_card)], mana=2)
    assert [gc.card.name for gc in eot_castable(p)] == ["Think Twice"]


def test_only_the_next_seat_gets_the_window(make_card):
    s = GameState(players={"a": _player("a"),
                           "b": _player("b", [_draw_two(make_card, "B Draw")], mana=2),
                           "c": _player("c", [_draw_two(make_card, "C Draw")], mana=2)},
                  order=["a", "b", "c"], cfg=DuelConfig(max_turns=30), active="a")
    s.phase = "end_step"
    advance(s)
    assert s.pending == Decision("b", EOT_WINDOW)


def test_greedy_casts_its_draw_spell_at_end_of_turn(make_card):
    b = _player("b", [_draw_two(make_card)], mana=2)
    b.library.extend(_draw_two(make_card, f"L{i}") for i in range(5))
    s = GameState(players={"a": _player("a"), "b": b}, order=["a", "b"],
                  cfg=DuelConfig(max_turns=30), active="a")
    s.phase = "end_step"
    advance(s)
    action = GreedyAgent().decide(s)
    assert isinstance(action, CastSpell) and action.card.card.name == "Think Twice"
    apply(s, action)
    assert len(b.hand) == 2 and not any(src.ready for src in b.sources)


def test_a_flash_creature_cast_at_end_of_turn_can_attack_on_its_owner_s_turn(make_card):
    bear = _flash_bear(make_card)
    b = _player("b", [bear], mana=2, color="G")
    b.library.extend(_flash_bear(make_card) for _ in range(5))
    a = _player("a")
    a.library.extend(_flash_bear(make_card) for _ in range(5))
    s = GameState(players={"a": a, "b": b}, order=["a", "b"], cfg=DuelConfig(max_turns=30),
                  active="a")
    s.phase = "end_step"
    advance(s)
    apply(s, CastSpell(bear))
    body = next(p for p in b.battlefield if p.name == "Ambush Bear")
    advance(s)                                 # nothing else castable: a's turn ends, b's starts
    assert s.active == "b" and not body.sick


def test_greedy_holds_instant_draw_for_end_of_turn(make_card):
    """(Rituals are the exception and still cast in the main phase: test_tier2_cedh's
    test_ritual_enables_a_bigger_cast_same_turn pins that.)"""
    me = _player("a", [_draw_two(make_card)], mana=2)
    s = GameState(players={"a": me, "b": _player("b")}, order=["a", "b"],
                  cfg=DuelConfig(max_turns=30), active="a", phase=MAIN, land_played=True)
    s.pending = Decision("a", MAIN)
    assert isinstance(GreedyAgent().decide(s), Pass)       # waits for the end-of-turn window
