"""Pump Equipment and Auras in the goldfish sim (tier0). Gold set: the real cards' printed text."""
from __future__ import annotations

from mythgauntlet.sim.tier0 import SimConfig, _attachment, simulate

CFG = SimConfig(turns=12, runs=150, seed=5)
EQ, AURA = "Artifact — Equipment", "Enchantment — Aura"


def test_attachment_gold_set():
    bone = _attachment(EQ, "Equipped creature gets +2/+0.\nEquip {1}")
    assert (bone.kind, bone.bonus, bone.equip_cost) == ("equip", 2, "{1}")
    cleave = _attachment(EQ, "Flash\nThis spell costs {1} less to cast for each attacking creature "
                             "you control.\nWhen this Equipment enters, attach it to target "
                             "creature you control.\nEquipped creature gets +1/+1 and has double "
                             "strike and trample.\nEquip {3}")
    assert cleave.bonus == 1 and cleave.double_strike
    rancor = _attachment(AURA, "Enchant creature\nEnchanted creature gets +2/+0 and has trample.\n"
                               "When this Aura is put into a graveyard from the battlefield, "
                               "return it to its owner's hand.")
    assert rancor.kind == "aura" and rancor.bonus == 2 and rancor.returns_to_hand
    exo = _attachment(EQ, "Equipped creature gets +2/+2 and has infect.\nWhenever this Equipment "
                          "becomes unattached from a permanent, sacrifice that permanent.\nEquip {2}")
    assert exo.infect and exo.bonus == 2


def test_attachments_it_cannot_read_are_none():
    assert _attachment(EQ, "Equipped creature has shroud and haste.\nEquip {0}") is None
    assert _attachment(AURA, "Enchant creature\nEnchanted creature gets +1/+1 for each "
                             "Aura you control.") is None
    assert _attachment(AURA, "Enchant creature\nEnchanted creature can't attack or block.") is None
    assert _attachment(AURA, "Enchant creature\nYou control enchanted creature.\nEnchanted "
                             "creature gets +1/+1.") is None
    assert _attachment(EQ, "Equipped creature gets +3/+3.\nEquip legendary creature {1}") is None


def _plains(make_card):
    return make_card("Plains", type_line="Basic Land — Plains", produced_mana=("W",),
                     color_identity=("W",))


def _bear(make_card, name="Bear", power="2"):
    c = make_card(name, mana_cost="{1}{W}", type_line="Creature — Bear")
    c.power, c.toughness = power, "2"
    return c


def _sums(runs):
    for r in runs:
        total = r.damage_by_turn[-1] if r.damage_by_turn else 0
        assert sum(r.damage_by_card.values()) == total
        assert sum(r.damage_by_source.values()) == total


def _mean_kill(runs):
    return sum(r.kill_turn or 99 for r in runs) / len(runs)


def test_equipment_and_auras_add_damage(make_card):
    bone = make_card("Bonesplitter", mana_cost="{1}", type_line=EQ,
                     oracle_text="Equipped creature gets +2/+0.\nEquip {1}")
    rancor = make_card("Rancor", mana_cost="{W}", type_line=AURA,
                       oracle_text="Enchant creature\nEnchanted creature gets +2/+0 and has "
                                   "trample.\nWhen this Aura is put into a graveyard from the "
                                   "battlefield, return it to its owner's hand.")
    rock = make_card("Rock", mana_cost="{1}", type_line="Artifact", oracle_text="Draw a card.")
    base = [(_plains(make_card), 40), (_bear(make_card), 49)]
    plain = simulate(base + [(rock, 10)], None, CFG)
    eq = simulate(base + [(bone, 10)], None, CFG)
    au = simulate(base + [(rancor, 10)], None, CFG)
    for runs in (eq, au):
        _sums(runs)
        assert _mean_kill(runs) < _mean_kill(plain)
    assert sum(r.damage_by_card.get("Bonesplitter", 0) for r in eq) > 0
    assert sum(r.damage_by_card.get("Rancor", 0) for r in au) > 0
    _sums(simulate(base + [(bone, 5), (rancor, 5)], None, CFG, board_wipe_turn=6))


def test_equipment_goes_on_the_commander(make_card):
    cmdr = make_card("Big Boss", mana_cost="{2}{W}", type_line="Legendary Creature — Giant")
    cmdr.power, cmdr.toughness = "4", "4"
    bone = make_card("Bonesplitter", mana_cost="{1}", type_line=EQ,
                     oracle_text="Equipped creature gets +2/+0.\nEquip {1}")
    runs = simulate([(_plains(make_card), 40), (_bear(make_card, power="1"), 54), (bone, 5)],
                    cmdr, CFG)
    _sums(runs)
    # the bonus rides on the commander, so it counts as commander combat damage
    assert any(r.commander_lethal_turn for r in runs)


def test_grafted_exoskeleton_makes_poison(make_card):
    exo = make_card("Grafted Exoskeleton", mana_cost="{4}", type_line=EQ,
                    oracle_text="Equipped creature gets +2/+2 and has infect.\nWhenever this "
                                "Equipment becomes unattached from a permanent, sacrifice that "
                                "permanent.\nEquip {2}")
    runs = simulate([(_plains(make_card), 40), (_bear(make_card), 50), (exo, 9)], None, CFG)
    _sums(runs)
    assert sum(r.poison_by_card.get("Grafted Exoskeleton", 0) for r in runs) > 0
