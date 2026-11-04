"""The tier2 executor must not point an effect at the opponent when its target says otherwise.

Found by scripts/effect_audit.py (every stored effect run on a synthetic board): of 18,219 effects
aimed at 'self', 'you', or a non-battlefield zone, 298 changed the opponent's state anyway. The real
bugs were player-type deal_damage with controller 'you' ("Ancient Tomb deals 2 damage to you",
Aftershock), deal_damage aimed at the source itself, and a MASS return_to_hand from a graveyard.
Creature-type 'controller: you' damage is left alone on purpose: it is the compiler's spelling of the
source in a bite effect ("target creature you control deals damage equal to its power ...").
"""
from __future__ import annotations

import json

from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier2 import _Permanent, _Player, _resolve, make_game_card


def _store(tmp_path, name, ccm):
    d = tmp_path / "authored"
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.json").write_text(json.dumps({"card": {"name": name}, "ccm": ccm}), encoding="utf-8")
    return SemanticsStore(authored=d, compiled=tmp_path / "none")


def _run(tmp_path, make_card, effect):
    card = make_card("Test Effect", mana_cost="{1}", type_line="Sorcery")
    ccm = {"name": "Test Effect", "ccm_version": 1, "cost": {"mana": "{1}"},
           "abilities": [{"kind": "spell_effect", "effects": [effect]}]}
    gc = make_game_card(card, _store(tmp_path, "Test Effect", ccm))
    mine = _Permanent(name="Mine", power=2, toughness=2, is_creature=True, sick=False)
    foe = _Permanent(name="Foe", power=3, toughness=3, is_creature=True, sick=False)
    me = _Player(name="me", library=[], battlefield=[mine], life=40)
    opp = _Player(name="opp", library=[], battlefield=[foe], life=40)
    _resolve(gc, me, opp, False)
    return me, opp


def test_damage_to_you_does_not_hit_the_opponent(tmp_path, make_card):
    _, opp = _run(tmp_path, make_card, {"op": "deal_damage", "amount": 3,
                                        "target": {"type": "player", "controller": "you"}})
    assert opp.life == 40 and len(opp.creatures()) == 1


def test_damage_to_the_source_itself_does_not_hit_the_opponent(tmp_path, make_card):
    _, opp = _run(tmp_path, make_card, {"op": "deal_damage", "amount": 5, "target": {"self": True}})
    assert opp.life == 40 and len(opp.creatures()) == 1


def test_damage_to_an_opponent_still_lands(tmp_path, make_card):
    _, opp = _run(tmp_path, make_card, {"op": "deal_damage", "amount": 3,
                                        "target": {"type": "player", "controller": "opponent"}})
    assert opp.life == 37


def test_creature_damage_with_controller_you_is_left_alone(tmp_path, make_card):
    # the bite shape: controller 'you' names the SOURCE; the damage still lands on their creature
    _, opp = _run(tmp_path, make_card, {"op": "deal_damage", "amount": 3,
                                        "target": {"type": "creature", "controller": "you", "count": 1}})
    assert opp.creatures() == []


def test_mass_return_from_a_graveyard_does_not_bounce_the_battlefield(tmp_path, make_card):
    me, opp = _run(tmp_path, make_card, {"op": "return_to_hand",
                                         "target": {"type": "creature", "count": "all",
                                                    "zone": "graveyard", "controller": "you"}})
    assert len(opp.creatures()) == 1 and len(me.creatures()) == 1


def test_mass_bounce_from_the_battlefield_still_works(tmp_path, make_card):
    me, opp = _run(tmp_path, make_card, {"op": "return_to_hand",
                                         "target": {"type": "creature", "count": "all"}})
    assert opp.creatures() == [] and me.creatures() == []
