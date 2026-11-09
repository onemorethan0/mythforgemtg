"""Proliferate, fixed drains, direct poison and Treasure in the goldfish sim (tier0), timed like
the token makers. Gold set: the real cards' printed text."""
from __future__ import annotations

from mythgauntlet.sim.tier0 import SimConfig, _effect_makers, _token_makers, simulate

CFG = SimConfig(turns=12, runs=150, seed=5)


def em(name, type_line, text):
    return [(e.kind, e.trigger, e.amount, e.cast_kind) for e in _effect_makers(name, type_line, text)]


def test_effect_gold_set():
    assert em("Atraxa, Praetors' Voice", "Legendary Creature — Phyrexian Angel Horror",
              "Flying, vigilance, deathtouch, lifelink\nAt the beginning of your end step, "
              "proliferate.") == [("proliferate", "end", 1, "any")]
    assert em("Flux Channeler", "Creature — Human Wizard",
              "Whenever you cast a noncreature spell, proliferate.") == [
        ("proliferate", "cast", 1, "noncreature")]
    assert em("Tezzeret's Gambit", "Sorcery", "Draw two cards, then proliferate.") == [
        ("proliferate", "now", 1, "any")]
    assert em("Lava Spike", "Sorcery — Arcane", "Lava Spike deals 3 damage to target player or "
                                                "planeswalker.") == [("drain", "now", 3, "any")]
    assert em("Vraska's Fall", "Instant", "Each opponent sacrifices a creature or planeswalker "
                                          "and gets a poison counter.") == [("poison", "now", 1, "any")]
    assert em("Professional Face-Breaker", "Creature — Human Warrior",
              "Menace\nWhenever one or more creatures you control deal combat damage to a "
              "player, create a Treasure token.\nSacrifice a Treasure: Exile the top card of "
              "your library. You may play that card this turn.") == [
        ("treasure", "attack_any", 1, "any")]


def test_effects_it_cannot_read_make_nothing():
    # removal pointed at a creature, a self-targeted drain, a variable drain, a death trigger
    assert em("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.") == []
    assert em("Sign in Blood", "Sorcery", "Target player draws two cards and loses 2 life.") == []
    assert em("Gray Merchant of Asphodel", "Creature — Zombie",
              "When this creature enters, each opponent loses X life, where X is your devotion "
              "to black. You gain life equal to the life lost this way.") == []
    assert em("Zulaport Cutthroat", "Creature — Human Rogue Ally",
              "Whenever this creature or another creature you control dies, each opponent "
              "loses 1 life and you gain 1 life.") == []
    # a cast trigger that deals DAMAGE is tags' cast_damage -- never counted twice
    assert em("Guttersnipe", "Creature — Goblin Shaman",
              "Whenever you cast an instant or sorcery spell, Guttersnipe deals 2 damage to "
              "each opponent.") == []
    # an activated proliferate
    assert em("Contagion Engine", "Artifact",
              "{4}, {T}: Proliferate, then proliferate again.") == []


def test_infect_tokens_are_read():
    (germ,) = _token_makers("Plague Maker", "Sorcery",
                            "Create two 1/1 black Phyrexian Germ creature tokens with infect.")
    assert germ.infect and germ.count == 2


def _swamp(make_card):
    return make_card("Swamp", type_line="Basic Land — Swamp", produced_mana=("B",),
                     color_identity=("B",))


def _sums(runs):
    for r in runs:
        total = r.damage_by_turn[-1] if r.damage_by_turn else 0
        assert sum(r.damage_by_card.values()) == total
        assert sum(r.damage_by_source.values()) == total
        assert sum(r.poison_by_card.values()) == (r.poison_by_turn[-1] if r.poison_by_turn else 0)


def test_drain_and_proliferate_in_play(make_card):
    spike = make_card("Spike", mana_cost="{B}", type_line="Sorcery",
                      oracle_text="Spike deals 3 damage to target player or planeswalker.")
    runs = simulate([(_swamp(make_card), 40), (spike, 59)], None, CFG)
    _sums(runs)
    assert all(r.damage_by_card.get("Spike", 0) > 0 for r in runs)

    blighter = make_card("Blighter", mana_cost="{1}{B}", type_line="Creature — Phyrexian",
                         oracle_text="Infect")
    blighter.power, blighter.toughness = "1", "1"
    atraxa_like = make_card("Proliferator", mana_cost="{2}{B}", type_line="Creature — Horror",
                            oracle_text="At the beginning of your end step, proliferate.")
    atraxa_like.power, atraxa_like.toughness = "0", "3"
    runs = simulate([(_swamp(make_card), 40), (blighter, 40), (atraxa_like, 19)], None, CFG)
    _sums(runs)
    assert sum(r.poison_by_card.get("Proliferator", 0) for r in runs) > 0


def test_treasure_is_mana_once(make_card):
    inn = make_card("Innkeeper", mana_cost="{B}", type_line="Creature — Human",
                    oracle_text="When this creature enters, create a Treasure token.")
    inn.power, inn.toughness = "1", "1"
    big = make_card("Big Thing", mana_cost="{5}{B}", type_line="Creature — Beast")
    big.power, big.toughness = "8", "8"
    with_t = simulate([(_swamp(make_card), 35), (inn, 30), (big, 34)], None, CFG)
    _sums(with_t)
    vanilla = make_card("Innkeeper", mana_cost="{B}", type_line="Creature — Human")
    vanilla.power, vanilla.toughness = "1", "1"
    without = simulate([(_swamp(make_card), 35), (vanilla, 30), (big, 34)], None, CFG)
    first = lambda rs: sum(min((t for n, t in r.played_turn.items() if n == "Big Thing"),  # noqa: E731
                               default=99) for r in rs)
    assert first(with_t) < first(without)
