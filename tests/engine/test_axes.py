"""Interaction, Ceiling, and Pod axes (offline, synthetic decks)."""

from mythgauntlet.ratings.axes import compute_ceiling, compute_interaction, compute_pod
from mythgauntlet.sim.tier0 import SimConfig, simulate


def _removal(make_card, name):
    return make_card(name, mana_cost="{1}{B}", type_line="Instant",
                     oracle_text="Destroy target creature.", color_identity=("B",))


def _counter(make_card, name):
    return make_card(name, mana_cost="{U}{U}", type_line="Instant",
                     oracle_text="Counter target spell.", color_identity=("U",))


def _wipe(make_card, name):
    return make_card(name, mana_cost="{2}{W}{W}", type_line="Sorcery",
                     oracle_text="Destroy all creatures.", color_identity=("W",))


def test_interaction_rewards_answers_and_breadth(make_card, forest, bear):
    control = [
        (forest, 38),
        (_removal(make_card, "Kill A"), 4),
        (_counter(make_card, "Deny B"), 4),
        (_wipe(make_card, "Sweep C"), 3),
        (bear, 50),
    ]
    durdle = [(forest, 38), (bear, 61)]
    ci = compute_interaction(control)
    di = compute_interaction(durdle)
    assert ci.score > di.score
    assert ci.breadth == 3  # removal + counter + wipe all present
    assert di.breadth == 0
    assert ci.spot_removal == 4 and ci.counterspells == 4 and ci.board_wipes == 3


def test_interaction_breadth_partial(make_card, forest, bear):
    only_removal = [(forest, 38), (_removal(make_card, "Kill"), 8), (bear, 53)]
    rep = compute_interaction(only_removal)
    assert rep.breadth == 1
    assert 0 < rep.score < 100


def test_interaction_lands_ignored(make_card, forest):
    assert compute_interaction([(forest, 99)]).answers == 0


def _island(make_card):
    return make_card("Island", type_line="Basic Land - Island",
                     produced_mana=("U",), color_identity=("U",))


def _swamp(make_card):
    return make_card("Swamp", type_line="Basic Land - Swamp",
                     produced_mana=("B",), color_identity=("B",))


def test_cheap_instants_beat_expensive_sorceries_same_count(make_card):
    """Castability weighting: 8 cheap on-color instants are more real interaction than 8
    seven-mana sorcery-speed answers, even at identical raw piece counts."""
    island = _island(make_card)
    cheap = make_card("Snap Counter", mana_cost="{U}", type_line="Instant",
                      oracle_text="Counter target spell.", color_identity=("U",))
    dear = make_card("Ponderous Wipe", mana_cost="{5}{U}{U}", type_line="Sorcery",
                     oracle_text="Destroy all creatures.", color_identity=("U",))
    cheap_deck = compute_interaction([(island, 37), (cheap, 8)])
    dear_deck = compute_interaction([(island, 37), (dear, 8)])
    assert cheap_deck.answers == dear_deck.answers == 8  # same raw count
    assert cheap_deck.effective_answers > dear_deck.effective_answers
    assert cheap_deck.score > dear_deck.score


def test_color_support_downweights_unsupported_pips(make_card):
    """The same triple-black wipe is worth less interaction in a deck that barely produces
    black than in a mono-black one (a strained manabase can't reliably cast it)."""
    heavy = make_card("Triple Wrath", mana_cost="{B}{B}{B}", type_line="Sorcery",
                      oracle_text="Destroy all creatures.", color_identity=("B",))
    mono_black = compute_interaction([(_swamp(make_card), 37), (heavy, 6)])
    splash = compute_interaction(
        [(_island(make_card), 35), (_swamp(make_card), 2), (heavy, 6)]  # only 2 black sources
    )
    assert mono_black.answers == splash.answers == 6
    assert mono_black.effective_answers > splash.effective_answers


def test_ceiling_higher_for_faster_deck(make_card, forest):
    fast = make_card("Haymaker", mana_cost="{G}", type_line="Creature — Giant")
    fast.power, fast.toughness = "12", "12"
    slow = make_card("Wall", mana_cost="{G}", type_line="Creature — Wall")
    slow.power, slow.toughness = "0", "6"
    cfg = SimConfig(runs=300, seed=9, turns=10)
    fast_c = compute_ceiling(simulate([(forest, 40), (fast, 59)], None, cfg), cfg)
    slow_c = compute_ceiling(simulate([(forest, 40), (slow, 59)], None, cfg), cfg)
    assert fast_c.score > slow_c.score
    assert fast_c.fast_kill_turn is not None


def test_ceiling_go_off_lifts_score_and_is_earlier_better(make_card, forest):
    # a durdly, no-combat-kill deck: without a go-off its ceiling is ~0.
    slow = make_card("Wall", mana_cost="{G}", type_line="Creature — Wall")
    slow.power, slow.toughness = "0", "6"
    cfg = SimConfig(runs=200, seed=9, turns=10)
    runs = simulate([(forest, 40), (slow, 59)], None, cfg)
    base = compute_ceiling(runs, cfg)
    fires = compute_ceiling(runs, cfg, go_off_turn=5)
    earlier = compute_ceiling(runs, cfg, go_off_turn=3)
    assert fires.score > base.score  # a storm go-off is a real (non-combat) ceiling
    assert earlier.score > fires.score  # earlier kill = higher ceiling
    assert fires.go_off_turn == 5 and base.go_off_turn is None


def test_ceiling_overrun_alpha_lifts_score(make_card, forest):
    slow = make_card("Wall", mana_cost="{G}", type_line="Creature — Wall")
    slow.power, slow.toughness = "0", "6"
    cfg = SimConfig(runs=200, seed=9, turns=10)
    runs = simulate([(forest, 40), (slow, 59)], None, cfg)
    base = compute_ceiling(runs, cfg)
    alpha = compute_ceiling(runs, cfg, overrun_alpha=True)
    assert alpha.score > base.score  # a wide lethal alpha strike is a real ceiling
    assert alpha.overrun_alpha is True and base.overrun_alpha is False


def test_ceiling_combo_boost(make_card, forest, bear):
    cfg = SimConfig(runs=100, seed=11, turns=8)
    runs = simulate([(forest, 40), (bear, 59)], None, cfg)
    without = compute_ceiling(runs, cfg, has_game_ending_combo=False)
    with_combo = compute_ceiling(runs, cfg, has_game_ending_combo=True)
    assert with_combo.score > without.score
    assert with_combo.has_game_ending_combo


def test_ceiling_score_in_range(make_card, forest, bear):
    cfg = SimConfig(runs=100, seed=13, turns=8)
    rep = compute_ceiling(simulate([(forest, 40), (bear, 59)], None, cfg), cfg)
    assert 0.0 <= rep.score <= 100.0


# --- Pod (multiplayer closing power) -----------------------------------------------------


def test_pod_wider_deck_closes_the_table_faster(make_card, forest):
    """A fast, wide beatdown reaches table-lethal (3x40) unopposed; a durdle wall never does."""
    haymaker = make_card("Haymaker", mana_cost="{G}", type_line="Creature - Giant")
    haymaker.power, haymaker.toughness = "12", "12"
    wall = make_card("Wall", mana_cost="{G}", type_line="Creature - Wall")
    wall.power, wall.toughness = "0", "6"
    cfg = SimConfig(runs=200, seed=9, turns=14)
    fast = compute_pod(simulate([(forest, 40), (haymaker, 59)], None, cfg), cfg)
    durdle = compute_pod(simulate([(forest, 40), (wall, 59)], None, cfg), cfg)
    assert fast.pod_close_rate > durdle.pod_close_rate
    assert fast.score > durdle.score
    assert durdle.pod_close_turn is None  # a 0-power wall can't generate table-lethal pressure
    assert fast.opponents == 3


def test_pod_duel_close_rate_exceeds_pod_close_rate(make_card, forest):
    """The whole point: a single-target clock (40 life) is easier to reach than table-lethal
    (120), so more games close a duel than close the pod."""
    beater = make_card("Beater", mana_cost="{G}", type_line="Creature - Beast")
    beater.power, beater.toughness = "4", "4"
    cfg = SimConfig(runs=200, seed=15, turns=14)
    pod = compute_pod(simulate([(forest, 40), (beater, 59)], None, cfg), cfg)
    assert pod.duel_close_rate >= pod.pod_close_rate


def test_pod_finisher_lifts_score(make_card, forest):
    wall = make_card("Wall", mana_cost="{G}", type_line="Creature - Wall")
    wall.power, wall.toughness = "0", "6"
    cfg = SimConfig(runs=100, seed=9, turns=14)
    runs = simulate([(forest, 40), (wall, 59)], None, cfg)
    base = compute_pod(runs, cfg, has_finisher=False)
    combo = compute_pod(runs, cfg, has_finisher=True)
    assert combo.score > base.score  # a game-ending combo closes the table combat can't
    assert combo.via_finisher and not base.via_finisher


def test_pod_score_in_range(make_card, forest, bear):
    cfg = SimConfig(runs=100, seed=13, turns=14)
    pod = compute_pod(simulate([(forest, 40), (bear, 59)], None, cfg), cfg, has_finisher=True)
    assert 0.0 <= pod.score <= 100.0
