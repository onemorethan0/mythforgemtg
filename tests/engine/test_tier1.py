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


def test_all_cards_none_still_works(make_card, forest):
    """`all_cards` is optional -- omitting it must not break a caller that predates it."""
    bear = _creature(make_card, "Beater", 3)
    cfg = SimConfig(runs=50, seed=23, turns=8)
    res = compute_resilience([(forest, 40), (bear, 59)], None, cfg, wipe_turn=4)
    assert res.runs == 50


def test_wipe_does_not_stop_a_storm_kill(make_card, forest):
    """PLAN_CLOCK Phase 2: this axis called sim.tier0.simulate directly and never got the
    Phase 1a/1b non-combat-kill fix the main runs/pod_runs batches did, so a storm deck's
    resilience read a combat-only (~turn 8+) kill_turn no matter how the sim actually wins.
    With apply_nut_kills wired in, a real go-off deck's clean kill turn reflects the storm
    kill (fast), and a board wipe -- which destroys creatures, not the storm engine's
    mana/spells -- must not meaningfully change it, because a wipe doesn't stop a combo."""
    granter = make_card(
        "Inspiration Muse", mana_cost="{2}{U}{R}", type_line="Legendary Creature",
        oracle_text="Instant and sorcery spells you cast have storm.",
    )
    burn_imp = make_card(
        "Cast-Burn Imp", type_line="Creature",
        oracle_text="Whenever you cast an instant or sorcery spell, it deals 2 damage "
                    "to any target.",
    )
    cantrips = [(make_card(
        f"Cantrip {i}", mana_cost="{U}", type_line="Instant", oracle_text="Draw a card.",
    ), 1) for i in range(14)]
    big_burn = make_card(
        "Big Burn", mana_cost="{X}{R}", type_line="Sorcery",
        oracle_text="Big Burn deals X damage to any target.",
    )
    # A real spell-count of rocks (not a synthetic mana curve, per this repo's own lesson
    # that a realistic decklist must be verified live, not assumed -- PLAN_CLOCK's own
    # "1 Guttersnipe in 99 cards mostly draws nothing" finding): purely linear one-land-
    # per-turn growth peaks at 24 damage, under the 40-life threshold, so the engine needs
    # its own ramp to reach supra-linear mana the way a real storm deck is actually built.
    rock = make_card(
        "Signet", mana_cost="{2}", type_line="Artifact", oracle_text="{T}: Add {C}{C}.",
        produced_mana=("C",),
    )
    spells = [(granter, 1), (burn_imp, 1), *cantrips, (big_burn, 1), (rock, 16)]
    deck = spells + [(forest, 99 - len(spells))]
    cfg = SimConfig(runs=150, seed=29, turns=12)
    res = compute_resilience(deck, None, cfg, wipe_turn=4, all_cards=deck)
    # Without apply_nut_kills wired in, this deck (no creatures to speak of) would report
    # NO kill at all -- kill_turn stays combat-only and this engine never attacks. With it,
    # the storm engine's own damage is visible as a real kill turn.
    assert res.clean_kill_rate > 0.5
    assert res.clean_avg_kill_turn is not None
    # The wipe clears creatures; it does not touch spells, mana, or the storm engine, so the
    # kill turn must be UNCHANGED by it -- a wipe that can't stop a combo shouldn't read as
    # having delayed it.
    assert res.wiped_avg_kill_turn == res.clean_avg_kill_turn
    assert res.kill_delay_turns == 0.0
