"""Reactions as explicit search decisions (Phase 7): counters and instant removal are now
COUNTER_WINDOW / INSTANT_WINDOW decision nodes an agent chooses, not auto-resolved greedy.

Offline/synthetic. Proves: the windows are exposed as legal actions, the mechanics (counter
LIFO parity, removal) resolve correctly through apply(), GreedyAgent reproduces the old value
gate + choice, and ISMCTS can counter a spell the greedy gate would let resolve.
"""

from __future__ import annotations

from mythgauntlet.agents.greedy import GreedyAgent
from mythgauntlet.agents.ismcts import ISMCTSAgent
from mythgauntlet.sim.game import (
    COMBAT_ATTACK,
    COUNTER_WINDOW,
    INSTANT_WINDOW,
    MAIN,
    CastSpell,
    Decision,
    GameState,
    PassReaction,
    advance,
    apply,
    legal_actions,
)
from mythgauntlet.sim.rng import SeededRng
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import DuelConfig, _Permanent, _Player, make_game_card


def _gc(card):
    return make_game_card(card, None)


def _counter(make_card, name="Deny", cost="{U}{U}"):
    return make_card(name, mana_cost=cost, type_line="Instant",
                     oracle_text="Counter target spell.", color_identity=("U",))


def _instant_kill(make_card, name="Murder", cost="{B}"):
    return make_card(name, mana_cost=cost, type_line="Instant",
                     oracle_text="Destroy target creature.", color_identity=("B",))


def _creature(make_card, name, cost, power, toughness, **kw):
    card = make_card(name, mana_cost=cost, type_line="Creature - Beast", **kw)
    card.power, card.toughness = str(power), str(toughness)
    return card


def _src(color="U", ready=True):
    return _Source(frozenset({color}), ready=ready)


def _state(a: _Player, b: _Player, phase: str = MAIN, turn: int = 3) -> GameState:
    st = GameState(players={"a": a, "b": b}, order=["a", "b"], cfg=DuelConfig(),
                   active="a", phase=phase, turn=turn)
    st.land_played = True  # skip the land drop in these focused scenarios
    return st


# --- a cast opens a searched counter window ----------------------------------------------


def test_cast_opens_counter_window_for_the_reactor(make_card):
    beast = _gc(_creature(make_card, "Beast", "{G}", 4, 4, color_identity=("G",)))
    a = _Player(name="a", library=[], hand=[beast], sources=[_src("G")])
    b = _Player(name="b", library=[], hand=[_gc(_counter(make_card))],
                sources=[_src(), _src()], life=40)
    st = _state(a, b)
    advance(st)
    assert st.pending == Decision("a", MAIN)
    apply(st, CastSpell(beast))          # beast goes on the stack
    advance(st)
    assert st.pending == Decision("b", COUNTER_WINDOW)  # the reactor decides
    keys = {type(x).__name__ for x in legal_actions(st)}
    assert keys == {"PassReaction", "CounterSpell"}


def test_no_counter_window_when_reactor_has_no_answer(make_card):
    beast = _gc(_creature(make_card, "Beast", "{G}", 4, 4, color_identity=("G",)))
    a = _Player(name="a", library=[], hand=[beast], sources=[_src("G")])
    b = _Player(name="b", library=[], hand=[], sources=[_src(), _src()], life=40)  # no counter
    st = _state(a, b)
    advance(st)
    apply(st, CastSpell(beast))
    advance(st)  # reactor can't counter -> spell resolves, no decision, back to caster's MAIN
    assert st.pending == Decision("a", MAIN)
    assert any(p.name == "Beast" for p in a.battlefield)  # resolved


# --- counter mechanics through apply() ---------------------------------------------------


def _cast_and_reach_counter_window(make_card, a_hand_counter=False):
    beast = _gc(_creature(make_card, "Beast", "{G}", 4, 4, color_identity=("G",)))
    a_hand = [beast]
    if a_hand_counter:
        a_hand.append(_gc(_counter(make_card, "Protect")))
    a = _Player(name="a", library=[], hand=a_hand, sources=[_src("G"), _src("U"), _src("U")])
    b = _Player(name="b", library=[], hand=[_gc(_counter(make_card))],
                sources=[_src(), _src()], life=40)
    st = _state(a, b)
    advance(st)
    apply(st, CastSpell(beast))
    advance(st)
    return st, a, b, beast


def test_counter_resolves_to_countered(make_card):
    st, a, b, _ = _cast_and_reach_counter_window(make_card)
    counter = legal_actions(st)[1]  # the CounterSpell action
    apply(st, counter)
    advance(st)  # caster has no counter-back -> spell is countered (1 counter, odd)
    assert not any(p.name == "Beast" for p in a.battlefield)
    assert b.hand == []  # counter spent
    assert st.pending == Decision("a", MAIN)


def test_pass_reaction_resolves_the_spell(make_card):
    st, a, b, _ = _cast_and_reach_counter_window(make_card)
    apply(st, PassReaction())
    advance(st)
    assert any(p.name == "Beast" for p in a.battlefield)  # resolved
    assert len(b.hand) == 1  # counter kept


def test_counter_war_lifo_parity_resolves_the_spell(make_card):
    # b counters; a counters back -> two counters -> original resolves.
    st, a, b, _ = _cast_and_reach_counter_window(make_card, a_hand_counter=True)
    apply(st, legal_actions(st)[1])   # b: CounterSpell
    advance(st)
    assert st.pending == Decision("a", COUNTER_WINDOW)  # priority passes to the caster
    apply(st, legal_actions(st)[1])   # a: CounterSpell (counter-back)
    advance(st)
    assert any(p.name == "Beast" for p in a.battlefield)  # 2 counters -> resolves
    assert b.hand == [] and not any(g.card.name == "Protect" for g in a.hand)


# --- instant-removal window --------------------------------------------------------------


def test_instant_window_is_a_searched_removal_decision(make_card):
    threat = _Permanent(name="Threat", power=6, toughness=6, is_creature=True, sick=False)
    a = _Player(name="a", library=[], battlefield=[threat], sources=[], life=40)
    b = _Player(name="b", library=[], hand=[_gc(_instant_kill(make_card))],
                sources=[_src("B")], life=40)
    st = _state(a, b, phase=INSTANT_WINDOW)
    advance(st)
    assert st.pending == Decision("b", INSTANT_WINDOW)
    names = {type(x).__name__ for x in legal_actions(st)}
    assert names == {"PassReaction", "CastRemoval"}
    apply(st, legal_actions(st)[1])  # CastRemoval
    advance(st)
    assert not any(p.name == "Threat" for p in a.battlefield)  # killed
    assert st.phase != INSTANT_WINDOW  # progressed past the window (no threat left to answer)


def test_instant_window_pass_goes_to_combat(make_card):
    threat = _Permanent(name="Threat", power=6, toughness=6, is_creature=True, sick=False)
    a = _Player(name="a", library=[], battlefield=[threat], sources=[], life=40)
    b = _Player(name="b", library=[], hand=[_gc(_instant_kill(make_card))],
                sources=[_src("B")], life=40)
    st = _state(a, b, phase=INSTANT_WINDOW)
    advance(st)
    apply(st, PassReaction())
    advance(st)
    assert any(p.name == "Threat" for p in a.battlefield)  # kept
    assert st.pending == Decision("a", COMBAT_ATTACK)


# --- GreedyAgent reproduces the old value gate + choice ----------------------------------


def _counter_window_state(make_card, spell_value: float):
    beast = _gc(_creature(make_card, "Beast", "{G}", 4, 4, color_identity=("G",)))
    a = _Player(name="a", library=[], sources=[])
    b = _Player(name="b", library=[], hand=[_gc(_counter(make_card))],
                sources=[_src(), _src()], life=40)
    st = _state(a, b, phase=COUNTER_WINDOW)
    st.pending_spell = (beast, False, spell_value, "a")
    st.reaction_actor = "b"
    advance(st)
    return st


def test_greedy_counters_valuable_spell(make_card):
    st = _counter_window_state(make_card, spell_value=10.0)
    assert type(GreedyAgent().decide(st)).__name__ == "CounterSpell"


def test_greedy_passes_cheap_spell(make_card):
    st = _counter_window_state(make_card, spell_value=1.0)  # below _COUNTER_MIN_VALUE
    assert isinstance(GreedyAgent().decide(st), PassReaction)


# --- ISMCTS can counter a spell the greedy gate would let resolve ------------------------


def test_ismcts_counters_a_lethal_spell_greedy_would_ignore(make_card):
    """The pending spell is valued below the greedy counter threshold (greedy would Pass), but
    if it resolves it is a lethal 12/12 that ends the game for the reactor. ISMCTS, searching
    the reaction, should counter it -- a decision greedy cannot make."""
    swamp = make_card("Swamp", type_line="Basic Land - Swamp",
                      produced_mana=("B",), color_identity=("B",))
    bomb = _gc(_creature(make_card, "Bomb", "{6}", 12, 12))  # resolves onto a's board
    a = _Player(name="a", library=[_gc(swamp)] * 20, hand=[], sources=[], life=40)
    b = _Player(name="b", library=[_gc(swamp)] * 20, hand=[_gc(_counter(make_card))],
                sources=[_src(), _src()], life=6)  # low life: the bomb is lethal fast
    st = _state(a, b, phase=COUNTER_WINDOW, turn=4)
    st.pending_spell = (bomb, False, 2.0, "a")  # value 2.0 < _COUNTER_MIN_VALUE (greedy Passes)
    st.reaction_actor = "b"
    advance(st)
    assert st.pending == Decision("b", COUNTER_WINDOW)
    assert isinstance(GreedyAgent().decide(st), PassReaction)  # greedy would let it resolve
    agent = ISMCTSAgent(iterations=250, rng=SeededRng(20260721))
    assert type(agent.decide(st)).__name__ == "CounterSpell"  # search chooses to counter


def test_reaction_search_is_deterministic(make_card):
    def run():
        swamp = make_card("Swamp", type_line="Basic Land - Swamp",
                          produced_mana=("B",), color_identity=("B",))
        bomb = _gc(_creature(make_card, "Bomb", "{6}", 12, 12))
        a = _Player(name="a", library=[_gc(swamp)] * 20, hand=[], sources=[], life=40)
        b = _Player(name="b", library=[_gc(swamp)] * 20, hand=[_gc(_counter(make_card))],
                    sources=[_src(), _src()], life=6)
        st = _state(a, b, phase=COUNTER_WINDOW, turn=4)
        st.pending_spell = (bomb, False, 2.0, "a")
        st.reaction_actor = "b"
        advance(st)
        return type(ISMCTSAgent(iterations=120, rng=SeededRng(7)).decide(st)).__name__

    assert run() == run()
