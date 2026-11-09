"""Creature tokens in the goldfish sim (tier0). Gold set: the real cards' printed text; anything
that cannot be read exactly (a variable count, a copy, a death trigger, a cost) makes nothing."""
from __future__ import annotations

from mythgauntlet.sim.tier0 import SimConfig, _token_makers, simulate

CFG = SimConfig(turns=12, runs=150, seed=5)


def tm(name, type_line, text):
    return _token_makers(name, type_line, text)


def test_token_makers_gold_set():
    (alarm,) = tm("Raise the Alarm", "Instant", "Create two 1/1 white Soldier creature tokens.")
    assert (alarm.trigger, alarm.count, alarm.power) == ("now", 2, 1)
    (hero,) = tm("Hero of Bladehold", "Creature — Human Knight",
                 "Battle cry\nWhenever this creature attacks, create two 1/1 white Soldier "
                 "creature tokens that are tapped and attacking.")
    assert hero.trigger == "attack" and hero.attacking and hero.count == 2
    (pyro,) = tm("Young Pyromancer", "Creature — Human Shaman",
                 "Whenever you cast an instant or sorcery spell, create a 1/1 red Elemental "
                 "creature token.")
    assert pyro.trigger == "cast" and pyro.cast_kind == "instant_sorcery"
    (rabble,) = tm("Goblin Rabblemaster", "Creature — Goblin Warrior",
                   "Other Goblin creatures you control attack each combat if able.\nAt the "
                   "beginning of combat on your turn, create a 1/1 red Goblin creature token "
                   "with haste.")
    assert rabble.trigger == "upkeep" and rabble.haste
    (bb,) = tm("Bitterblossom", "Kindred Enchantment — Faerie",
               "At the beginning of your upkeep, you lose 1 life and create a 1/1 black Faerie "
               "Rogue creature token with flying.")
    assert bb.trigger == "upkeep"
    (elspeth,) = tm("Elspeth, Sun's Champion", "Legendary Planeswalker — Elspeth",
                    "+1: Create three 1/1 white Soldier creature tokens.\n−3: Destroy all "
                    "creatures with power 4 or greater.\n−7: You get an emblem.")
    assert elspeth.trigger == "pw" and elspeth.count == 3


def test_token_makers_it_cannot_read_make_nothing():
    # variable count, X, copy, death trigger, activated ability, opponent's tokens, a mode
    assert tm("Avenger of Zendikar", "Creature — Elemental",
              "When this creature enters, create a 0/1 green Plant creature token for each land "
              "you control.") == ()
    assert tm("Secure the Wastes", "Instant", "Create X 1/1 white Warrior creature tokens.") == ()
    assert tm("Mirror", "Sorcery", "Create a token that's a copy of target creature you control.") == ()
    assert tm("Doomed", "Creature — Zombie",
              "When this creature dies, create a 2/2 black Zombie creature token.") == ()
    assert tm("Krenko, Mob Boss", "Legendary Creature — Goblin Warrior",
              "{T}: Create X 1/1 red Goblin creature tokens, where X is the number of Goblins "
              "you control.") == ()
    assert tm("Beast Within", "Instant", "Destroy target permanent. Its controller creates a 3/3 "
                                         "green Beast creature token.") == ()
    assert tm("Charm", "Instant", "Choose one —\n• Create a 1/1 white Soldier creature token.\n"
                                  "• Draw a card.") == ()


def _forest(make_card):
    return make_card("Forest", type_line="Basic Land — Forest", produced_mana=("W",),
                     color_identity=("W",))


def _sums(runs):
    for r in runs:
        total = r.damage_by_turn[-1] if r.damage_by_turn else 0
        assert sum(r.damage_by_card.values()) == total
        assert sum(r.damage_by_source.values()) == total


def _mean_kill(runs):
    return sum(r.kill_turn or 99 for r in runs) / len(runs)


def test_token_spells_add_attackers(make_card):
    alarm = make_card("Raise the Alarm", mana_cost="{1}{W}", type_line="Instant",
                      oracle_text="Create two 1/1 white Soldier creature tokens.")
    dud = make_card("Dud", mana_cost="{1}{W}", type_line="Instant", oracle_text="You gain 1 life.")
    with_t = simulate([(_forest(make_card), 40), (alarm, 59)], None, CFG)
    without = simulate([(_forest(make_card), 40), (dud, 59)], None, CFG)
    _sums(with_t)
    assert sum(r.damage_by_card.get("Raise the Alarm token", 0) for r in with_t) > 0
    assert _mean_kill(with_t) < _mean_kill(without)


def test_upkeep_makers_and_wipes(make_card):
    bb = make_card("Bitterblossom", mana_cost="{1}{W}", type_line="Kindred Enchantment — Faerie",
                   oracle_text="At the beginning of your upkeep, you lose 1 life and create a 1/1 "
                               "black Faerie Rogue creature token with flying.")
    runs = simulate([(_forest(make_card), 40), (bb, 59)], None, CFG)
    _sums(runs)
    assert any(r.kill_turn for r in runs)
    # the enchantment survives a creature wipe and keeps making tokens; its tokens die
    _sums(simulate([(_forest(make_card), 40), (bb, 59)], None, CFG, board_wipe_turn=6))


def test_attack_makers_attack_at_once(make_card):
    hero = make_card("Hero of Bladehold", mana_cost="{2}{W}", type_line="Creature — Human Knight",
                     oracle_text="Whenever this creature attacks, create two 1/1 white Soldier "
                                 "creature tokens that are tapped and attacking.")
    hero.power, hero.toughness = "3", "4"
    runs = simulate([(_forest(make_card), 40), (hero, 59)], None, CFG)
    _sums(runs)
    assert sum(r.damage_by_card.get("Hero of Bladehold token", 0) for r in runs) > 0


def test_cast_makers_count_only_their_spells(make_card):
    pyro = make_card("Young Pyromancer", mana_cost="{1}{W}", type_line="Creature — Human Shaman",
                     oracle_text="Whenever you cast an instant or sorcery spell, create a 1/1 red "
                                 "Elemental creature token.")
    pyro.power, pyro.toughness = "2", "1"
    bear = make_card("Bear", mana_cost="{1}{W}", type_line="Creature — Bear")
    bear.power, bear.toughness = "2", "2"
    runs = simulate([(_forest(make_card), 40), (pyro, 4), (bear, 55)], None, CFG)
    assert all(r.damage_by_card.get("Young Pyromancer token", 0) == 0 for r in runs)
