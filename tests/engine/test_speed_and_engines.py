"""Goldfish combat clock and repeatable draw-engine behavior in Tier 0."""

from mythgauntlet.ratings import metrics
from mythgauntlet.semantics import tags
from mythgauntlet.sim.tier0 import SimConfig, simulate


def test_engine_draw_tagged_separately_from_one_shots(make_card):
    whisperer = make_card(
        "Beast Talker", mana_cost="{2}{G}{G}", type_line="Creature — Elf Druid",
        oracle_text="Whenever you cast a creature spell, draw a card.",
    )
    fx = tags.analyze(whisperer)
    assert fx.engine_draw == 1
    assert fx.draw_cards == 0


def test_additional_draw_engine(make_card):
    library_card = make_card(
        "Sylvan Tome", mana_cost="{1}{G}", type_line="Enchantment",
        oracle_text="At the beginning of your draw step, you may draw two additional cards.",
    )
    assert tags.analyze(library_card).engine_draw == 2


def test_bigger_creatures_kill_faster(make_card, forest):
    small = make_card("Small Bear", mana_cost="{1}{G}", type_line="Creature — Bear")
    small.power = "2"
    big = make_card("Big Beast", mana_cost="{1}{G}", type_line="Creature — Beast")
    big.power = "5"
    cfg = SimConfig(runs=200, seed=17, turns=10)
    small_rep = metrics.compute(simulate([(forest, 40), (small, 59)], None, cfg), cfg)
    big_rep = metrics.compute(simulate([(forest, 40), (big, 59)], None, cfg), cfg)
    assert big_rep.goldfish_kill_rate > small_rep.goldfish_kill_rate or (
        big_rep.avg_kill_turn is not None
        and small_rep.avg_kill_turn is not None
        and big_rep.avg_kill_turn < small_rep.avg_kill_turn
    )


def test_noncreature_deck_never_kills(make_card, forest):
    rock = make_card(
        "Mana Trinket", mana_cost="{2}", type_line="Artifact", oracle_text="{T}: Add {C}."
    )
    cfg = SimConfig(runs=50, seed=19, turns=8)
    report = metrics.compute(simulate([(forest, 40), (rock, 59)], None, cfg), cfg)
    assert report.goldfish_kill_rate == 0.0
    assert report.avg_damage_by_turn[-1] == 0.0


def test_summoning_sickness_delays_damage(make_card, forest):
    """A creature resolved on turn N deals its first damage on turn N+1."""
    titan = make_card("Haymaker", mana_cost="{G}", type_line="Creature — Giant")
    titan.power = "40"
    cfg = SimConfig(runs=100, seed=23, turns=6)
    runs = simulate([(forest, 50), (titan, 49)], None, cfg)
    killed = [r for r in runs if r.kill_turn is not None]
    # Assert the precondition. Every assert here sits inside `if r.kill_turn is not None`,
    # so a change that stopped this deck killing at all would leave the test asserting
    # nothing and still passing — a 40-power one-drop across 100 runs must kill.
    assert killed, "no run produced a kill; the summoning-sickness invariant went untested"
    for r in killed:
        first_cast_possible = 1  # {G} is castable turn 1
        assert r.kill_turn >= first_cast_possible + 1


def test_draw_engines_draw_more_cards_over_time(make_card, forest):
    engine = make_card(
        "Study Idol", mana_cost="{1}{G}", type_line="Enchantment",
        oracle_text="At the beginning of your upkeep, draw a card.",
    )
    bear = make_card("Filler Bear", mana_cost="{1}{G}", type_line="Creature — Bear")
    cfg = SimConfig(runs=200, seed=29, turns=8)
    plain = metrics.compute(simulate([(forest, 40), (bear, 59)], None, cfg), cfg)
    with_engines = metrics.compute(
        simulate([(forest, 40), (bear, 49), (engine, 10)], None, cfg), cfg
    )
    assert with_engines.avg_cards_drawn > plain.avg_cards_drawn


def test_commander_effects_apply(make_card, forest):
    """A creature commander contributes to the goldfish clock after being cast."""
    cmdr = make_card(
        "Big Commander", mana_cost="{2}{G}", type_line="Legendary Creature — Beast",
        color_identity=("G",),
    )
    cmdr.power = "6"
    cfg = SimConfig(runs=100, seed=31, turns=8)
    with_cmdr = metrics.compute(simulate([(forest, 99)], cmdr, cfg), cfg)
    without = metrics.compute(simulate([(forest, 99)], None, cfg), cfg)
    assert with_cmdr.avg_damage_by_turn[-1] > without.avg_damage_by_turn[-1]


def test_stricter_mulligan_policy_mulls_more(make_card, forest, bear):
    deck = [(forest, 30), (bear, 69)]
    loose = SimConfig(runs=200, seed=37, turns=4, mulligan_min_lands=2)
    strict = SimConfig(runs=200, seed=37, turns=4, mulligan_min_lands=4)
    loose_rep = metrics.compute(simulate(deck, None, loose), loose)
    strict_rep = metrics.compute(simulate(deck, None, strict), strict)
    assert strict_rep.avg_mulligans > loose_rep.avg_mulligans
