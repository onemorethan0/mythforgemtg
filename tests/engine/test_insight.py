"""Deck insight: the deck-specific narrative (archetype / gameplan / why / cards / verdict)."""

from __future__ import annotations

from types import SimpleNamespace

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
                               avg_commander_turn=3.9, consistency_score=77.0),
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


def test_strengths_and_weaknesses_are_grounded(make_card, forest):
    ins = build_insight(_resolved([(forest, 40), (_creature(make_card, "X"), 20)]), _analysis())
    assert any("Consistent" in s for s in ins.strengths)   # consistency 77 -> strength
    assert any("ceiling" in w.lower() for w in ins.weaknesses)  # ceiling 0 -> weakness


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


def test_pod_read_scales_with_bracket(make_card, forest):
    for br, needle in [(1, "Bracket 1"), (3, "Bracket 3"), (4, "Bracket 4"), (5, "cEDH")]:
        a = _analysis(bracket=SimpleNamespace(bracket=br, label="x", plays_up=False))
        ins = build_insight(_resolved([(forest, 40)]), a)
        assert needle in ins.pod_read
