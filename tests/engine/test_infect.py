"""Infect, toxic and poison in the goldfish sim (tier0): CR 702.90b (an infect source's damage
to a player is poison counters, not life), CR 702.180 (toxic adds poison on top), CR 704.5c
(ten poison loses). Gold set: the real cards' printed text."""
from __future__ import annotations

from mythgauntlet.ratings import kill_methods
from mythgauntlet.semantics import tags
from mythgauntlet.sim.tier0 import (SimConfig, _has_own_infect, _infect_aura, _toxic_amount,
                                    simulate)

CFG = SimConfig(turns=12, runs=150, seed=5)
REMINDER = ("(It deals damage to creatures in the form of -1/-1 counters and to players in the "
            "form of poison counters.)")
PHYRESIS = f"Enchant creature\nEnchanted creature has infect. {REMINDER}"
GLISTENING_OIL = ("Enchant creature\nEnchanted creature has infect.\nAt the beginning of your "
                  "upkeep, put a -1/-1 counter on enchanted creature.\nWhen this Aura is put into "
                  "a graveyard from the battlefield, return it to its owner's hand.")


def test_own_infect_is_a_printed_keyword_line_only():
    assert _has_own_infect("Infect (A creature with infect deals damage ...)")
    assert _has_own_infect("Flying, infect")
    assert _has_own_infect("Infect\n{B}: Regenerate this creature.")
    # mentions, not has: Vector Asp, Viridian Betrayers, Tainted Strike
    assert not _has_own_infect("{B}: This creature gains infect until end of turn.")
    assert not _has_own_infect("This creature has infect as long as an opponent is poisoned.")
    assert not _has_own_infect("Target creature gets +1/+0 and gains infect until end of turn.")


def test_toxic_amount():
    assert _toxic_amount("Toxic 2 (Players dealt combat damage by this creature also get two "
                         "poison counters.)") == 2
    assert _toxic_amount("Deathtouch, toxic 1") == 1
    assert _toxic_amount("Creatures you control with toxic lose toxic and gain infect.") == 0


def test_infect_auras_gold_set():
    aura = "Enchantment — Aura"
    assert _infect_aura(aura, PHYRESIS) is not None
    assert not _infect_aura(aura, PHYRESIS).upkeep_counter
    oil = _infect_aura(aura, GLISTENING_OIL)
    assert oil.upkeep_counter and oil.returns_to_hand
    # Corrupted Conscience enchants an opponent's creature: not one for the commander
    assert _infect_aura(aura, "Enchant creature\nYou control enchanted creature.\n"
                              f"Enchanted creature has infect. {REMINDER}") is None
    # Grafted Exoskeleton: equipment needs its equip cost -- not modeled
    assert _infect_aura("Artifact — Equipment", "Equipped creature gets +2/+2 and has infect.\n"
                                                "Equip {2}") is None


def _forest(make_card):
    return make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                     color_identity=("G",))


def _creature(make_card, name, text="", power="2", toughness="2"):
    c = make_card(name, mana_cost="{1}{G}", type_line="Creature — Phyrexian", colors=("G",),
                  color_identity=("G",), oracle_text=text)
    c.power, c.toughness = power, toughness
    return c


def _check_life_sums(runs):
    for r in runs:
        total = r.damage_by_turn[-1] if r.damage_by_turn else 0
        assert sum(r.damage_by_card.values()) == total
        assert sum(r.damage_by_source.values()) == total
        assert sum(r.poison_by_card.values()) == (r.poison_by_turn[-1] if r.poison_by_turn else 0)


def test_infect_creatures_kill_by_poison_and_faster(make_card):
    plain = simulate([(_forest(make_card), 40), (_creature(make_card, "Bear"), 59)], None, CFG)
    infect = simulate([(_forest(make_card), 40),
                       (_creature(make_card, "Blight Bear", "Infect"), 59)], None, CFG)
    _check_life_sums(infect)
    assert all(r.damage_by_turn[-1] == 0 for r in infect)          # no life damage at all
    killed = [r for r in infect if r.kill_turn is not None]
    assert killed and all(r.kill_method == "poison" for r in killed)
    med = lambda rs: sorted(r.kill_turn or 99 for r in rs)[len(rs) // 2]   # noqa: E731
    assert med(infect) < med(plain)
    km = kill_methods.compute(infect)
    assert km.method_share == {"poison": 1.0}
    assert km.top_damage_cards[0]["name"] == "Blight Bear"


def test_toxic_adds_poison_on_top_of_life_damage(make_card):
    runs = simulate([(_forest(make_card), 40),
                     (_creature(make_card, "Toxic Bear", "Toxic 1"), 59)], None, CFG)
    _check_life_sums(runs)
    assert all(r.damage_by_turn[-1] > 0 for r in runs)              # still deals life damage
    assert any(r.poison_by_turn[-1] > 0 for r in runs)


def _pinger_commander(make_card):
    cmdr = make_card("Night Pinger", mana_cost="{2}{G}", type_line="Legendary Creature — Elf",
                     colors=("G",), color_identity=("G",),
                     oracle_text="Whenever you cast an instant or sorcery spell, Night Pinger "
                                 "deals 2 damage to each opponent.")
    cmdr.power, cmdr.toughness = "2", "4"
    return cmdr


def _spell(make_card):
    return make_card("Study", mana_cost="{G}", type_line="Instant", colors=("G",),
                     color_identity=("G",), oracle_text="Draw a card.")


def _aura(make_card, name, text):
    return make_card(name, mana_cost="{1}{G}", type_line="Enchantment — Aura", colors=("G",),
                     color_identity=("G",), oracle_text=text)


def test_infect_aura_turns_the_commanders_cast_damage_into_poison(make_card):
    cmdr = _pinger_commander(make_card)
    assert tags.analyze(cmdr).cast_damage == 2
    base = [(_forest(make_card), 40), (_spell(make_card), 40)]
    without = simulate(base + [(_creature(make_card, "Filler"), 19)], cmdr, CFG)
    with_aura = simulate(base + [(_aura(make_card, "Phyresis", PHYRESIS), 19)], cmdr, CFG)
    _check_life_sums(with_aura)
    assert sum(r.poison_by_card.get("Night Pinger", 0) for r in with_aura) > 0
    assert not any(r.poison_by_turn and r.poison_by_turn[-1] for r in without)
    assert any(r.kill_method == "poison" for r in with_aura)
    mean = lambda rs: sum(r.kill_turn or 99 for r in rs) / len(rs)   # noqa: E731
    assert mean(with_aura) < mean(without)


def test_glistening_oil_shrinks_and_kills_the_commander(make_card):
    """A 2/4 under Glistening Oil dies on the fourth upkeep; the Oil comes back to hand. So
    it deals less poison than under Phyresis -- but still some, and still kills."""
    cmdr = _pinger_commander(make_card)
    base = [(_forest(make_card), 40), (_spell(make_card), 40)]
    phy = simulate(base + [(_aura(make_card, "Phyresis", PHYRESIS), 19)], cmdr, CFG)
    oil = simulate(base + [(_aura(make_card, "Glistening Oil", GLISTENING_OIL), 19)], cmdr, CFG)
    _check_life_sums(oil)
    total = lambda rs: sum(r.poison_by_turn[-1] for r in rs)   # noqa: E731
    assert 0 < total(oil) < total(phy)


def test_the_aura_falls_off_in_a_wipe(make_card):
    cmdr = _pinger_commander(make_card)
    deck = [(_forest(make_card), 40), (_spell(make_card), 40),
            (_aura(make_card, "Phyresis", PHYRESIS), 19)]
    wiped = simulate(deck, cmdr, CFG, board_wipe_turn=6)
    _check_life_sums(wiped)
    clean = simulate(deck, cmdr, CFG)
    assert sum(r.poison_by_turn[-1] for r in wiped) < sum(r.poison_by_turn[-1] for r in clean)


def test_cast_payoff_filters_gold_set():
    from mythgauntlet.sim.tier0 import _cast_filter
    # Guttersnipe: instants and sorceries (the default)
    assert _cast_filter("Whenever you cast an instant or sorcery spell, Guttersnipe deals 2 "
                        "damage to each opponent.") == (False, 0)
    # Firebrand Archer: every noncreature spell
    assert _cast_filter("Whenever you cast a noncreature spell, Firebrand Archer deals 1 damage "
                        "to each opponent.") == (True, 0)
    # Y'shtola, Night's Blessed: noncreature, mana value 3 or greater
    assert _cast_filter("Vigilance\nAt the beginning of each end step, if a player lost 4 or more "
                        "life this turn, you draw a card.\nWhenever you cast a noncreature spell "
                        "with mana value 3 or greater, Y'shtola deals 2 damage to each opponent "
                        "and you gain 2 life.") == (True, 3)


def test_a_noncreature_payoff_counts_artifacts_and_skips_cheap_spells(make_card):
    from mythgauntlet.sim.tier0 import _cast_filter, _counts_for, build_sim_cards
    flt = _cast_filter("Whenever you cast a noncreature spell with mana value 3 or greater, "
                       "X deals 2 damage to each opponent.")
    rock = make_card("Big Rock", mana_cost="{3}", type_line="Artifact")
    cheap = make_card("Shock", mana_cost="{R}", type_line="Instant")
    big = make_card("Big Spell", mana_cost="{2}{R}", type_line="Sorcery")
    beast = make_card("Beast", mana_cost="{3}{G}", type_line="Creature — Beast")
    r, c, b, k = (s for s in build_sim_cards([(x, 1) for x in (rock, cheap, big, beast)]))
    assert _counts_for(r, flt) and _counts_for(b, flt)
    assert not _counts_for(c, flt) and not _counts_for(k, flt)
    gutter = (False, 0)
    assert _counts_for(c, gutter) and _counts_for(b, gutter) and not _counts_for(r, gutter)
