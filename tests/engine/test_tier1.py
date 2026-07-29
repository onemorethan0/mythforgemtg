"""Tier-1 board-wipe resilience: paired-seed disruption deltas (offline, synthetic)."""

from mythgauntlet.sim.tier0 import SimConfig
from mythgauntlet.sim.tier1 import compute_resilience


def _creature(make_card, name, power):
    c = make_card(name, mana_cost="{1}{G}", type_line="Creature — Beast", color_identity=("G",))
    c.power, c.toughness = str(power), "3"
    return c


def test_noncreature_ramp_shrugs_off_a_wipe(make_card, forest):
    """A wipe destroys creatures only — a rocks+lands deck keeps all its development."""
    rock = make_card(
        "Mana Rock", mana_cost="{2}", type_line="Artifact", oracle_text="{T}: Add {C}.",
        produced_mana=("C",),
    )
    cfg = SimConfig(runs=200, seed=5, turns=8)
    res = compute_resilience([(forest, 40), (rock, 59)], None, cfg, wipe_turn=5)
    assert res.resilience_score > 95  # nothing the deck cares about dies


def test_creature_deck_folds_harder_than_rocks(make_card, forest):
    rock = make_card(
        "Mana Rock", mana_cost="{2}", type_line="Artifact", oracle_text="{T}: Add {C}.",
        produced_mana=("C",),
    )
    bear = _creature(make_card, "Beater", 3)
    cfg = SimConfig(runs=300, seed=7, turns=8)
    creatures = compute_resilience([(forest, 40), (bear, 59)], None, cfg, wipe_turn=5)
    rocks = compute_resilience([(forest, 40), (rock, 59)], None, cfg, wipe_turn=5)
    assert creatures.resilience_score < rocks.resilience_score


def test_wipe_delays_the_kill(make_card, forest):
    bear = _creature(make_card, "Beater", 4)
    cfg = SimConfig(runs=400, seed=11, turns=10)
    res = compute_resilience([(forest, 36), (bear, 63)], None, cfg, wipe_turn=5)
    assert res.clean_kill_rate >= res.wiped_kill_rate
    if res.kill_delay_turns is not None:
        assert res.kill_delay_turns >= 0  # a wipe never speeds your own clock up


def test_mana_dorks_die_to_wipe(make_card, forest):
    """Creature mana sources are lost to a wipe; equivalent rock ramp is not."""
    dork = make_card(
        "Mana Elf", mana_cost="{G}", type_line="Creature — Elf Druid",
        oracle_text="{T}: Add {G}.", produced_mana=("G",), color_identity=("G",),
    )
    dork.power, dork.toughness = "1", "1"
    rock = make_card(
        "Signet", mana_cost="{2}", type_line="Artifact", oracle_text="{T}: Add {G}.",
        produced_mana=("G",),
    )
    cfg = SimConfig(runs=300, seed=13, turns=8)
    dorks = compute_resilience([(forest, 30), (dork, 69)], None, cfg, wipe_turn=5)
    rocks = compute_resilience([(forest, 30), (rock, 69)], None, cfg, wipe_turn=5)
    assert dorks.resilience_score < rocks.resilience_score


def test_deterministic(make_card, forest):
    bear = _creature(make_card, "Beater", 3)
    cfg = SimConfig(runs=100, seed=17, turns=8)
    a = compute_resilience([(forest, 40), (bear, 59)], None, cfg, wipe_turn=5)
    b = compute_resilience([(forest, 40), (bear, 59)], None, cfg, wipe_turn=5)
    assert a == b


def test_score_in_range(make_card, forest):
    bear = _creature(make_card, "Beater", 3)
    cfg = SimConfig(runs=100, seed=19, turns=8)
    res = compute_resilience([(forest, 40), (bear, 59)], None, cfg, wipe_turn=4)
    assert 0.0 <= res.resilience_score <= 100.0
    assert res.runs == 100
