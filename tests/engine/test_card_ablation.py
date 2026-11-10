"""Paired drawn-games ablation (ratings/card_ablation, 2026-11-10): what one card does for the
goldfish kill, in the games it is drawn, with every other card arriving on the same turn."""
from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.ratings import card_ablation as CA
from mythgauntlet.sim.tier0 import SimConfig

CFG = SimConfig(turns=12, runs=200, seed=3)


def _deck(make_card, extra, bears=50):
    forest = make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                       color_identity=("G",))
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature — Bear")
    bear.power, bear.toughness = "2", "2"
    filler = make_card("Filler", mana_cost="{G}", type_line="Enchantment")
    cards = [(c, n) for c, n in ((forest, 40), (bear, bears), (filler, 50 - bears)) if n]
    cards += [(c, 1) for c in extra]
    return ResolvedDeck(deck=Deck(commanders=[], entries=[]), commanders=[], cards=cards,
                        missing=[])


def test_blanking_keeps_the_slot(make_card):
    giant = make_card("Giant", mana_cost="{3}{G}", type_line="Creature — Giant")
    deck = _deck(make_card, [giant])
    blanked = CA._blanked(deck, "Giant")
    assert [c.name for c, _ in blanked.cards] == ["Forest", "Bear", CA.BLANK.name]
    assert sum(n for _, n in blanked.cards) == sum(n for _, n in deck.cards)


def test_a_real_threat_is_load_bearing_and_a_dud_is_not(make_card):
    giant = make_card("Giant", mana_cost="{3}{G}", type_line="Creature — Giant")
    giant.power, giant.toughness = "9", "9"
    dud = make_card("Dud", mana_cost="{3}{G}", type_line="Enchantment",
                    oracle_text="You may look at the top card of your library any time.")
    vals = CA.drawn_value(_deck(make_card, [giant, dud]), CFG, ["Giant", "Dud"])
    assert vals["Giant"].load_bearing and vals["Giant"].turns_sooner > 0
    assert vals["Giant"].games > 0
    assert not vals["Dud"].load_bearing
    assert abs(vals["Dud"].turns_sooner) < 0.2
    # never-drawn games carry no information and are excluded, not averaged in as zeros
    assert vals["Giant"].games < CFG.runs


def test_a_late_finisher_is_measured_too(make_card):
    """The early-window metric cannot see a card that only acts late; this one can -- in a
    slow deck. (In a deck that kills by turn 8 anyway an 8-drop is honestly worth ~0.)"""
    titan = make_card("Titan", mana_cost="{6}{G}{G}", type_line="Creature — Giant")
    titan.power, titan.toughness = "12", "12"
    vals = CA.drawn_value(_deck(make_card, [titan], bears=6), CFG, ["Titan"])
    assert vals["Titan"].load_bearing
