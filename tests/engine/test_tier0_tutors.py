"""Tutors in the goldfish sim (tier0): what a tutor may fetch and where it goes, read strictly
from its own text (gold set = the real cards' printed text); anything not read fetches nothing.
The pick is the deck's missing plan piece (an infect Aura for its commander) first, else the
highest-impact card the tutor may take."""
from __future__ import annotations

from mythgauntlet.sim.tier0 import SimConfig, _tutor_spec, simulate

SORC, INST = "Sorcery", "Instant"
CFG = SimConfig(turns=12, runs=150, seed=5)


def spec(type_line, text):
    return _tutor_spec(type_line, text)


def test_tutor_gold_set_reads_filter_and_destination():
    demonic = spec(SORC, "Search your library for a card, put that card into your hand, then "
                         "shuffle.")
    assert demonic.types == () and demonic.dest == "hand"
    diabolic = spec(SORC, "Search your library for a card and put that card into your hand. "
                          "Then shuffle.")
    assert diabolic.dest == "hand"
    vampiric = spec(INST, "Search your library for a card, then shuffle and put that card on "
                          "top. You lose 2 life.")
    assert vampiric.dest == "top"
    enlightened = spec(INST, "Search your library for an artifact or enchantment card, reveal "
                             "it, then shuffle and put that card on top.")
    assert enlightened.types == ("artifact", "enchantment") and enlightened.dest == "top"
    idyllic = spec(SORC, "Search your library for an enchantment card, reveal it, put it into "
                         "your hand, then shuffle.")
    assert idyllic.types == ("enchantment",)
    spellseeker = spec("Creature — Human Wizard",
                       "When this creature enters, you may search your library for an instant "
                       "or sorcery card with mana value 2 or less, reveal it, put it into your "
                       "hand, then shuffle.")
    assert spellseeker.types == ("instant", "sorcery") and spellseeker.max_mv == 2
    trophy = spec("Creature — Human Wizard",
                  "When this creature enters, you may search your library for an artifact card "
                  "with mana value 3, reveal it, put it into your hand, then shuffle.")
    assert (trophy.min_mv, trophy.max_mv) == (3, 3)


def test_tutors_it_cannot_read_exactly_fetch_nothing():
    # additional cost (Diabolic Intent), random discard (Gamble), two cards (Final Parting)
    assert spec(SORC, "As an additional cost to cast this spell, sacrifice a creature.\nSearch "
                      "your library for a card, put that card into your hand, then shuffle.") is None
    assert spec(SORC, "Search your library for a card, put that card into your hand, discard a "
                      "card at random, then shuffle.") is None
    assert spec(SORC, "Search your library for two cards. Put one into your hand and the other "
                      "into your graveyard. Then shuffle.") is None
    # an activated ability (Planar Bridge), a dies trigger (Academy Rector)
    assert spec("Artifact", "{8}, {T}: Search your library for a permanent card, put it onto "
                            "the battlefield, then shuffle.") is None
    assert spec("Creature — Human Wizard",
                "When this creature dies, you may exile it. If you do, search your library for "
                "an enchantment card, put that card onto the battlefield, then shuffle.") is None
    # a colour / subtype / name / to graveyard
    assert spec(SORC, "Search your library for a legendary creature card, reveal it, put it "
                      "into your hand, then shuffle.") is None
    assert spec(SORC, "Search your library for a nonlegendary card, put that card into your "
                      "graveyard, then shuffle.") is None
    # transmute: the search lives in reminder text
    assert spec(INST, "Counter target spell.\nTransmute {1}{U}{U} ({1}{U}{U}, Discard this card: "
                      "Search your library for a card with the same mana value as this card, "
                      "reveal it, put it into your hand, then shuffle.)") is None


def _forest(make_card):
    return make_card("Forest", type_line="Basic Land — Forest", produced_mana=("G",),
                     color_identity=("G",))


def test_a_tutor_fetches_the_infect_aura_for_its_commander(make_card):
    cmdr = make_card("Night Pinger", mana_cost="{2}{G}", type_line="Legendary Creature — Elf",
                     colors=("G",), color_identity=("G",),
                     oracle_text="Whenever you cast an instant or sorcery spell, Night Pinger "
                                 "deals 2 damage to each opponent.")
    cmdr.power, cmdr.toughness = "2", "4"
    spell = make_card("Study", mana_cost="{G}", type_line=INST, colors=("G",),
                      color_identity=("G",), oracle_text="Draw a card.")
    aura = make_card("Phyresis", mana_cost="{1}{G}", type_line="Enchantment — Aura",
                     colors=("G",), color_identity=("G",),
                     oracle_text="Enchant creature\nEnchanted creature has infect.")
    tutor = make_card("Grove Tutor", mana_cost="{1}{G}", type_line=SORC, colors=("G",),
                      color_identity=("G",),
                      oracle_text="Search your library for a card, put that card into your "
                                  "hand, then shuffle.")
    dud = make_card("Grove Dud", mana_cost="{1}{G}", type_line=SORC, colors=("G",),
                    color_identity=("G",), oracle_text="You gain 1 life.")
    base = [(_forest(make_card), 40), (spell, 45),
            (aura, 1)]
    with_tutors = simulate(base + [(tutor, 13)], cmdr, CFG)
    with_duds = simulate(base + [(dud, 13)], cmdr, CFG)
    found = lambda rs: sum(r.played_turn.get("Phyresis") is not None for r in rs)   # noqa: E731
    assert found(with_tutors) > found(with_duds) + 30
    poison = lambda rs: sum(r.poison_by_turn[-1] for r in rs)   # noqa: E731
    assert poison(with_tutors) > poison(with_duds)


def test_a_top_tutor_puts_the_card_on_top(make_card):
    """Enlightened-Tutor class: the fetched card is the NEXT draw, not a card in hand now."""
    rock = make_card("Big Rock", mana_cost="{3}", type_line="Artifact",
                     oracle_text="{T}: Add {C}{C}.", produced_mana=("C",))
    top = make_card("Top Tutor", mana_cost="{G}", type_line=INST, colors=("G",),
                    color_identity=("G",),
                    oracle_text="Search your library for an artifact card, reveal it, then "
                                "shuffle and put that card on top.")
    runs = simulate([(_forest(make_card), 40), (top, 58), (rock, 1)], None, CFG)
    # fetched to the top, so it is seen at a later turn than the tutor was played
    later = [r for r in runs if "Big Rock" in r.seen_turn and "Top Tutor" in r.played_turn
             and r.played_turn["Top Tutor"] < r.seen_turn["Big Rock"]]
    assert later
    assert all(r.seen_turn["Big Rock"] >= r.played_turn["Top Tutor"] for r in later)
