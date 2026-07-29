"""Behavioral tests for the Tier-0 goldfish simulator (offline, synthetic cards)."""

from mythgauntlet.ratings import metrics
from mythgauntlet.semantics import tags
from mythgauntlet.sim.tier0 import SimConfig, simulate


def _deck(forest, bear, lands: int, spells: int):
    return [(forest, lands), (bear, spells)]


def _commander(make_card):
    return make_card(
        "Test Commander",
        mana_cost="{2}{G}{G}",
        type_line="Legendary Creature — Elf Warrior",
        colors=("G",),
        color_identity=("G",),
    )


def test_determinism_same_seed_identical_results(make_card, forest, bear):
    cfg = SimConfig(runs=50, seed=123, turns=6)
    deck = _deck(forest, bear, 38, 61)
    cmdr = _commander(make_card)
    assert simulate(deck, cmdr, cfg) == simulate(deck, cmdr, cfg)


def test_different_seeds_differ(make_card, forest, bear):
    deck = _deck(forest, bear, 38, 61)
    cmdr = _commander(make_card)
    a = simulate(deck, cmdr, SimConfig(runs=50, seed=1, turns=6))
    b = simulate(deck, cmdr, SimConfig(runs=50, seed=2, turns=6))
    assert a != b


def _mono_r_commander(make_card, cheat: bool):
    text = ("Whenever this attacks, you may put a creature card from your hand onto the "
            "battlefield tapped and attacking." if cheat else "")
    c = make_card("Boss", mana_cost="{2}{R}", type_line="Legendary Creature — Dragon",
                  colors=("R",), color_identity=("R",), oracle_text=text)
    c.power, c.toughness = "4", "4"
    return c


def test_cheat_enabler_detected_by_heuristic(make_card):
    assert tags.analyze(_mono_r_commander(make_card, cheat=True)).cheats_creatures is True
    assert tags.analyze(_mono_r_commander(make_card, cheat=False)).cheats_creatures is False


def test_cheat_commander_deploys_stranded_fatties(make_card):
    """A Kaalia-class commander turns a hand of uncastable fatties into a clock: fewer dead
    cards and more kills than the same deck under a vanilla commander of equal cost."""
    mountain = make_card("Mountain", type_line="Basic Land — Mountain",
                         produced_mana=("R",), color_identity=("R",))
    fatty = make_card("Fatty", mana_cost="{7}", type_line="Creature — Dragon",
                      colors=("R",), color_identity=("R",))
    fatty.power, fatty.toughness = "7", "7"
    deck = [(mountain, 40), (fatty, 59)]
    cfg = SimConfig(runs=400, seed=11, turns=10)

    cheat = simulate(deck, _mono_r_commander(make_card, cheat=True), cfg)
    plain = simulate(deck, _mono_r_commander(make_card, cheat=False), cfg)
    dead = lambda runs: sum(r.dead_cards for r in runs) / len(runs)  # noqa: E731
    kills = lambda runs: sum(1 for r in runs if r.kill_turn is not None)  # noqa: E731
    assert dead(cheat) < dead(plain)      # fatties get cheated in, not stranded
    assert kills(cheat) > kills(plain)    # ... and close games


def test_cheat_does_nothing_without_the_enabler(make_card):
    """The over-shoot guard: a deck with no enabler is byte-identical (cheats_creatures unset)."""
    mountain = make_card("Mountain", type_line="Basic Land — Mountain",
                         produced_mana=("R",), color_identity=("R",))
    fatty = make_card("Fatty", mana_cost="{7}", type_line="Creature — Dragon",
                      colors=("R",), color_identity=("R",))
    fatty.power, fatty.toughness = "7", "7"
    deck = [(mountain, 40), (fatty, 59)]
    cfg = SimConfig(runs=200, seed=5, turns=10)
    vanilla = _mono_r_commander(make_card, cheat=False)
    assert simulate(deck, vanilla, cfg) == simulate(deck, vanilla, cfg)


def test_more_lands_hit_more_land_drops(make_card, forest, bear):
    cfg = SimConfig(runs=300, seed=7, turns=5)
    high = metrics.compute(simulate(_deck(forest, bear, 45, 54), None, cfg), cfg)
    low = metrics.compute(simulate(_deck(forest, bear, 20, 79), None, cfg), cfg)
    assert high.land_hit_by_turn[2] > low.land_hit_by_turn[2]


def test_ramp_accelerates_commander(make_card, forest, bear, sol_ring_like):
    cfg = SimConfig(runs=400, seed=11, turns=8)
    cmdr = _commander(make_card)
    no_ramp = metrics.compute(simulate(_deck(forest, bear, 38, 61), cmdr, cfg), cfg)
    with_ramp = metrics.compute(
        simulate([(forest, 38), (bear, 51), (sol_ring_like, 10)], cmdr, cfg), cfg
    )
    assert no_ramp.avg_commander_turn is not None
    assert with_ramp.avg_commander_turn is not None
    assert with_ramp.avg_commander_turn < no_ramp.avg_commander_turn


def test_landless_deck_mulligans_hard(make_card, bear):
    cfg = SimConfig(runs=100, seed=5, turns=4)
    report = metrics.compute(simulate([(bear, 99)], None, cfg), cfg)
    assert report.avg_mulligans > 0.5
    assert report.keep_rate < 0.1


def test_taplands_slow_mana_availability(make_card, bear):
    untapped = make_card(
        "Fast Land", type_line="Land", produced_mana=("G",), color_identity=("G",)
    )
    tapped = make_card(
        "Slow Land", type_line="Land",
        oracle_text="Slow Land enters the battlefield tapped.",
        produced_mana=("G",), color_identity=("G",),
    )
    cfg = SimConfig(runs=200, seed=3, turns=4)
    fast = metrics.compute(simulate([(untapped, 40), (bear, 59)], None, cfg), cfg)
    slow = metrics.compute(simulate([(tapped, 40), (bear, 59)], None, cfg), cfg)
    assert fast.avg_mana_available_by_turn[1] > slow.avg_mana_available_by_turn[1]


def test_draw_spells_increase_cards_drawn(make_card, forest, bear):
    draw_spell = make_card(
        "Insight Spell", mana_cost="{1}{U}", type_line="Sorcery",
        oracle_text="Draw two cards.", colors=("U",), color_identity=("U",),
    )
    island = make_card(
        "Island", type_line="Basic Land — Island", produced_mana=("U",), color_identity=("U",)
    )
    cfg = SimConfig(runs=300, seed=9, turns=8)
    plain = metrics.compute(simulate([(island, 40), (bear, 59)], None, cfg), cfg)
    drawing = metrics.compute(
        simulate([(island, 40), (bear, 49), (draw_spell, 10)], None, cfg), cfg
    )
    assert drawing.avg_cards_drawn > plain.avg_cards_drawn


def test_color_requirements_gate_casting(make_card):
    """A deck whose spells need a color its lands can't produce casts ~nothing."""
    swamp = make_card(
        "Swamp", type_line="Basic Land — Swamp", produced_mana=("B",), color_identity=("B",)
    )
    green_spell = make_card(
        "Green Spell", mana_cost="{G}", type_line="Sorcery", colors=("G",), color_identity=("G",)
    )
    cfg = SimConfig(runs=100, seed=13, turns=5)
    report = metrics.compute(simulate([(swamp, 40), (green_spell, 59)], None, cfg), cfg)
    assert report.avg_spells_cast == 0.0


def test_report_score_in_range(make_card, forest, bear):
    cfg = SimConfig(runs=100, seed=21, turns=6)
    report = metrics.compute(simulate(_deck(forest, bear, 38, 61), None, cfg), cfg)
    assert 0.0 <= report.consistency_score <= 100.0
    assert report.runs == 100
