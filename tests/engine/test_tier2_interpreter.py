"""T2 executes CCM resolution effects through the interpreter path. Offline, synthetic."""

from __future__ import annotations

import json

from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier2 import _Permanent, _Player, _resolve, make_game_card


def _store(tmp_path, name: str, ccm: dict) -> SemanticsStore:
    authored = tmp_path / "authored"
    authored.mkdir(parents=True, exist_ok=True)
    slug = name.lower().replace(" ", "-").replace(",", "")
    (authored / f"{slug}.json").write_text(
        json.dumps({"card": {"name": name}, "ccm": ccm}), encoding="utf-8"
    )
    return SemanticsStore(authored=authored, compiled=tmp_path / "no-compiled")


def _spell_ccm(name: str, effects: list[dict], kind: str = "spell_effect", **extra) -> dict:
    ability = {"kind": kind, "effects": effects, **extra}
    return {"name": name, "ccm_version": 1, "cost": {"mana": "{1}"}, "abilities": [ability]}


def test_rung1_card_has_no_resolve_abilities(make_card):
    card = make_card("Vanilla Bear", mana_cost="{1}{G}", type_line="Creature — Bear")
    assert make_game_card(card, None).resolve_abilities is None  # no store -> flattened path


def test_ccm_etb_draw_fires_via_interpreter(tmp_path, make_card):
    card = make_card("Test Drawer", mana_cost="{1}{U}", type_line="Creature — Wizard")
    card.power, card.toughness = "1", "1"
    ccm = _spell_ccm(
        "Test Drawer", [{"op": "draw", "count": 2}],
        kind="triggered", trigger={"event": "etb"},
    )
    gc = make_game_card(card, _store(tmp_path, "Test Drawer", ccm))
    assert gc.resolve_abilities is not None and len(gc.resolve_abilities) == 1

    me = _Player(name="me", library=[gc, gc, gc])   # 3 cards available to draw
    opp = _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    assert len(me.hand) == 2                          # drew 2 via the interpreter
    assert any(p.name == "Test Drawer" for p in me.battlefield)  # creature entered play


def test_ccm_spell_damage_fires(tmp_path, make_card):
    card = make_card("Test Bolt", mana_cost="{R}", type_line="Instant")
    ccm = _spell_ccm("Test Bolt", [{"op": "deal_damage", "amount": 3,
                                    "target": {"type": "opponent"}}])
    gc = make_game_card(card, _store(tmp_path, "Test Bolt", ccm))
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[], life=40)
    _resolve(gc, me, opp, False)
    assert opp.life == 37
    assert not me.battlefield                          # an instant leaves no permanent


def test_ccm_two_token_effects_both_fire(tmp_path, make_card):
    # the flattening kept only the LAST create_token; per-effect execution spawns BOTH.
    card = make_card("Test Tokens", mana_cost="{2}{W}", type_line="Sorcery")
    ccm = _spell_ccm("Test Tokens", [
        {"op": "create_token", "count": 2, "power": 1, "toughness": 1},
        {"op": "create_token", "count": 1, "power": 3, "toughness": 3},
    ])
    gc = make_game_card(card, _store(tmp_path, "Test Tokens", ccm))
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    assert len(me.creatures()) == 3                    # 2 + 1, both effects fired


def _bear(name):
    return _Permanent(name=name, power=2, toughness=2, is_creature=True, sick=False)


def test_x_basis_creatures_resolves_from_the_board(tmp_path, make_card):
    # "deal X damage where X is the number of creatures you control" (x_basis, prompt v8+)
    card = make_card("Crowd Surge", mana_cost="{X}{R}", type_line="Sorcery")
    ccm = _spell_ccm("Crowd Surge", [{"op": "deal_damage", "amount": "X",
                                      "x_basis": "creatures_you_control",
                                      "target": {"type": "opponent"}}])
    gc = make_game_card(card, _store(tmp_path, "Crowd Surge", ccm))
    me = _Player(name="me", library=[], battlefield=[_bear("A"), _bear("B"), _bear("C")])
    opp = _Player(name="opp", library=[], life=40)
    _resolve(gc, me, opp, False)
    assert opp.life == 37  # X resolved to 3 live creatures, not the default 1


def test_x_without_live_basis_stays_default(tmp_path, make_card):
    # mana_paid is a COST-side basis: live state can't know it -> modest default (1)
    card = make_card("Test Blaze", mana_cost="{X}{R}", type_line="Sorcery")
    ccm = _spell_ccm("Test Blaze", [{"op": "deal_damage", "amount": "X",
                                     "x_basis": "mana_paid",
                                     "target": {"type": "opponent"}}])
    gc = make_game_card(card, _store(tmp_path, "Test Blaze", ccm))
    me = _Player(name="me", library=[], battlefield=[_bear("A"), _bear("B")])
    opp = _Player(name="opp", library=[], life=40)
    _resolve(gc, me, opp, False)
    assert opp.life == 39  # X -> 1, board size is irrelevant to a cost-side X


def test_each_amount_scales_to_the_board(tmp_path, make_card):
    # "create a 1/1 for each creature you control" -> board-aware resolver, not X->1
    card = make_card("Swarm Call", mana_cost="{3}{G}", type_line="Sorcery")
    ccm = _spell_ccm("Swarm Call", [{"op": "create_token", "count": "each",
                                     "power": 1, "toughness": 1}])
    gc = make_game_card(card, _store(tmp_path, "Swarm Call", ccm))
    me = _Player(name="me", library=[], battlefield=[_bear("A"), _bear("B"), _bear("C")])
    opp = _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    assert len(me.creatures()) == 6                    # 3 existing + 3 tokens ("each" = 3)


def test_add_counter_self_target_buffs_power_and_toughness(tmp_path, make_card):
    """add_counter was a complete no-op store-wide before this (4,519 uses, the 2nd most
    common op in the compiled store) — this is the additive fix for its dominant real
    shape: a creature counting up on itself (Managorger Hydra, Walking Ballista, ...)."""
    card = make_card("Test Grower", mana_cost="{1}{G}", type_line="Creature — Ooze")
    card.power, card.toughness = "1", "1"
    ccm = _spell_ccm(
        "Test Grower", [{"op": "add_counter", "count": 2, "counter_type": "plus"}],
        kind="triggered", trigger={"event": "etb"},
    )
    gc = make_game_card(card, _store(tmp_path, "Test Grower", ccm))
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    grower = next(p for p in me.battlefield if p.name == "Test Grower")
    assert (grower.power, grower.toughness, grower.counters) == (3, 3, 2)


def test_add_counter_other_creature_target_is_not_modeled(tmp_path, make_card):
    """No targeting infra exists for this op — guessing WHICH creature gets the counter
    would fabricate a value, so an explicit non-self target stays a no-op (honest
    under-count), same as before this change."""
    card = make_card("Test Blesser", mana_cost="{1}{G}", type_line="Sorcery")
    ccm = _spell_ccm("Test Blesser", [{"op": "add_counter", "count": 2,
                                        "counter_type": "plus",
                                        "target": {"type": "creature", "controller": "you"}}])
    gc = make_game_card(card, _store(tmp_path, "Test Blesser", ccm))
    me = _Player(name="me", library=[], battlefield=[_bear("A")])
    opp = _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    bear = me.battlefield[0]
    assert (bear.power, bear.toughness, bear.counters) == (2, 2, 0)  # untouched


def test_counters_on_this_x_basis_resolves_from_the_permanent(make_card):
    """A later trigger reading back counters an earlier resolution placed on itself —
    the same x_basis mechanism as creatures_you_control/lands_you_control, now covering
    the single most common non-cost basis in the store (118 uses)."""
    from mythgauntlet.sim.tier2 import _fire_perm_triggers

    ability = {
        "kind": "triggered", "trigger": {"event": "upkeep"},
        "effects": [{"op": "deal_damage", "amount": "X", "x_basis": "counters_on_this",
                     "target": {"type": "opponent"}}],
    }
    # 12 counters, deliberately above _EACH_CAP (6) -- a counter pile is a STAT, not a
    # board count, and an Ashling/Braid-of-Fire-style engine exists specifically to grow
    # past that. A board-count cap would silently gut the exact deck this basis is for.
    perm = _Permanent(name="Counter Pile", power=0, toughness=0, is_creature=False,
                       sick=False, counters=12, triggers=(("upkeep", ability),))
    me = _Player(name="me", library=[], battlefield=[perm])
    opp = _Player(name="opp", library=[], life=40)
    _fire_perm_triggers(perm, me, opp, "upkeep")
    assert opp.life == 28  # X resolved to the 12 live counters, not capped at 6


def test_artifacts_you_control_x_basis_resolves_from_the_board(tmp_path, make_card):
    card = make_card("Test Inventory", mana_cost="{2}{R}", type_line="Sorcery")
    ccm = _spell_ccm("Test Inventory", [{"op": "deal_damage", "amount": "X",
                                         "x_basis": "artifacts_you_control",
                                         "target": {"type": "opponent"}}])
    gc = make_game_card(card, _store(tmp_path, "Test Inventory", ccm))
    rock = _Permanent(name="Rock", power=0, toughness=0, is_creature=False, is_artifact=True)
    me = _Player(name="me", library=[], battlefield=[_bear("A"), rock, rock])
    opp = _Player(name="opp", library=[], life=40)
    _resolve(gc, me, opp, False)
    assert opp.life == 38  # 2 artifacts, the non-artifact bear doesn't count


def test_target_power_x_basis_resolves_to_the_source_creatures_power():
    """target_power is NOT the damage recipient's power -- sampled real cards (Abyssal
    Hunter, Aggressive Instinct) and the dominant shape is a fight effect: the SOURCE
    creature deals damage equal to its own power."""
    from mythgauntlet.sim.tier2 import _fire_perm_triggers

    ability = {
        "kind": "triggered", "trigger": {"event": "upkeep"},
        "effects": [{"op": "deal_damage", "amount": "X", "x_basis": "target_power",
                     "target": {"type": "player", "controller": "opponent"}}],
    }
    fighter = _Permanent(name="Fighter", power=7, toughness=7, is_creature=True,
                         sick=False, triggers=(("upkeep", ability),))
    me = _Player(name="me", library=[], battlefield=[fighter])
    opp = _Player(name="opp", library=[], life=40)
    _fire_perm_triggers(fighter, me, opp, "upkeep")
    assert opp.life == 33  # X resolved to the source's power (7), not the default 1


def test_target_power_x_basis_stays_default_without_a_creature_source(tmp_path, make_card):
    """A mass-effect SPELL scaling off someone else's power (Alpha Brawl, Allies at Last)
    has no creature source in this context -- fall back to the honest default rather than
    guessing whose power it means."""
    card = make_card("Test Alpha Brawl", mana_cost="{2}{B}", type_line="Sorcery")
    ccm = _spell_ccm("Test Alpha Brawl", [{"op": "deal_damage", "amount": "X",
                                           "x_basis": "target_power",
                                           "target": {"type": "player", "controller": "opponent"}}])
    gc = make_game_card(card, _store(tmp_path, "Test Alpha Brawl", ccm))
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[], life=40)
    _resolve(gc, me, opp, False)
    assert opp.life == 39  # no creature source (an instant/sorcery) -> default 1


def test_power_x_basis_is_an_alias_for_target_power(tmp_path, make_card):
    """`power` and `target_power` are the SAME concept under two names, not different
    ones -- the compiler's x_basis field is free text with no closed enum, and sampling
    all 104 stored `power`-basis effects (2026-09-10) showed the same "deals damage equal
    to its power" shape target_power already resolves (Aerie Ouphes, Cyclops Gladiator,
    Durkwood Tracker, Cinder Shade, Champion of Wits)."""
    from mythgauntlet.sim.tier2 import _fire_perm_triggers

    ability = {
        "kind": "triggered", "trigger": {"event": "upkeep"},
        "effects": [{"op": "deal_damage", "amount": "X", "x_basis": "power",
                     "target": {"type": "player", "controller": "opponent"}}],
    }
    fighter = _Permanent(name="Fighter", power=7, toughness=7, is_creature=True,
                         sick=False, triggers=(("upkeep", ability),))
    me = _Player(name="me", library=[], battlefield=[fighter])
    opp = _Player(name="opp", library=[], life=40)
    _fire_perm_triggers(fighter, me, opp, "upkeep")
    assert opp.life == 33  # resolved via the same source-power path as target_power


def test_greatest_power_x_basis_resolves_from_the_board(tmp_path, make_card):
    """"gain life equal to the greatest power among creatures you control" (Huatli,
    Warrior Poet; Garruk, Primal Hunter) -- sampled all 14 stored uses, unambiguous
    every time, unlike target_toughness's mixed referents."""
    card = make_card("Test Huatli", mana_cost="{2}{G}", type_line="Sorcery")
    ccm = _spell_ccm("Test Huatli", [{"op": "gain_life", "amount": "X",
                                      "x_basis": "greatest_power"}])
    gc = make_game_card(card, _store(tmp_path, "Test Huatli", ccm))
    me = _Player(name="me", library=[], life=40,
                battlefield=[_bear("A"), _Permanent(name="Big", power=9, toughness=9,
                                                     is_creature=True)])
    opp = _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    assert me.life == 49  # 9, the greatest power on board, not the 2/2 bear's


def test_greatest_power_with_no_creatures_is_a_real_zero_not_a_fabricated_one(
    tmp_path, make_card
):
    """The bug this whole pair of fixes exists for: Huatli's "+2: gain life equal to the
    greatest power among creatures you control" is trivially reachable with an EMPTY
    board (activate turn 1, no creatures out) -- and the shared `max(1, ...)` floor in
    `amount()` used to turn that real zero into a fabricated 1 life gained. Live-resolved
    values are measurements, not guesses, so they must not be floored up."""
    card = make_card("Test Huatli", mana_cost="{2}{G}", type_line="Sorcery")
    ccm = _spell_ccm("Test Huatli", [{"op": "gain_life", "amount": "X",
                                      "x_basis": "greatest_power"}])
    gc = make_game_card(card, _store(tmp_path, "Test Huatli", ccm))
    me = _Player(name="me", library=[], life=40, battlefield=[])
    opp = _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    assert me.life == 40  # gained exactly 0, not floored to 1


def test_a_zero_power_source_deals_zero_not_one(tmp_path, make_card):
    """Retroactive fix, not a new one: a 0-power creature (a manland before animation, a
    freshly-made 0/0 token) "dealing damage equal to its power" via target_power/power
    was dealing 1 before this fix -- the same near-miss shape, one basis over."""
    from mythgauntlet.sim.tier2 import _fire_perm_triggers

    ability = {
        "kind": "triggered", "trigger": {"event": "upkeep"},
        "effects": [{"op": "deal_damage", "amount": "X", "x_basis": "target_power",
                     "target": {"type": "player", "controller": "opponent"}}],
    }
    dud = _Permanent(name="Dud", power=0, toughness=1, is_creature=True,
                     sick=False, triggers=(("upkeep", ability),))
    me = _Player(name="me", library=[], battlefield=[dud])
    opp = _Player(name="opp", library=[], life=40)
    _fire_perm_triggers(dud, me, opp, "upkeep")
    assert opp.life == 40  # 0 power -> 0 damage, not the old floor of 1


def test_counters_on_this_with_zero_counters_is_zero_not_one():
    """Same fix, third basis: a permanent with no counters yet (activated the turn it
    entered, before anything grew it) reading X from counters_on_this must resolve 0."""
    from mythgauntlet.sim.tier2 import _fire_perm_triggers

    ability = {
        "kind": "triggered", "trigger": {"event": "upkeep"},
        "effects": [{"op": "deal_damage", "amount": "X", "x_basis": "counters_on_this",
                     "target": {"type": "opponent"}}],
    }
    perm = _Permanent(name="Empty Pile", power=0, toughness=0, is_creature=False,
                      sick=False, counters=0, triggers=(("upkeep", ability),))
    me = _Player(name="me", library=[], battlefield=[perm])
    opp = _Player(name="opp", library=[], life=40)
    _fire_perm_triggers(perm, me, opp, "upkeep")
    assert opp.life == 40  # 0 counters -> 0 damage


def test_the_genuinely_unknown_fallback_still_defaults_to_one(tmp_path, make_card):
    """The floor-of-0 fix is scoped to LIVE-RESOLVED values only. A bare X with no
    x_basis at all is still genuinely unknown (a chosen/cost amount, per the module's own
    doctrine) and keeps the modest default of 1 -- not 0, which would silently zero out
    every unresolved X spell instead of under-counting it honestly."""
    card = make_card("Test Fireball", mana_cost="{X}{R}", type_line="Sorcery")
    ccm = _spell_ccm("Test Fireball", [{"op": "deal_damage", "amount": "X",
                                        "target": {"type": "opponent"}}])
    gc = make_game_card(card, _store(tmp_path, "Test Fireball", ccm))
    me = _Player(name="me", library=[])
    opp = _Player(name="opp", library=[], life=40)
    _resolve(gc, me, opp, False)
    assert opp.life == 39  # unknown X -> the modest default of 1, unchanged


def test_proliferate_grows_the_casters_own_countered_permanents(tmp_path, make_card):
    """proliferate (CR 122.7) is a new op (2026-09-08) -- 94 cards use the real keyword and
    none could be modeled before (no op existed for it at all). Grows every one of the
    caster's own already-countered permanents; a permanent with no counters is untouched,
    and a non-creature's power/toughness (base 0/0 in this engine) doesn't move."""
    card = make_card("Test Proliferate", mana_cost="{1}{U}", type_line="Instant")
    ccm = _spell_ccm("Test Proliferate", [{"op": "proliferate"}])
    gc = make_game_card(card, _store(tmp_path, "Test Proliferate", ccm))
    grown = _Permanent(name="Grown", power=3, toughness=3, is_creature=True, counters=2)
    untouched_creature = _Permanent(name="Bystander", power=2, toughness=2, is_creature=True)
    grown_artifact = _Permanent(name="Gadget", power=0, toughness=0, is_creature=False,
                                is_artifact=True, counters=1)
    me = _Player(name="me", library=[], battlefield=[grown, untouched_creature, grown_artifact])
    opp = _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    assert (grown.counters, grown.power, grown.toughness) == (3, 4, 4)
    assert (untouched_creature.counters, untouched_creature.power,
            untouched_creature.toughness) == (0, 2, 2)
    assert (grown_artifact.counters, grown_artifact.power, grown_artifact.toughness) == (2, 0, 0)


def test_proliferate_does_not_touch_the_opponents_counters(tmp_path, make_card):
    """No infrastructure exists for a genuine per-permanent CHOICE, so the safe scope is
    the caster's own board only -- an opponent's counters (poison, a rival planeswalker's
    loyalty) are left alone rather than guessed at."""
    card = make_card("Test Proliferate 2", mana_cost="{1}{U}", type_line="Instant")
    ccm = _spell_ccm("Test Proliferate 2", [{"op": "proliferate"}])
    gc = make_game_card(card, _store(tmp_path, "Test Proliferate 2", ccm))
    theirs = _Permanent(name="Their Hydra", power=5, toughness=5, is_creature=True, counters=3)
    me = _Player(name="me", library=[], battlefield=[])
    opp = _Player(name="opp", library=[], battlefield=[theirs])
    _resolve(gc, me, opp, False)
    assert (theirs.counters, theirs.power, theirs.toughness) == (3, 5, 5)


def test_grant_ability_haste_self_clears_summoning_sickness(tmp_path, make_card):
    """grant_ability is new (2026-09-08) -- add_counter was being fabricated with fake
    counter types like 'haste'/'flying' for exactly this shape of effect. Haste is the
    one keyword worth executing here: it maps directly to the `sick` field the engine
    already reads for attack/tap eligibility, so granting it self-target is a real state
    change, not a guess."""
    card = make_card("Test Hasty", mana_cost="{2}{R}", type_line="Creature — Elemental")
    card.power, card.toughness = "3", "3"
    ccm = _spell_ccm(
        "Test Hasty", [{"op": "grant_ability", "ability": "haste"}],
        kind="triggered", trigger={"event": "etb"},
    )
    gc = make_game_card(card, _store(tmp_path, "Test Hasty", ccm))
    me, opp = _Player(name="me", library=[]), _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    hasty = next(p for p in me.battlefield if p.name == "Test Hasty")
    assert hasty.sick is False


def test_grant_ability_other_keywords_and_targets_stay_inert(tmp_path, make_card):
    """Evasion/damage-prevention keywords (flying, trample, indestructible, ...) are
    correctly NOT executed -- this engine's combat resolution doesn't read them for any
    creature yet, printed or granted, so pretending otherwise would fabricate an
    advantage this engine can't actually enforce in combat. A non-self target (the
    common real shape: "target creature gains X") also stays inert -- no targeting
    infra, same discipline as add_counter."""
    card = make_card("Test Flight Grant", mana_cost="{1}{U}", type_line="Instant")
    ccm = _spell_ccm("Test Flight Grant", [
        {"op": "grant_ability", "ability": "flying",
         "target": {"type": "creature", "count": 1}},
    ])
    gc = make_game_card(card, _store(tmp_path, "Test Flight Grant", ccm))
    bear = _Permanent(name="Bear", power=2, toughness=2, is_creature=True, sick=True)
    me = _Player(name="me", library=[], battlefield=[bear])
    opp = _Player(name="opp", library=[])
    _resolve(gc, me, opp, False)
    assert bear.sick is True  # untouched -- not self, and not haste anyway
