"""Denial roles (D2): lock pieces, theft, and the deck-level block. Gold set from real oracle
text; every near-miss is a card a looser pattern matched during the 2026-11-08 sweep."""
from __future__ import annotations

import pytest

from mythgauntlet.ratings import denial

LOCKS = [
    ("Stasis", "Enchantment", "Players skip their untap steps.\nAt the beginning of your upkeep, "
     "sacrifice this enchantment unless you pay {U}.", "untap"),
    ("Winter Orb", "Artifact", "As long as this artifact is untapped, players can't untap more "
     "than one land during their untap steps.", "untap"),
    ("Smoke", "Enchantment", "Players can't untap more than one creature during their untap "
     "steps.", "untap"),
    ("Arena of the Ancients", "Legendary Artifact", "Legendary creatures don't untap during their "
     "controllers' untap steps.\nWhen this artifact enters, tap all legendary creatures.", "untap"),
    ("Rule of Law", "Enchantment", "Each player can't cast more than one spell each turn.",
     "spell_limit"),
    ("Drannith Magistrate", "Creature — Human Wizard", "Your opponents can't cast spells from "
     "anywhere other than their hands.", "spell_limit"),
    ("Spirit of the Labyrinth", "Enchantment Creature — Spirit", "Each player can't draw more "
     "than one card each turn.", "draw_limit"),
    ("Moat", "Enchantment", "Creatures without flying can't attack.", "attack"),
    ("Ensnaring Bridge", "Artifact", "Creatures with power greater than the number of cards in "
     "your hand can't attack.", "attack"),
    ("Peacekeeper", "Creature — Human", "At the beginning of your upkeep, sacrifice this creature "
     "unless you pay {1}{W}.\nCreatures can't attack.", "attack"),
    ("Silent Arbiter", "Artifact Creature — Construct", "No more than one creature can attack "
     "each combat.\nNo more than one creature can block each combat.", "attack"),
    ("Solitary Confinement", "Enchantment", "At the beginning of your upkeep, sacrifice this "
     "enchantment unless you discard a card.\nSkip your draw step.\nYou have shroud. (You can't "
     "be the target of spells or abilities.)\nPrevent all damage that would be dealt to you.",
     "cant_lose"),
    ("Platinum Emperion", "Artifact Creature — Golem", "Your life total can't change. (You can't "
     "gain or lose life. You can't pay any amount of life except 0.)", "cant_lose"),
    ("Worship", "Enchantment", "If you control a creature, damage that would reduce your life "
     "total to less than 1 reduces it to 1 instead.", "cant_lose"),
    ("Cursed Totem", "Artifact", "Activated abilities of creatures can't be activated.", "ability"),
    ("Linvala, Keeper of Silence", "Legendary Creature — Angel", "Flying\nActivated abilities of "
     "creatures your opponents control can't be activated.", "ability"),
    ("The Tabernacle at Pendrell Vale", "Legendary Land", 'All creatures have "At the beginning '
     'of your upkeep, destroy this creature unless you pay {1}."', "untap"),
]

NOT_LOCKS = [
    ("Ghostly Prison", "Enchantment", "Creatures can't attack you unless their controller pays "
     "{2} for each creature they control that's attacking you."),           # a tax
    ("Propaganda", "Enchantment", "Creatures can't attack you unless their controller pays {2} "
     "for each creature they control that's attacking you."),
    ("Sandwurm Convergence", "Enchantment", "Creatures with flying can't attack you or "
     "planeswalkers you control.\nAt the beginning of your end step, create a 5/5 green Wurm "
     "creature token."),                                                     # a narrow subset
    ("Reverence", "Enchantment", "Creatures with power 2 or less can't attack you."),
    ("Magnetic Mountain", "Enchantment", "Blue creatures don't untap during their controllers' "
     "untap steps.\nAt the beginning of each player's upkeep, that player may choose any number "
     "of tapped blue creatures they control and pay {4} for each creature chosen this way. If "
     "the player does, untap those creatures."),                             # a colour hoser
    ("Dream Tides", "Enchantment", "Creatures don't untap during their controllers' untap steps."
     "\nAt the beginning of each player's upkeep, that player may choose any number of tapped "
     "nongreen creatures they control and pay {2} for each creature chosen this way. If the "
     "player does, untap those creatures."),                                 # pay to untap
    ("Shipbreaker Kraken", "Creature — Kraken", "{6}{U}{U}: Monstrosity 4.\nWhen this creature "
     "becomes monstrous, tap up to four target creatures. Those creatures don't untap during "
     "their controllers' untap steps for as long as you control this creature."),  # targets
    ("Intruder Alarm", "Enchantment", "Creatures don't untap during their controllers' untap "
     "steps.\nWhenever a creature enters, untap all creatures."),            # a combo piece
    ("Angel of Grace", "Creature — Angel", "Flash\nFlying\nWhen this creature enters, until end "
     "of turn, damage that would reduce your life total to less than 1 reduces it to 1 instead."),
    ("Fog", "Instant", "Prevent all combat damage that would be dealt this turn."),
    ("Holy Day", "Instant", "Prevent all combat damage that would be dealt this turn."),
    ("Pithing Needle", "Artifact", "As this artifact enters, choose a card name.\nActivated "
     "abilities of sources with the chosen name can't be activated unless they're mana abilities."),
    ("Grand Abolisher", "Creature — Human Cleric", "During your turn, your opponents can't cast "
     "spells or activate abilities of artifacts, creatures, or enchantments."),  # your turn only
    ("Serra the Benevolent", "Legendary Planeswalker — Serra", "+2: Creatures you control with "
     "flying get +1/+1 until end of turn.\n−3: Create a 4/4 white Angel creature token with "
     "flying and vigilance.\n−6: You get an emblem with \"If you control a creature, damage "
     "that would reduce your life total to less than 1 reduces it to 1 instead.\""),  # ultimate
]


@pytest.mark.parametrize("name,type_line,text,kind", LOCKS)
def test_locks(make_card, name, type_line, text, kind):
    lock = denial.lock_of(make_card(name, mana_cost="{2}", type_line=type_line, oracle_text=text))
    assert lock is not None and lock.kind == kind, name


@pytest.mark.parametrize("name,type_line,text", NOT_LOCKS)
def test_not_locks(make_card, name, type_line, text):
    assert denial.lock_of(make_card(name, mana_cost="{2}", type_line=type_line,
                                    oracle_text=text)) is None, name


@pytest.mark.parametrize("name,text,steals", [
    ("Control Magic", "Enchant creature\nYou control enchanted creature.", True),
    ("Treachery", "Enchant creature\nWhen this Aura enters, untap up to five lands.\nYou control "
     "enchanted creature.", True),
    ("Agent of Treachery", "When this creature enters, gain control of target permanent.\nAt the "
     "beginning of your end step, if you control three or more permanents you don't own, draw "
     "three cards.", True),
    ("Threaten", "Untap target creature and gain control of it until end of turn. That creature "
     "gains haste until end of turn.", False),                        # a turn's loan
    ("Brand", "Gain control of all permanents you own. (This effect lasts indefinitely.)", False),
])
def test_theft_is_a_lasting_change_of_control(make_card, name, text, steals):
    assert denial.steals(make_card(name, mana_cost="{2}", type_line="Enchantment",
                                   oracle_text=text)) is steals, name


def test_deck_denial_counts_every_role(make_card, forest):
    counter = make_card("Counterspell", mana_cost="{U}{U}", type_line="Instant",
                        oracle_text="Counter target spell.")
    rule = make_card("Rule of Law", mana_cost="{2}{W}", type_line="Enchantment",
                     oracle_text="Each player can't cast more than one spell each turn.")
    warp = make_card("Time Warp", mana_cost="{3}{U}{U}", type_line="Sorcery",
                     oracle_text="Target player takes an extra turn after this one.")
    moon = make_card("Blood Moon", mana_cost="{2}{R}", type_line="Enchantment",
                     oracle_text="Nonbasic lands are Mountains.")
    agent = make_card("Agent of Treachery", mana_cost="{5}{U}{U}", type_line="Creature — Human Rogue",
                      oracle_text="When this creature enters, gain control of target permanent.")
    d = denial.deck_denial([(forest, 30), (counter, 3), (rule, 1), (warp, 1), (moon, 1),
                            (agent, 1)], [])
    assert [lk.name for lk in d.locks] == ["Rule of Law"]
    assert (d.counterspells, d.theft, d.extra_turn_cards) == (3, 1, 1)
    assert d.mass_land_denial == ["Blood Moon"]
