"""Static anthems in the tier0 goldfish clock (docs/BACKLOG.md B3, phase 2b)."""
from __future__ import annotations

from mythgauntlet.sim.tier0 import SimConfig, _anthems_in_text, simulate

CFG = SimConfig(runs=60, seed=5, turns=8)


def _cards(make_card, anthem_text=None, anthem_type="Enchantment", copies=2):
    forest = make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                       color_identity=("G",))
    bear = make_card("Bear", mana_cost="{1}", type_line="Creature — Bear", colors=("G",),
                     color_identity=("G",))
    bear.power, bear.toughness = "2", "2"
    deck = [(forest, 40), (bear, 59 if anthem_text is None else 59 - copies)]
    if anthem_text is not None:
        a = make_card("Test Anthem", mana_cost="{1}", type_line=anthem_type, colors=("G",),
                      color_identity=("G",), oracle_text=anthem_text)
        if "Creature" in anthem_type:
            a.power, a.toughness = "1", "1"
        deck.append((a, copies))
    return deck


def _mean_final_power(runs):
    return sum(r.final_board_power for r in runs) / len(runs)


def test_text_parser_reads_only_flat_unconditional_power_anthems():
    assert _anthems_in_text("Creatures you control get +1/+1.") == ((1, False),)
    assert _anthems_in_text("Other creatures you control get +2/+0") == ((2, True),)
    assert _anthems_in_text("Flash\nCreatures you control get +1/+1.\nDraw a card.") == ((1, False),)
    # all declined: not a power bonus to MY creatures, or not unconditional, or not a whole line
    assert _anthems_in_text("Creatures you control have haste.") == ()
    assert _anthems_in_text("Creatures your opponents control get -1/-1.") == ()
    assert _anthems_in_text("Nontoken creatures you control get +1/+1.") == ()
    assert _anthems_in_text("Creatures you control get +1/+1 until end of turn.") == ()
    assert _anthems_in_text("- Temur: Creatures you control get +1/+0 and have haste.") == ()
    assert _anthems_in_text("Creatures you control get +1/+1 as long as you control a Forest.") == ()
    assert _anthems_in_text("") == ()


def test_reminder_text_is_ignored(make_card):
    assert _anthems_in_text("Creatures you control get +1/+1. (They are bigger.)") == ((1, False),)


def test_an_anthem_raises_the_goldfish_clock(make_card):
    plain = simulate(_cards(make_card), None, CFG)
    boosted = simulate(_cards(make_card, "Creatures you control get +1/+1."), None, CFG)
    assert _mean_final_power(boosted) > _mean_final_power(plain)


def test_a_lord_does_not_buff_itself(make_card):
    only_self = simulate(_cards(make_card, "Other creatures you control get +1/+1.",
                                anthem_type="Creature — Elf", copies=1), None, CFG)
    buffs_self = simulate(_cards(make_card, "Creatures you control get +1/+1.",
                                 anthem_type="Creature — Elf", copies=1), None, CFG)
    assert _mean_final_power(buffs_self) > _mean_final_power(only_self)


def test_an_instant_or_sorcery_never_provides_a_static_anthem(make_card):
    runs = simulate(_cards(make_card, "Creatures you control get +1/+1.", anthem_type="Sorcery"),
                    None, CFG)
    plain = simulate(_cards(make_card), None, CFG)
    # the sorcery occupies slots a bear would have; it must add no anthem power on top
    assert _mean_final_power(runs) <= _mean_final_power(plain)


def test_a_noncreature_anthem_survives_a_wipe_and_keeps_buffing(make_card):
    boosted = simulate(_cards(make_card, "Creatures you control get +1/+1."), None, CFG,
                       board_wipe_turn=5)
    plain = simulate(_cards(make_card), None, CFG, board_wipe_turn=5)
    # the wipe clears every creature in both, but the enchantment stays and buffs what is rebuilt
    assert _mean_final_power(boosted) > _mean_final_power(plain)


def test_a_creature_sourced_anthem_does_not_outlive_the_wipe(make_card):
    wiped_creature = simulate(_cards(make_card, "Creatures you control get +1/+1.",
                                     anthem_type="Creature — Elf"), None, CFG, board_wipe_turn=5)
    wiped_enchant = simulate(_cards(make_card, "Creatures you control get +1/+1."), None, CFG,
                             board_wipe_turn=5)
    # same anthem text, same copies: only the creature one is destroyed by the wipe
    assert _mean_final_power(wiped_creature) < _mean_final_power(wiped_enchant)
