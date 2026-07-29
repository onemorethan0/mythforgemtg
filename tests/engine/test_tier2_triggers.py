"""T2 executes CCM event triggers (cast/attack/upkeep/...) at the event. Offline, synthetic."""

from __future__ import annotations

import json

from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier0 import _Source
from mythgauntlet.sim.tier2 import (
    DuelConfig,
    _combat,
    _fire_triggers,
    _main_phase,
    _Permanent,
    _Player,
    _resolve,
    duel,
    make_game_card,
)

# --- helpers -----------------------------------------------------------------------------


def _store(tmp_path, name: str, ccm: dict) -> SemanticsStore:
    authored = tmp_path / "authored"
    authored.mkdir(parents=True, exist_ok=True)
    slug = name.lower().replace(" ", "-").replace(",", "")
    (authored / f"{slug}.json").write_text(
        json.dumps({"card": {"name": name}, "ccm": ccm}), encoding="utf-8"
    )
    return SemanticsStore(authored=authored, compiled=tmp_path / "no-compiled")


def _trigger_ccm(name: str, event: str, effects: list[dict], cost: str = "{1}") -> dict:
    return {
        "name": name, "ccm_version": 1, "cost": {"mana": cost},
        "abilities": [{"kind": "triggered", "trigger": {"event": event}, "effects": effects}],
    }


def _trigger_gc(tmp_path, make_card, name: str, event: str, effects: list[dict],
                type_line: str = "Enchantment", power: int | None = None):
    card = make_card(name, mana_cost="{1}", type_line=type_line)
    if power is not None:
        card.power, card.toughness = str(power), str(power)
    ccm = _trigger_ccm(name, event, effects)
    return make_game_card(card, _store(tmp_path, name, ccm))


def _on_battlefield(gc, me: _Player, opp: _Player) -> _Permanent:
    _resolve(gc, me, opp, False)
    perm = me.battlefield[-1]
    perm.sick = False
    return perm


def _src(color="G", ready=True):
    return _Source(frozenset({color}), ready=ready)


def _vanilla(make_card, name="Bear", power=2):
    card = make_card(name, mana_cost="{1}{G}", type_line="Creature — Bear")
    card.power, card.toughness = str(power), str(power)
    return make_game_card(card, None)


# --- extraction --------------------------------------------------------------------------


def test_rung1_card_has_no_trigger_abilities(make_card):
    gc = _vanilla(make_card)
    assert gc.trigger_abilities is None  # no store -> flattened engine_draw path


def test_event_triggers_extracted_etb_and_death_excluded(tmp_path, make_card):
    card = make_card("Multi Trigger", mana_cost="{2}", type_line="Enchantment")
    ccm = {
        "name": "Multi Trigger", "ccm_version": 1, "cost": {"mana": "{2}"},
        "abilities": [
            {"kind": "triggered", "trigger": {"event": "etb"},
             "effects": [{"op": "draw", "count": 1}]},
            {"kind": "triggered", "trigger": {"event": "death"},
             "effects": [{"op": "draw", "count": 1}]},
            {"kind": "triggered", "trigger": {"event": "cast_spell"},
             "effects": [{"op": "lose_life", "amount": 1, "who": "each_opponent"}]},
            {"kind": "triggered", "trigger": {"event": "attack"},
             "effects": [{"op": "deal_damage", "amount": 1, "target": {"type": "opponent"}}]},
        ],
    }
    gc = make_game_card(card, _store(tmp_path, "Multi Trigger", ccm))
    events = [ev for ev, _ in gc.trigger_abilities]
    assert events == ["cast_spell", "attack"]  # etb -> resolve path, death -> DeathEffect


def test_instant_ccm_gets_no_event_triggers(tmp_path, make_card):
    card = make_card("Weird Instant", mana_cost="{1}", type_line="Instant")
    ccm = _trigger_ccm("Weird Instant", "cast_spell", [{"op": "draw", "count": 1}])
    gc = make_game_card(card, _store(tmp_path, "Weird Instant", ccm))
    assert gc.trigger_abilities == ()  # never a permanent -> nothing to fire from


def test_ccm_permanent_engine_draw_zeroed_no_double_count(tmp_path, make_card):
    # A cast_spell draw trigger: valued as engine_draw in the profile, but the PERMANENT
    # must not also draw per turn — the trigger now draws for real at the event.
    gc = _trigger_gc(tmp_path, make_card, "Cast Drawer", "cast_spell",
                     [{"op": "draw", "count": 1}])
    assert gc.profile.engine_draw >= 1  # the flattening still counts it (valuation prior)
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[])
    perm = _on_battlefield(gc, me, opp)
    assert perm.engine_draw == 0 and perm.triggers  # executes at the event instead


# --- firing plumbing ---------------------------------------------------------------------


def test_fire_triggers_matches_event_only(tmp_path, make_card):
    gc = _trigger_gc(tmp_path, make_card, "Upkeep Token", "upkeep",
                     [{"op": "create_token", "count": 1, "power": 1, "toughness": 1}])
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[])
    _on_battlefield(gc, me, opp)
    _fire_triggers(me, opp, "end_step")
    assert len(me.creatures()) == 0  # wrong event -> nothing
    _fire_triggers(me, opp, "upkeep")
    _fire_triggers(me, opp, "upkeep")
    assert len(me.creatures()) == 2  # fires once per upkeep


# --- cast triggers through the real cast flow --------------------------------------------


def test_cast_trigger_drains_on_each_cast(tmp_path, make_card):
    drainer = _trigger_gc(tmp_path, make_card, "Cast Drainer", "cast_spell",
                          [{"op": "lose_life", "amount": 1, "who": "each_opponent"}])
    me = _Player(name="me", library=[], sources=[_src(), _src()])
    opp = _Player(name="opp", library=[], life=40)
    _on_battlefield(drainer, me, opp)
    me.hand = [_vanilla(make_card)]
    _main_phase(me, opp, turn=3, cfg=DuelConfig())
    assert opp.life == 39  # one cast -> one drain (the drainer itself was pre-placed)


def test_cast_creature_trigger_ignores_noncreature_spells(tmp_path, make_card):
    pinger = _trigger_gc(tmp_path, make_card, "Creature Cheer", "cast_creature",
                         [{"op": "deal_damage", "amount": 1, "target": {"type": "opponent"}}])
    me = _Player(name="me", library=[], sources=[_src("U"), _src("U")])
    opp = _Player(name="opp", library=[], life=40)
    _on_battlefield(pinger, me, opp)
    blank = make_card("Nothing", mana_cost="{U}", type_line="Instant",
                      oracle_text="Draw a card.")
    me.hand = [make_game_card(blank, None)]
    me.library = [_vanilla(make_card)]
    _main_phase(me, opp, turn=3, cfg=DuelConfig())
    assert opp.life == 40  # a non-creature cast doesn't fire cast_creature


def test_opponent_cast_trigger_fires_for_the_defender(tmp_path, make_card):
    taxer = _trigger_gc(tmp_path, make_card, "Cast Taxer", "opponent_casts_spell",
                        [{"op": "deal_damage", "amount": 2, "target": {"type": "opponent"}}])
    me = _Player(name="me", library=[], life=40, sources=[_src(), _src()])
    opp = _Player(name="opp", library=[], life=40)
    _on_battlefield(taxer, opp, me)  # the TAXER belongs to the non-active player
    me.hand = [_vanilla(make_card)]
    _main_phase(me, opp, turn=3, cfg=DuelConfig())
    assert me.life == 38  # my cast fired the opponent's trigger back at me


def test_countered_spell_still_fires_cast_triggers(tmp_path, make_card):
    drainer = _trigger_gc(tmp_path, make_card, "Cast Drainer", "cast_spell",
                          [{"op": "lose_life", "amount": 3, "who": "each_opponent"}])
    bomb = make_card("Bomb", mana_cost="{2}", type_line="Creature — Beast")
    bomb.power, bomb.toughness = "8", "8"
    counter = make_card("Deny", mana_cost="{U}{U}", type_line="Instant",
                        oracle_text="Counter target spell.")
    me = _Player(name="me", library=[], sources=[_src(), _src()])
    opp = _Player(name="opp", library=[], life=40,
                  hand=[make_game_card(counter, None)], sources=[_src("U"), _src("U")])
    _on_battlefield(drainer, me, opp)
    me.hand = [make_game_card(bomb, None)]
    _main_phase(me, opp, turn=5, cfg=DuelConfig())
    assert not any(p.name == "Bomb" for p in me.battlefield)  # countered
    assert opp.life == 37  # ... but the cast trigger already fired


# --- landfall ----------------------------------------------------------------------------


def test_landfall_trigger_fires_on_land_drop(tmp_path, make_card, forest):
    grower = _trigger_gc(tmp_path, make_card, "Land Grower", "landfall",
                         [{"op": "create_token", "count": 1, "power": 1, "toughness": 1}])
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[])
    _on_battlefield(grower, me, opp)
    me.hand = [make_game_card(forest, None)]
    _main_phase(me, opp, turn=2, cfg=DuelConfig())
    assert len(me.creatures()) == 1  # the land drop spawned a token


# --- combat triggers ---------------------------------------------------------------------


def test_attacking_creature_fires_its_attack_trigger(tmp_path, make_card):
    raider = _trigger_gc(tmp_path, make_card, "Raider", "attack",
                         [{"op": "deal_damage", "amount": 1, "target": {"type": "opponent"}}],
                         type_line="Creature — Pirate", power=2)
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[], life=40)
    _on_battlefield(raider, me, opp)
    _combat(me, opp)
    assert opp.life == 37  # 2 combat + 1 attack-trigger ping


def test_non_attacking_creature_attack_trigger_does_not_fire(tmp_path, make_card):
    raider = _trigger_gc(tmp_path, make_card, "Sick Raider", "attack",
                         [{"op": "deal_damage", "amount": 5, "target": {"type": "opponent"}}],
                         type_line="Creature — Pirate", power=2)
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[], life=40)
    perm = _on_battlefield(raider, me, opp)
    perm.sick = True  # can't attack this turn
    _combat(me, opp)
    assert opp.life == 40  # no attack -> no trigger


def _attack_scope_gc(tmp_path, make_card, name, oracle, effects, type_line="Enchantment",
                     power=None):
    """Build a GameCard whose attack trigger's subject-scope comes from `oracle`."""
    card = make_card(name, mana_cost="{1}", type_line=type_line, oracle_text=oracle)
    if power is not None:
        card.power, card.toughness = str(power), str(power)
    ccm = _trigger_ccm(name, "attack", effects)
    return make_game_card(card, _store(tmp_path, name, ccm))


def test_attack_subject_scope_classification(make_card):
    from mythgauntlet.sim.tier2 import _attack_subject_scope

    def mk(oracle, type_line):
        return make_card("X", mana_cost="{1}", type_line=type_line, oracle_text=oracle)

    # self: a creature's own "this creature attacks"
    assert _attack_subject_scope(mk("Whenever this creature attacks, draw a card.",
                                    "Creature - Cat")) == "self"
    # global_each: "a creature you control attacks" fires per attacker
    assert _attack_subject_scope(
        mk("Whenever a creature you control attacks, create a 1/1.", "Enchantment")
    ) == "global_each"
    assert _attack_subject_scope(
        mk("Whenever another creature you control attacks, it gets +1/+0.", "Creature - Cat")
    ) == "global_each"
    # global_once: plural / "you attack" / attacks-alone / a non-creature with no wording
    assert _attack_subject_scope(
        mk("Whenever one or more creatures you control attack, draw a card.", "Enchantment")
    ) == "global_once"
    assert _attack_subject_scope(
        mk("Whenever you attack, each opponent loses 1 life.", "Enchantment")
    ) == "global_once"
    assert _attack_subject_scope(
        mk("Whenever a creature you control attacks alone, it gets +2/+2.", "Enchantment")
    ) == "global_once"
    assert _attack_subject_scope(mk("Whenever this attacks, ping.", "Artifact")) == "global_once"


def test_global_each_attack_trigger_fires_once_per_attacker(tmp_path, make_card):
    # "Whenever a creature you control attacks, deal 1" -> once per attacking creature.
    drummer = _attack_scope_gc(
        tmp_path, make_card, "War Drummer",
        "Whenever a creature you control attacks, War Drummer deals 1 damage to that player.",
        [{"op": "deal_damage", "amount": 1, "target": {"type": "opponent"}}],
    )
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[], life=40)
    _on_battlefield(drummer, me, opp)
    for name in ("A", "B", "C"):
        me.battlefield.append(
            _Permanent(name=name, power=2, toughness=2, is_creature=True, sick=False)
        )
    _combat(me, opp)
    assert opp.life == 31  # 6 combat + 3 drummer pings (one per attacker)


def test_global_once_attack_trigger_fires_once_regardless_of_width(tmp_path, make_card):
    banner = _attack_scope_gc(
        tmp_path, make_card, "Battle Cry",
        "Whenever one or more creatures you control attack, Battle Cry deals 1 damage.",
        [{"op": "deal_damage", "amount": 1, "target": {"type": "opponent"}}],
    )
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[], life=40)
    _on_battlefield(banner, me, opp)
    for name in ("A", "B", "C"):
        me.battlefield.append(
            _Permanent(name=name, power=2, toughness=2, is_creature=True, sick=False)
        )
    _combat(me, opp)
    assert opp.life == 33  # 6 combat + 1 ping (once, not per attacker)


def test_global_each_trigger_on_attacking_creature_counts_itself(tmp_path, make_card):
    # A lord that itself attacks: "a creature you control attacks" counts all attackers,
    # including the lord -> 2 attackers => 2 tokens.
    lord = _attack_scope_gc(
        tmp_path, make_card, "Token Lord",
        "Whenever a creature you control attacks, create a 1/1 white Soldier token.",
        [{"op": "create_token", "count": 1, "power": 1, "toughness": 1}],
        type_line="Creature - Captain", power=2,
    )
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[], life=40)
    _on_battlefield(lord, me, opp)
    me.battlefield.append(
        _Permanent(name="Ally", power=2, toughness=2, is_creature=True, sick=False)
    )
    _combat(me, opp)
    # 2 attackers (lord + ally) -> 2 new tokens; battlefield had lord + ally, now +2 = 4
    assert len(me.creatures()) == 4


def test_noncreature_attack_trigger_fires_once_per_combat(tmp_path, make_card):
    banner = _trigger_gc(tmp_path, make_card, "War Banner", "attack",
                         [{"op": "deal_damage", "amount": 1, "target": {"type": "opponent"}}])
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[], life=40)
    _on_battlefield(banner, me, opp)
    for name in ("A", "B"):
        me.battlefield.append(
            _Permanent(name=name, power=2, toughness=2, is_creature=True, sick=False)
        )
    _combat(me, opp)
    assert opp.life == 35  # 4 combat + 1 banner ping (once per combat, not per attacker)


def test_combat_damage_trigger_draws_when_unblocked(tmp_path, make_card):
    saboteur = _trigger_gc(tmp_path, make_card, "Saboteur", "combat_damage_to_player",
                           [{"op": "draw", "count": 1}],
                           type_line="Creature — Rogue", power=1)
    me = _Player(name="me", library=[_vanilla(make_card)])
    opp = _Player(name="opp", library=[], life=40)
    _on_battlefield(saboteur, me, opp)
    _combat(me, opp)
    assert len(me.hand) == 1 and opp.life == 39  # connected -> drew


def test_combat_damage_trigger_silent_when_blocked(tmp_path, make_card):
    saboteur = _trigger_gc(tmp_path, make_card, "Saboteur", "combat_damage_to_player",
                           [{"op": "draw", "count": 1}],
                           type_line="Creature — Rogue", power=1)
    me = _Player(name="me", library=[_vanilla(make_card)])
    opp = _Player(name="opp", library=[], life=1)  # lethal on board -> the wall must block
    _on_battlefield(saboteur, me, opp)
    opp.battlefield.append(  # a wall that blocks and survives
        _Permanent(name="Wall", power=0, toughness=4, is_creature=True, sick=False)
    )
    _combat(me, opp)
    assert len(me.hand) == 0 and opp.life == 1  # blocked -> no player damage, no draw


# --- turn-structure hooks (through a real game) -------------------------------------------


def test_upkeep_drain_wins_games_via_play_game(tmp_path, make_card, forest):
    """A deck of upkeep-drainers beats a blank deck long before the turn cap: proof the
    upkeep hook fires inside the real game loop and its life loss ends games."""
    drainer_card = make_card("Upkeep Drainer", mana_cost="{1}", type_line="Enchantment")
    ccm = _trigger_ccm("Upkeep Drainer", "upkeep",
                       [{"op": "lose_life", "amount": 3, "who": "each_opponent"}])
    store = _store(tmp_path, "Upkeep Drainer", ccm)
    wastes = make_card("Wastes", type_line="Basic Land", produced_mana=("C",))
    drain_deck = [(wastes, 20), (drainer_card, 20)]
    blank = make_card("Do Nothing", mana_cost="{4}", type_line="Enchantment",
                      oracle_text="It does nothing at all.")
    blank_deck = [(wastes, 20), (blank, 20)]
    cfg = DuelConfig(games=40, seed=11, max_turns=30)
    result = duel(drain_deck, None, blank_deck, None, cfg, store=store)
    assert result.winrate_a > 0.9  # drains win games, not just adjudication
    assert result.avg_turns < 25  # and they END them early (life hit zero mid-game)


def test_trigger_execution_is_deterministic(tmp_path, make_card):
    drainer_card = make_card("Cast Drainer", mana_cost="{1}", type_line="Enchantment")
    ccm = _trigger_ccm("Cast Drainer", "cast_spell",
                       [{"op": "lose_life", "amount": 1, "who": "each_opponent"}])
    store = _store(tmp_path, "Cast Drainer", ccm)
    wastes = make_card("Wastes", type_line="Basic Land", produced_mana=("C",))
    bear = make_card("Bear", mana_cost="{1}", type_line="Creature — Bear")
    bear.power, bear.toughness = "2", "2"
    deck_a = [(wastes, 20), (drainer_card, 10), (bear, 10)]
    deck_b = [(wastes, 20), (bear, 20)]
    cfg = DuelConfig(games=30, seed=5, max_turns=20)
    assert duel(deck_a, None, deck_b, None, cfg, store=store) == duel(
        deck_a, None, deck_b, None, cfg, store=store
    )
