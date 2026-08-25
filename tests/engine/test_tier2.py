"""Tier-2 adversarial engine: behavioral sanity (offline, synthetic decks)."""

import json

from mythgauntlet.semantics.profile import DeathEffect
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier2 import DuelConfig, _Permanent, _Player, _apply_resolved, _wipe_table, duel
from mythgauntlet.semantics.interpreter import ResolvedEffect


def _store_with(tmp_path, docs: dict[str, dict]) -> SemanticsStore:
    authored = tmp_path / "authored"
    authored.mkdir(parents=True, exist_ok=True)
    for name, ccm in docs.items():
        slug = name.lower().replace(" ", "-").replace(",", "")
        (authored / f"{slug}.json").write_text(
            json.dumps({"card": {"name": name}, "ccm": ccm}), encoding="utf-8"
        )
    return SemanticsStore(authored=authored, compiled=tmp_path / "no-compiled")


def _creature(make_card, name, cost, power, toughness, **kw):
    card = make_card(name, mana_cost=cost, type_line="Creature — Beast",
                     color_identity=("G",), **kw)
    card.power = str(power)
    card.toughness = str(toughness)
    return card


def _aggro_deck(make_card, forest):
    bear = _creature(make_card, "Attack Bear", "{1}{G}", 3, 2)
    return [(forest, 24), (bear, 36)]


def _do_nothing_deck(forest):
    return [(forest, 60)]


def test_determinism(make_card, forest):
    cfg = DuelConfig(games=30, seed=99, max_turns=20)
    a = duel(_aggro_deck(make_card, forest), None, _do_nothing_deck(forest), None, cfg)
    b = duel(_aggro_deck(make_card, forest), None, _do_nothing_deck(forest), None, cfg)
    assert a == b


def test_aggro_crushes_do_nothing(make_card, forest):
    cfg = DuelConfig(games=50, seed=7, max_turns=25)
    result = duel(_aggro_deck(make_card, forest), None, _do_nothing_deck(forest), None, cfg)
    assert result.winrate_a > 0.95
    assert result.avg_turns < 20


def test_bigger_creatures_win(make_card, forest):
    small = _creature(make_card, "Small Bear", "{1}{G}", 2, 2)
    big = _creature(make_card, "Big Beast", "{1}{G}", 4, 4)
    cfg = DuelConfig(games=100, seed=13, max_turns=25)
    result = duel([(forest, 24), (big, 36)], None, [(forest, 24), (small, 36)], None, cfg)
    assert result.winrate_a > 0.6


def test_removal_beats_pure_beef(make_card, forest):
    bear = _creature(make_card, "War Bear", "{1}{G}", 3, 3)
    kill = make_card(
        "Kill Spell", mana_cost="{1}{G}", type_line="Sorcery", color_identity=("G",),
        oracle_text="Destroy target creature.",
    )
    with_removal = [(forest, 24), (bear, 24), (kill, 12)]
    without = [(forest, 24), (bear, 36)]
    cfg = DuelConfig(games=100, seed=17, max_turns=30)
    result = duel(with_removal, None, without, None, cfg)
    # removal converts dead weight into tempo: should at least hold its own
    assert result.winrate_a > 0.45


def test_commander_recasts_with_tax(make_card, forest):
    cmdr = _creature(make_card, "Big Commander", "{2}{G}", 5, 5)
    cfg = DuelConfig(games=40, seed=23, max_turns=25)
    with_cmdr = duel(_do_nothing_deck(forest), cmdr, _aggro_deck(make_card, forest), None, cfg)
    without = duel(_do_nothing_deck(forest), None, _aggro_deck(make_card, forest), None, cfg)
    # a commander gives the do-nothing deck SOME wins/longevity vs pure lands
    assert with_cmdr.wins_a >= without.wins_a
    assert with_cmdr.avg_turns >= without.avg_turns


def test_wipes_stabilize_against_aggro(make_card, forest):
    wipe = make_card(
        "Sweep Spell", mana_cost="{2}{G}{G}", type_line="Sorcery", color_identity=("G",),
        oracle_text="Destroy all creatures.",
    )
    fatty = _creature(make_card, "Late Fatty", "{4}{G}{G}", 8, 8)
    control = [(forest, 26), (wipe, 14), (fatty, 20)]
    cfg = DuelConfig(games=100, seed=29, max_turns=30)
    vs_aggro = duel(control, None, _aggro_deck(make_card, forest), None, cfg)
    no_wipes = duel([(forest, 26), (fatty, 34)], None, _aggro_deck(make_card, forest), None, cfg)
    assert vs_aggro.winrate_a > no_wipes.winrate_a


def test_pingers_win_through_activated_abilities(tmp_path, make_card, forest):
    """A 0-power board can only win if activated damage outlets actually fire."""
    pinger = _creature(make_card, "Test Pinger", "{1}{G}", 0, 3)
    store = _store_with(tmp_path, {
        "Test Pinger": {
            "name": "Test Pinger", "ccm_version": 1, "cost": {"mana": "{1}{G}"},
            "types": ["creature"],
            "abilities": [{"kind": "activated", "cost": {"tap": True},
                           "effects": [{"op": "deal_damage", "amount": 1,
                                        "target": {"type": "any"}}]}],
        },
    })
    deck = [(forest, 24), (pinger, 36)]
    lands = [(forest, 60)]
    cfg = DuelConfig(games=40, seed=41, max_turns=40)
    with_outlets = duel(deck, None, lands, None, cfg, store=store)
    without = duel(deck, None, lands, None, cfg, store=None)
    assert with_outlets.winrate_a > without.winrate_a
    assert with_outlets.winrate_a > 0.9  # pings close the game before the turn cap


def test_death_triggers_swing_mirror_matches(tmp_path, make_card, forest):
    martyr = _creature(make_card, "Test Martyr", "{1}{G}", 2, 2)
    plain = _creature(make_card, "Plain Bear", "{1}{G}", 2, 2)
    store = _store_with(tmp_path, {
        "Test Martyr": {
            "name": "Test Martyr", "ccm_version": 1, "cost": {"mana": "{1}{G}"},
            "types": ["creature"],
            "abilities": [{"kind": "triggered", "trigger": {"event": "death"},
                           "effects": [{"op": "lose_life", "amount": 2,
                                        "who": "each_opponent"}]}],
        },
    })
    cfg = DuelConfig(games=100, seed=43, max_turns=30)
    result = duel(
        [(forest, 24), (martyr, 36)], None, [(forest, 24), (plain, 36)], None,
        cfg, store=store,
    )
    assert result.winrate_a > 0.6  # every trade drains the opponent


def _blood_artist(name: str) -> _Permanent:
    """A Blood-Artist-class permanent: on death, each opponent loses 1 life."""
    return _Permanent(
        name=name, power=0, toughness=1, is_creature=True, sick=False,
        death=DeathEffect(drain=1),
    )


def _pod(n: int, life: int = 40) -> list[_Player]:
    return [_Player(name=chr(ord("a") + i), library=[], life=life) for i in range(n)]


def test_wipe_table_drains_every_opponent_not_just_one():
    """A 4-player board wipe killing 4 Blood Artists must drain ALL N-1 opponents per
    death, not just the single `killer` passed to `_kill` -- each seat's creature death
    is an "each opponent loses 1" trigger scoped to the WHOLE pod minus its owner."""
    a, b, c, d = _pod(4)
    for p in (a, b, c, d):
        p.battlefield.append(_blood_artist(f"Artist ({p.name})"))
    _wipe_table(a, b, (c, d), None)
    # Each of the 4 deaths drains the other 3 seats by 1 -> every seat takes exactly 3.
    assert a.life == b.life == c.life == d.life == 37
    for p in (a, b, c, d):
        assert p.creatures() == []


def test_apply_resolved_each_creature_sweep_drains_every_opponent():
    """`_apply_resolved`'s "deals N to each creature" pod sweep must fan a death drain
    across every OTHER seat too, matching `_wipe_table`'s fix for the same bug class."""
    a, b, c, d = _pod(4)
    for p in (a, b, c, d):
        p.battlefield.append(_blood_artist(f"Artist ({p.name})"))
    eff = ResolvedEffect(op="deal_damage", params={
        "amount": 5, "target": {"type": "creature", "count": "all"},
    })
    _apply_resolved(eff, a, b, None, (c, d))
    assert a.life == b.life == c.life == d.life == 37
    for p in (a, b, c, d):
        assert p.creatures() == []


def test_combo_assembly_wins_the_game(make_card, forest):
    """A deck that assembles its two-card combo wins even with a punier board."""
    # Two vanilla 1/1 combo pieces vs an aggro deck that would otherwise race it.
    piece_a = _creature(make_card, "Combo Piece A", "{G}", 1, 1)
    piece_b = _creature(make_card, "Combo Piece B", "{G}", 1, 1)
    combo = frozenset({"combo piece a", "combo piece b"})
    combo_deck = [(forest, 24), (piece_a, 18), (piece_b, 18)]
    aggro = _aggro_deck(make_card, forest)
    cfg = DuelConfig(games=100, seed=51, max_turns=30)
    with_combo = duel(combo_deck, None, aggro, None, cfg, combos_a=(combo,))
    without = duel(combo_deck, None, aggro, None, cfg)
    assert with_combo.combo_wins > 0
    assert with_combo.winrate_a > without.winrate_a


def test_combo_needs_all_pieces(make_card, forest):
    """One piece present is not a win; the combo must be fully assembled."""
    piece_a = _creature(make_card, "Only Piece", "{G}", 1, 1)
    combo = frozenset({"only piece", "missing piece"})  # 2nd piece not in the deck
    deck = [(forest, 24), (piece_a, 36)]
    cfg = DuelConfig(games=40, seed=53, max_turns=25)
    result = duel(deck, None, [(forest, 60)], None, cfg, combos_a=(combo,))
    assert result.combo_wins == 0


def test_combo_win_is_deterministic(make_card, forest):
    piece_a = _creature(make_card, "Piece One", "{G}", 1, 1)
    piece_b = _creature(make_card, "Piece Two", "{G}", 1, 1)
    combo = frozenset({"piece one", "piece two"})
    deck = [(forest, 24), (piece_a, 18), (piece_b, 18)]
    cfg = DuelConfig(games=50, seed=57, max_turns=30)
    a = duel(deck, None, [(forest, 60)], None, cfg, combos_a=(combo,))
    b = duel(deck, None, [(forest, 60)], None, cfg, combos_a=(combo,))
    assert a == b


def test_attackers_tap_and_cannot_block_next_turn(make_card, forest):
    """Attacking taps the creature, so a race deck can't attack AND block every cycle."""
    beater = _creature(make_card, "Racer", "{1}{G}", 3, 1)  # 3/1: trades badly if it blocks
    # Two symmetric aggro decks: with tapping, attackers die to counterattacks / races
    # resolve; the game should end (a winner or decking), not stall to adjudication forever.
    cfg = DuelConfig(games=60, seed=71, max_turns=40)
    res = duel([(forest, 24), (beater, 36)], None, [(forest, 24), (beater, 36)], None, cfg)
    decisive = res.wins_a + res.wins_b
    assert decisive >= res.draws  # most games reach a real result, not a vigilance stall


def test_decking_mid_turn_loses_immediately(make_card, forest):
    """A draw engine that empties the library loses that same turn (state-based)."""
    draw_engine = make_card(
        "Overdraw", mana_cost="{U}", type_line="Enchantment",
        oracle_text="At the beginning of your upkeep, draw two additional cards.",
        color_identity=("U",),
    )
    island = make_card(
        "Island", type_line="Basic Land — Island", produced_mana=("U",), color_identity=("U",)
    )
    tiny = [(island, 8), (draw_engine, 4)]  # ~12 cards -> decks itself fast
    cfg = DuelConfig(games=20, seed=73, max_turns=200)
    res = duel(tiny, None, [(island, 60)], None, cfg)
    assert res.decked_losses == 20  # the tiny deck always decks itself


def test_duel_rejects_zero_games():
    import pytest

    from mythgauntlet.cli import main

    # guard fires (SystemExit 2) before any file/store access, so no fixtures needed
    with pytest.raises(SystemExit) as exc:
        main(["duel", "a.txt", "b.txt", "--games", "0"])
    assert exc.value.code == 2


def test_draw_from_empty_library_loses(make_card, forest):
    cfg = DuelConfig(games=10, seed=31, max_turns=200)
    tiny = [(forest, 15)]  # will deck itself long before turn 200
    result = duel(tiny, None, [(forest, 60)], None, cfg)
    assert result.decked_losses == 10
