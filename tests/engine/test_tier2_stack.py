"""Tier-2 reactive interaction: the stack + instant-timing MVP (offline, synthetic)."""

from __future__ import annotations

from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import (
    _MAX_RESERVE,
    DuelConfig,
    _counter_chain,
    _find_counter,
    _instant_window,
    _main_phase,
    _Permanent,
    _Player,
    _reactive_reserve,
    duel,
    make_game_card,
)

# --- helpers -----------------------------------------------------------------------------


def _gc(card):
    return make_game_card(card, None)  # rung-1 profile (no store)


def _counter(make_card, name="Deny", cost="{U}{U}"):
    return make_card(
        name, mana_cost=cost, type_line="Instant",
        oracle_text="Counter target spell.", color_identity=("U",),
    )


def _instant_kill(make_card, name="Murder", cost="{B}"):
    return make_card(
        name, mana_cost=cost, type_line="Instant",
        oracle_text="Destroy target creature.", color_identity=("B",),
    )


def _creature(make_card, name, cost, power, toughness, **kw):
    card = make_card(name, mana_cost=cost, type_line="Creature — Beast", **kw)
    card.power, card.toughness = str(power), str(toughness)
    return card


def _src(color="U", ready=True):
    return _Source(frozenset({color}), ready=ready)


# --- profile exposes counter / instant ---------------------------------------------------


def test_profile_flags_counterspell_and_instant(make_card):
    p = _gc(_counter(make_card)).profile
    assert p.counter is True and p.is_instant is True


def test_profile_sorcery_is_not_instant(make_card):
    sorc = make_card("Slay", mana_cost="{B}", type_line="Sorcery",
                     oracle_text="Destroy target creature.")
    p = _gc(sorc).profile
    assert p.is_instant is False and p.counter is False


# --- reserve / find-counter --------------------------------------------------------------


def test_reactive_reserve_holds_cheapest_answer(make_card):
    two = _gc(_counter(make_card, "C2", "{U}{U}"))       # mv 2
    one = _gc(_instant_kill(make_card, "Zap", "{B}"))    # mv 1
    p = _Player(name="p", library=[], hand=[two, one])
    assert _reactive_reserve(p) == 1  # cheapest instant answer


def test_reactive_reserve_capped_and_zero(make_card):
    big = _gc(_counter(make_card, "Big Deny", "{5}{U}{U}"))  # mv 7
    assert _reactive_reserve(_Player(name="p", library=[], hand=[big])) == _MAX_RESERVE
    assert _reactive_reserve(_Player(name="p", library=[], hand=[])) == 0


def test_find_counter_requires_counter_instant_and_mana(make_card):
    counter = _gc(_counter(make_card))  # {U}{U}
    payable = _Player(name="p", library=[], hand=[counter], sources=[_src(), _src()])
    assert _find_counter(payable)[0] is counter
    short = _Player(name="p", library=[], hand=[counter], sources=[_src()])
    assert _find_counter(short) is None  # can't pay
    burn = _gc(make_card("Bolt", mana_cost="{R}", type_line="Instant",
                         oracle_text="Deal 3 damage to any target."))
    not_a_counter = _Player(name="p", library=[], hand=[burn], sources=[_src("R")])
    assert _find_counter(not_a_counter) is None


# --- counter-war chain (LIFO parity) -----------------------------------------------------


def test_counter_chain_single_counter_counters_the_spell(make_card):
    responder = _Player(name="r", library=[], hand=[_gc(_counter(make_card))],
                        sources=[_src(), _src()])
    caster = _Player(name="c", library=[], sources=[])
    assert _counter_chain(caster, responder, spell_value=10.0) is True
    assert responder.hand == []  # counter spent


def test_counter_chain_counter_war_resolves_the_spell(make_card):
    responder = _Player(name="r", library=[], hand=[_gc(_counter(make_card))],
                        sources=[_src(), _src()])
    caster = _Player(name="c", library=[], hand=[_gc(_counter(make_card, "Protect"))],
                     sources=[_src(), _src()])
    # responder counters; caster counters back -> two counters -> original resolves
    assert _counter_chain(caster, responder, spell_value=10.0) is False
    assert responder.hand == [] and caster.hand == []


def test_counter_chain_skips_cheap_spells(make_card):
    responder = _Player(name="r", library=[], hand=[_gc(_counter(make_card))],
                        sources=[_src(), _src()])
    caster = _Player(name="c", library=[], sources=[])
    assert _counter_chain(caster, responder, spell_value=1.0) is False
    assert len(responder.hand) == 1  # not worth countering -> counter kept


# --- instant-removal window --------------------------------------------------------------


def test_instant_window_kills_biggest_threat(make_card):
    active = _Player(name="a", library=[])
    active.battlefield = [
        _Permanent(name="Small", power=2, toughness=2, is_creature=True, sick=False),
        _Permanent(name="Big", power=5, toughness=5, is_creature=True, sick=False),
    ]
    reactor = _Player(name="r", library=[], hand=[_gc(_instant_kill(make_card))],
                      sources=[_src("B")])
    _instant_window(reactor, active)
    names = {p.name for p in active.creatures()}
    assert "Big" not in names and "Small" in names
    assert reactor.hand == []


def test_instant_window_ignores_sorcery_removal(make_card):
    active = _Player(name="a", library=[])
    active.battlefield = [_Permanent(name="Big", power=5, toughness=5, is_creature=True,
                                     sick=False)]
    sorc = make_card("Slay", mana_cost="{B}", type_line="Sorcery",
                     oracle_text="Destroy target creature.")
    reactor = _Player(name="r", library=[], hand=[_gc(sorc)], sources=[_src("B")])
    _instant_window(reactor, active)
    assert len(active.creatures()) == 1  # sorcery can't fire at instant speed
    assert len(reactor.hand) == 1


# --- integration: a counter fires through the real cast flow -----------------------------


def test_main_phase_counters_a_worthwhile_spell(make_card):
    """A bomb cast into an opponent's held-up counter mana is countered, not resolved."""
    bomb = _creature(make_card, "Bomb", "{2}", 8, 8)  # value ~12, well over the threshold
    caster = _Player(name="b", library=[], hand=[_gc(bomb)], sources=[_src(), _src()])
    responder = _Player(name="a", library=[], hand=[_gc(_counter(make_card))],
                        sources=[_src(), _src()])
    _main_phase(caster, responder, turn=5, cfg=DuelConfig())
    assert not any(p.name == "Bomb" for p in caster.battlefield)  # countered -> never resolved
    assert responder.hand == []  # the counter was spent


def test_main_phase_keeps_counter_for_trivial_spell(make_card):
    """A 1/1 isn't worth a counter; the answer is held for something that matters."""
    mouse = _creature(make_card, "Mouse", "{1}", 1, 1)  # value ~1.5, under the threshold
    caster = _Player(name="b", library=[], hand=[_gc(mouse)], sources=[_src()])
    responder = _Player(name="a", library=[], hand=[_gc(_counter(make_card))],
                        sources=[_src(), _src()])
    _main_phase(caster, responder, turn=5, cfg=DuelConfig())
    assert any(p.name == "Mouse" for p in caster.battlefield)  # resolved
    assert len(responder.hand) == 1  # counter kept


# --- behavioral: reactive answers are no longer inert ------------------------------------


def test_removal_outlasts_a_blank_vs_aggro(make_card):
    """Instant removal (main phase + the pre-combat window) survives aggro far longer than a
    same-cost blank instant -- proof the reactive machinery works end to end."""
    swamp = make_card("Swamp", type_line="Basic Land — Swamp",
                      produced_mana=("B",), color_identity=("B",))
    forest = make_card("Forest", type_line="Basic Land — Forest",
                       produced_mana=("G",), color_identity=("G",))
    wall = _creature(make_card, "Wall", "{1}{B}", 0, 4, color_identity=("B",))
    removal = _instant_kill(make_card, "Doom Blade", "{1}{B}")
    blank = make_card("Nothing", mana_cost="{1}{B}", type_line="Instant",
                      oracle_text="It does nothing.", color_identity=("B",))
    beater = _creature(make_card, "Bear", "{1}{G}", 3, 2, color_identity=("G",))
    aggro = [(forest, 24), (beater, 36)]
    cfg = DuelConfig(games=150, seed=91, max_turns=30)
    with_removal = duel([(swamp, 26), (wall, 16), (removal, 18)], None, aggro, None, cfg)
    with_blank = duel([(swamp, 26), (wall, 16), (blank, 18)], None, aggro, None, cfg)
    assert with_removal.avg_turns > with_blank.avg_turns + 3  # removal buys real time


def test_reactive_interaction_is_deterministic(make_card):
    swamp = make_card("Swamp", type_line="Basic Land — Swamp",
                      produced_mana=("B",), color_identity=("B",))
    forest = make_card("Forest", type_line="Basic Land — Forest",
                       produced_mana=("G",), color_identity=("G",))
    wall = _creature(make_card, "Wall", "{1}{B}", 0, 4, color_identity=("B",))
    removal = _instant_kill(make_card, "Doom Blade", "{1}{B}")
    beater = _creature(make_card, "Bear", "{1}{G}", 3, 2, color_identity=("G",))
    control = [(swamp, 26), (wall, 16), (removal, 18)]
    aggro = [(forest, 24), (beater, 36)]
    cfg = DuelConfig(games=60, seed=67, max_turns=30)
    assert duel(control, None, aggro, None, cfg) == duel(control, None, aggro, None, cfg)
