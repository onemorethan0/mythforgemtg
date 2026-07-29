"""Golden-master characterization of the Tier-2 engine under the greedy policy.

Captured BEFORE the Phase-7 action-based refactor (docs/ROADMAP.md Phase 7). The refactor
converts the imperative turn loop into an action-based state machine an Agent drives; this
battery is the safety net. RNG is consumed ONLY at deck shuffle + per-game spawn, and the
greedy decisions consume none, so the refactored engine must reproduce every DuelResult here
BIT-FOR-BIT with agent="greedy" (the default). That proves the greedy calibration instrument is
untouched while the control flow is rewritten.

The scenarios span every mutation + control path the engine has: combat + tapping, rung-1
removal/wipes, the reactive counter-war + instant window, commander recast + tax, assembled
combos, decking, and the CCM interpreter paths (activated pingers, death/upkeep/cast/landfall/
attack/combat-damage triggers, ritual mana, tutors, x_basis scaling).

First run with no fixture CAPTURES tests/data/tier2_golden.json (current engine == ground truth)
and passes; later runs ASSERT reproduction. Regenerate deliberately by deleting the fixture.
Offline/synthetic (invariant #5).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier2 import DuelConfig, duel

_FIXTURE = Path(__file__).parent / "data" / "tier2_golden.json"


# --- synthetic-deck builders (mirror the tier2 test suites) ------------------------------


def _ccm_store(tmp_path, docs: dict[str, dict]) -> SemanticsStore:
    authored = tmp_path / "authored"
    authored.mkdir(parents=True, exist_ok=True)
    for name, ccm in docs.items():
        slug = name.lower().replace(" ", "-").replace(",", "").replace("'", "")
        (authored / f"{slug}.json").write_text(
            json.dumps({"card": {"name": name}, "ccm": ccm}), encoding="utf-8"
        )
    return SemanticsStore(authored=authored, compiled=tmp_path / "no-compiled")


def _creature(make_card, name, cost, power, toughness, **kw):
    kw.setdefault("color_identity", ("G",))
    card = make_card(name, mana_cost=cost, type_line="Creature - Beast", **kw)
    card.power, card.toughness = str(power), str(toughness)
    return card


def _spell_ccm(name, effects, cost="{1}", kind="spell_effect", **extra):
    ability = {"kind": kind, "effects": effects, **extra}
    return {"name": name, "ccm_version": 1, "cost": {"mana": cost}, "abilities": [ability]}


def _trigger_ccm(name, event, effects, cost="{1}"):
    return {
        "name": name, "ccm_version": 1, "cost": {"mana": cost},
        "abilities": [{"kind": "triggered", "trigger": {"event": event}, "effects": effects}],
    }


def _scenarios(make_card, forest, tmp_path):
    """Yield (name, DuelResult) for the current engine. Each scenario is deterministic."""
    swamp = make_card("Swamp", type_line="Basic Land - Swamp",
                      produced_mana=("B",), color_identity=("B",))
    island = make_card("Island", type_line="Basic Land - Island",
                       produced_mana=("U",), color_identity=("U",))
    wastes = make_card("Wastes", type_line="Basic Land", produced_mana=("C",))

    bear = _creature(make_card, "Attack Bear", "{1}{G}", 3, 2)
    aggro = [(forest, 24), (bear, 36)]
    do_nothing = [(forest, 60)]

    out: list[tuple[str, object]] = []

    def run(name, a, ca, b, cb, cfg, store=None, combos_a=(), combos_b=()):
        out.append((name, duel(a, ca, b, cb, cfg, store=store,
                               combos_a=combos_a, combos_b=combos_b)))

    # combat clock + tapping
    run("aggro_vs_do_nothing", aggro, None, do_nothing, None,
        DuelConfig(games=40, seed=7, max_turns=25))
    big = _creature(make_card, "Big Beast", "{1}{G}", 4, 4)
    small = _creature(make_card, "Small Bear", "{1}{G}", 2, 2)
    run("big_vs_small", [(forest, 24), (big, 36)], None, [(forest, 24), (small, 36)], None,
        DuelConfig(games=40, seed=13, max_turns=25))
    racer = _creature(make_card, "Racer", "{1}{G}", 3, 1)
    run("aggro_mirror_tapping", [(forest, 24), (racer, 36)], None,
        [(forest, 24), (racer, 36)], None, DuelConfig(games=40, seed=71, max_turns=40))

    # rung-1 removal + wipes
    kill = make_card("Kill Spell", mana_cost="{1}{G}", type_line="Sorcery",
                     color_identity=("G",), oracle_text="Destroy target creature.")
    war_bear = _creature(make_card, "War Bear", "{1}{G}", 3, 3)
    run("removal_vs_beef", [(forest, 24), (war_bear, 24), (kill, 12)], None,
        [(forest, 24), (war_bear, 36)], None, DuelConfig(games=40, seed=17, max_turns=30))
    wipe = make_card("Sweep Spell", mana_cost="{2}{G}{G}", type_line="Sorcery",
                     color_identity=("G",), oracle_text="Destroy all creatures.")
    fatty = _creature(make_card, "Late Fatty", "{4}{G}{G}", 8, 8)
    run("wipe_control_vs_aggro", [(forest, 26), (wipe, 14), (fatty, 20)], None,
        aggro, None, DuelConfig(games=40, seed=29, max_turns=30))

    # commander recast + tax
    cmdr = _creature(make_card, "Big Commander", "{2}{G}", 5, 5)
    run("commander_recast", do_nothing, cmdr, aggro, None,
        DuelConfig(games=40, seed=23, max_turns=25))

    # combos
    pa = _creature(make_card, "Combo Piece A", "{G}", 1, 1)
    pb = _creature(make_card, "Combo Piece B", "{G}", 1, 1)
    combo = frozenset({"combo piece a", "combo piece b"})
    run("combo_assembles", [(forest, 24), (pa, 18), (pb, 18)], None, aggro, None,
        DuelConfig(games=40, seed=51, max_turns=30), combos_a=(combo,))

    # decking
    run("decking_tiny_deck", [(forest, 15)], None, do_nothing, None,
        DuelConfig(games=20, seed=31, max_turns=200))

    # reactive interaction: counters + instant removal
    wall = _creature(make_card, "Wall", "{1}{B}", 0, 4, color_identity=("B",))
    doom = make_card("Doom Blade", mana_cost="{1}{B}", type_line="Instant",
                     color_identity=("B",), oracle_text="Destroy target creature.")
    beater = _creature(make_card, "Bear", "{1}{G}", 3, 2, color_identity=("G",))
    run("instant_removal_control_vs_aggro", [(swamp, 26), (wall, 16), (doom, 18)], None,
        [(forest, 24), (beater, 36)], None, DuelConfig(games=40, seed=91, max_turns=30))
    counter = make_card("Deny", mana_cost="{U}{U}", type_line="Instant",
                        color_identity=("U",), oracle_text="Counter target spell.")
    bomb = _creature(make_card, "Bomb", "{4}{U}", 6, 6, color_identity=("U",))
    run("counter_control_mirror", [(island, 30), (counter, 15), (bomb, 15)], None,
        [(island, 30), (counter, 15), (bomb, 15)], None,
        DuelConfig(games=40, seed=67, max_turns=30))

    # CCM: activated pinger
    pinger = _creature(make_card, "Test Pinger", "{1}{G}", 0, 3)
    pinger_store = _ccm_store(tmp_path / "pinger", {
        "Test Pinger": {
            "name": "Test Pinger", "ccm_version": 1, "cost": {"mana": "{1}{G}"},
            "types": ["creature"],
            "abilities": [{"kind": "activated", "cost": {"tap": True},
                           "effects": [{"op": "deal_damage", "amount": 1,
                                        "target": {"type": "any"}}]}]},
    })
    run("ccm_pinger_activated", [(forest, 24), (pinger, 36)], None, do_nothing, None,
        DuelConfig(games=40, seed=41, max_turns=40), store=pinger_store)

    # CCM: death trigger (aristocrat)
    martyr = _creature(make_card, "Test Martyr", "{1}{G}", 2, 2)
    plain = _creature(make_card, "Plain Bear", "{1}{G}", 2, 2)
    martyr_store = _ccm_store(tmp_path / "martyr", {
        "Test Martyr": _trigger_ccm("Test Martyr", "death",
                                    [{"op": "lose_life", "amount": 2, "who": "each_opponent"}],
                                    cost="{1}{G}")})
    run("ccm_death_trigger", [(forest, 24), (martyr, 36)], None,
        [(forest, 24), (plain, 36)], None, DuelConfig(games=40, seed=43, max_turns=30),
        store=martyr_store)

    # CCM: upkeep drainer (event trigger, ends games)
    drainer = make_card("Upkeep Drainer", mana_cost="{1}", type_line="Enchantment")
    blank = make_card("Do Nothing", mana_cost="{4}", type_line="Enchantment",
                      oracle_text="It does nothing at all.")
    upkeep_store = _ccm_store(tmp_path / "upkeep", {
        "Upkeep Drainer": _trigger_ccm("Upkeep Drainer", "upkeep",
                                       [{"op": "lose_life", "amount": 3, "who": "each_opponent"}])})
    run("ccm_upkeep_drainer", [(wastes, 20), (drainer, 20)], None,
        [(wastes, 20), (blank, 20)], None, DuelConfig(games=40, seed=11, max_turns=30),
        store=upkeep_store)

    # CCM: landfall token-maker
    grower = make_card("Land Grower", mana_cost="{1}{G}", type_line="Enchantment",
                       color_identity=("G",))
    grower_store = _ccm_store(tmp_path / "grower", {
        "Land Grower": _trigger_ccm("Land Grower", "landfall",
                                    [{"op": "create_token", "count": 1, "power": 2,
                                      "toughness": 2}], cost="{1}{G}")})
    run("ccm_landfall_tokens", [(forest, 30), (grower, 30)], None, do_nothing, None,
        DuelConfig(games=40, seed=61, max_turns=30), store=grower_store)

    # CCM: ritual mana enabling a payoff
    ritual = make_card("Test Ritual", mana_cost="{B}", type_line="Instant",
                       color_identity=("B",), edhrec_rank=100)
    payoff = _creature(make_card, "Ritual Payoff", "{2}{B}", 5, 5, color_identity=("B",))
    ritual_store = _ccm_store(tmp_path / "ritual", {
        "Test Ritual": _spell_ccm("Test Ritual",
                                  [{"op": "add_mana", "amount": 3, "colors": "B"}], cost="{B}")})
    run("ccm_ritual_mana", [(swamp, 24), (ritual, 18), (payoff, 18)], None,
        [(swamp, 24), (payoff, 36)], None, DuelConfig(games=40, seed=83, max_turns=30),
        store=ritual_store)

    # CCM: x_basis scaling (deal X = creatures you control)
    surge = make_card("Crowd Surge", mana_cost="{X}{R}", type_line="Sorcery",
                      color_identity=("R",))
    mountain = make_card("Mountain", type_line="Basic Land - Mountain",
                         produced_mana=("R",), color_identity=("R",))
    goblin = _creature(make_card, "Goblin", "{R}", 1, 1, color_identity=("R",))
    surge_store = _ccm_store(tmp_path / "surge", {
        "Crowd Surge": _spell_ccm("Crowd Surge",
                                  [{"op": "deal_damage", "amount": "X",
                                    "x_basis": "creatures_you_control",
                                    "target": {"type": "opponent"}}], cost="{X}{R}")})
    run("ccm_x_basis_surge", [(mountain, 24), (goblin, 24), (surge, 12)], None,
        [(mountain, 24), (goblin, 36)], None, DuelConfig(games=40, seed=97, max_turns=30),
        store=surge_store)

    return out


def test_tier2_golden_master(make_card, forest, tmp_path):
    results = {name: asdict(res) for name, res in _scenarios(make_card, forest, tmp_path)}

    if not _FIXTURE.exists():
        _FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        _FIXTURE.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
        pytest.skip(f"captured golden master ({len(results)} scenarios) -> {_FIXTURE.name}")

    expected = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert set(results) == set(expected), "scenario set drifted from the fixture"
    mismatches = {k: (expected[k], results[k]) for k in results if results[k] != expected[k]}
    assert not mismatches, (
        "Tier-2 engine diverged from the golden master under greedy:\n"
        + "\n".join(f"  {k}: expected {e} got {g}" for k, (e, g) in mismatches.items())
    )
