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
