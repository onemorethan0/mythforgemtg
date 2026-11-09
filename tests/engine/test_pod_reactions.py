"""D5: reactions in a pod. Until 2026-11-08 a 4-player game resolved every spell at once and
skipped the pre-combat instant window, so counterspells and instant removal did nothing at a
table. Now priority goes around the table (CR 117.4): a seat responds only to move the stack
its way, and the spell resolves when every seat with a reason and an answer has passed."""
from __future__ import annotations

from mythgauntlet.agents.greedy import GreedyAgent
from mythgauntlet.sim.game import (
    COUNTER_WINDOW,
    INSTANT_WINDOW,
    CastRemoval,
    CounterSpell,
    GameState,
    PassReaction,
    advance,
    apply,
)
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import DuelConfig, _Permanent, _Player, make_game_card


def _counter(make_card, name="Deny"):
    return make_game_card(make_card(name, mana_cost="{U}{U}", type_line="Instant",
                                    oracle_text="Counter target spell.", color_identity=("U",)), None)


def _murder(make_card, name="Murder"):
    return make_game_card(make_card(name, mana_cost="{B}", type_line="Instant",
                                    oracle_text="Destroy target creature.",
                                    color_identity=("B",)), None)


def _bear(make_card, name="Big Beast"):
    c = make_card(name, mana_cost="{3}{G}", type_line="Creature - Beast", color_identity=("G",))
    c.power, c.toughness = "6", "6"
    return make_game_card(c, None)


def _player(key, hand=(), mana=0, color="U"):
    p = _Player(name=key, library=[], life=40)
    p.hand.extend(hand)
    p.sources.extend(_Source(frozenset({color}), ready=True) for _ in range(mana))
    return p


def _pod(players: dict[str, _Player], active="a") -> GameState:
    return GameState(players=players, order=list(players), cfg=DuelConfig(max_turns=30),
                     active=active)


def _on_stack(state, spell, value=10.0):
    state.pending_spell = (spell, False, value, state.active)
    state.counters_on_stack = 0
    state.phase = COUNTER_WINDOW
    advance(state)


def test_priority_goes_around_the_table_to_the_first_seat_with_a_counter(make_card):
    s = _pod({"a": _player("a"), "b": _player("b"),
              "c": _player("c", [_counter(make_card)], mana=2), "d": _player("d")})
    _on_stack(s, _bear(make_card))
    assert s.pending.player == "c" and s.pending.kind == COUNTER_WINDOW


def test_after_a_counter_only_the_caster_may_respond(make_card):
    """The other opponents want the spell countered too, so they are not asked to flip it
    back; the caster is, and wins the war with a counter of its own."""
    s = _pod({"a": _player("a", [_counter(make_card, "Back")], mana=2),
              "b": _player("b", [_counter(make_card, "B1")], mana=2),
              "c": _player("c", [_counter(make_card, "C1")], mana=2)})
    _on_stack(s, _bear(make_card))
    assert s.pending.player == "b"
    apply(s, CounterSpell(s.players["b"].hand[0]))
    advance(s)
    assert s.pending.player == "a"                      # not c: c also wants it countered
    apply(s, CounterSpell(s.players["a"].hand[0]))
    advance(s)
    assert s.pending.player == "c"                      # the stack changed: c may fight on
    apply(s, PassReaction())
    advance(s)
    # everyone has passed: two counters -> the spell resolves
    assert s.pending_spell is None and s.counters_on_stack == 0
    assert any(p.name == "Big Beast" for p in s.players["a"].battlefield)


def test_a_spell_is_countered_when_an_odd_number_of_counters_stand(make_card):
    s = _pod({"a": _player("a"), "b": _player("b", [_counter(make_card)], mana=2),
              "c": _player("c")})
    _on_stack(s, _bear(make_card))
    apply(s, CounterSpell(s.players["b"].hand[0]))
    advance(s)
    assert s.pending_spell is None
    assert not any(p.name == "Big Beast" for p in s.players["a"].battlefield)


def test_passing_moves_priority_to_the_next_seat(make_card):
    s = _pod({"a": _player("a"), "b": _player("b", [_counter(make_card, "B1")], mana=2),
              "c": _player("c", [_counter(make_card, "C1")], mana=2)})
    _on_stack(s, _bear(make_card))
    apply(s, PassReaction())
    advance(s)
    assert s.pending.player == "c"
    apply(s, PassReaction())
    advance(s)
    assert s.pending_spell is None                      # all passed -> resolved
    assert any(p.name == "Big Beast" for p in s.players["a"].battlefield)


def test_the_greedy_seat_counters_only_a_spell_worth_fighting_over(make_card):
    s = _pod({"a": _player("a"), "b": _player("b", [_counter(make_card)], mana=2),
              "c": _player("c")})
    _on_stack(s, _bear(make_card), value=1.0)           # below _COUNTER_MIN_VALUE
    assert isinstance(GreedyAgent().decide(s), PassReaction)


def test_the_pod_gets_an_instant_window_in_seat_order(make_card):
    beast = _Permanent(name="Threat", power=6, toughness=6, is_creature=True, sick=False)
    a = _player("a")
    a.battlefield.append(beast)
    s = _pod({"a": a, "b": _player("b"),
              "c": _player("c", [_murder(make_card)], mana=1, color="B"),
              "d": _player("d", [_murder(make_card, "Doom")], mana=1, color="B")})
    s.phase = "post_main"
    advance(s)
    assert s.phase == INSTANT_WINDOW and s.pending.player == "c"
    apply(s, PassReaction())
    advance(s)
    assert s.pending.player == "d"
    apply(s, CastRemoval(s.players["d"].hand[0]))
    advance(s)
    assert beast not in a.battlefield
    # nothing left to remove: the window closed and the game moved on (with no attackers and
    # empty libraries it runs past combat into the next turn)
    assert s.phase != INSTANT_WINDOW and s.reaction_passed == frozenset()
