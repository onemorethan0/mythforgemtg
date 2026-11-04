"""tier2's exile/destroy branch only runs when the effect really names an opposing permanent.

The branch skipped `controller: "you"` and nothing else, so an effect aimed at the SOURCE
("exile this creature", "destroy this at end of combat") or at a non-battlefield zone ("exile
target card from a graveyard") still killed the opponent's best creature. Measured over the store
2026-11-04: 271 exile(self), 25 destroy(self) and 83 off-battlefield exile effects reached it.
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


def _run(tmp_path, make_card, op, target):
    card = make_card("Test Effect", mana_cost="{1}", type_line="Sorcery")
    ccm = {"name": "Test Effect", "ccm_version": 1, "cost": {"mana": "{1}"},
           "abilities": [{"kind": "spell_effect", "effects": [{"op": op, "target": target}]}]}
    gc = make_game_card(card, _store(tmp_path, "Test Effect", ccm))
    me = _Player(name="me", library=[])
    foe = _Permanent(name="Big Foe", power=5, toughness=5, is_creature=True, sick=False)
    opp = _Player(name="opp", library=[], battlefield=[foe])
    _resolve(gc, me, opp, False)
    return opp


def test_real_removal_still_removes(tmp_path, make_card):
    opp = _run(tmp_path, make_card, "exile", {"type": "creature", "controller": "opponent", "count": 1})
    assert opp.creatures() == []
    opp = _run(tmp_path, make_card, "destroy", {"type": "creature", "controller": "any", "count": 1})
    assert opp.creatures() == []


def test_exiling_the_source_does_not_kill_an_opposing_creature(tmp_path, make_card):
    opp = _run(tmp_path, make_card, "exile", {"self": True})
    assert len(opp.creatures()) == 1


def test_destroying_the_source_does_not_kill_an_opposing_creature(tmp_path, make_card):
    opp = _run(tmp_path, make_card, "destroy", {"self": True, "type": "creature"})
    assert len(opp.creatures()) == 1


def test_exiling_from_a_graveyard_does_not_kill_an_opposing_creature(tmp_path, make_card):
    opp = _run(tmp_path, make_card, "exile",
               {"type": "creature", "zone": "graveyard", "controller": "opponent", "count": 1})
    assert len(opp.creatures()) == 1


def test_other_off_battlefield_zones_are_also_skipped(tmp_path, make_card):
    for zone in ("hand", "library", "exile", "stack", "command"):
        opp = _run(tmp_path, make_card, "exile", {"type": "creature", "zone": zone, "count": 1})
        assert len(opp.creatures()) == 1, zone


def test_an_explicit_battlefield_zone_is_still_removal(tmp_path, make_card):
    opp = _run(tmp_path, make_card, "exile", {"type": "permanent", "zone": "battlefield", "count": 1})
    assert opp.creatures() == []
