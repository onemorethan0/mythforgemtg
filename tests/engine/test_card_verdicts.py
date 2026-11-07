"""Strong and weak cards (B31, ratings/card_verdicts.py) and the planeswalker-ultimate fix found
while building it (semantics/tags.py `_reachable_text`)."""
from __future__ import annotations

from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.ratings import card_verdicts as cv
from mythgauntlet.ratings.card_stats import CardStat
from mythgauntlet.semantics import tags


def _stat(name, up=None, ci=None, stranded=0.0, colour=0.0, cost=0.0, land=False, drawn=800):
    return CardStat(name=name, is_land=land, drawn=drawn, cast_rate=1 - stranded,
                    avg_cast_turn=5.0, stranded_rate=stranded, stranded_colour_share=colour,
                    stranded_cost_share=cost, early_uplift=up, uplift_ci=ci,
                    n_early=200 if up is not None else 0, n_late=1800)


def _deck(make_card, *cards):
    return ResolvedDeck(deck=Deck(), commanders=[make_card(
        "Cmdr", type_line="Legendary Creature — Elf", mana_cost="{G}")],
        cards=[(c, 1) for c in cards], missing=[])


def test_a_significant_fast_card_is_strong_and_never_also_weak(make_card):
    rock = make_card("Rock", mana_cost="{1}", type_line="Artifact",
                     oracle_text="{T}: Add {C}{C}.", produced_mana=("C",))
    out = cv.build(_deck(make_card, rock),
                   [_stat("Rock", up=0.8, ci=(0.6, 1.0), stranded=0.4, cost=0.9)])
    assert [v.kind for v in out["strong"]] == ["speeds_kill"]
    assert out["weak"] == []


def test_insignificant_or_small_effects_are_not_named(make_card):
    a = make_card("A", mana_cost="{1}", type_line="Artifact", oracle_text="{T}: Add {C}.")
    b = make_card("B", mana_cost="{1}", type_line="Artifact", oracle_text="{T}: Add {C}.")
    out = cv.build(_deck(make_card, a, b), [_stat("A", up=0.9, ci=(-0.1, 1.9)),
                                            _stat("B", up=0.2, ci=(0.1, 0.3))])
    assert out["strong"] == []


def test_stranded_reason_is_the_recorded_one(make_card):
    wrath = make_card("Big Pips", mana_cost="{W}{W}{W}", type_line="Creature — Golem")
    wrath.power, wrath.toughness = "5", "5"
    huge = make_card("Huge", mana_cost="{9}", type_line="Creature — Golem")
    huge.power, huge.toughness = "9", "9"
    out = cv.build(_deck(make_card, wrath, huge),
                   [_stat("Big Pips", stranded=0.6, colour=0.8),
                    _stat("Huge", stranded=0.5, cost=0.9)])
    reasons = {v.name: v.evidence["reason"] for v in out["weak"]}
    assert reasons == {"Big Pips": "colour", "Huge": "cost"}


def test_an_outranked_wipe_is_not_called_weak(make_card):
    """No opponent, nothing to wipe: the goldfish never prioritises it. A blind spot."""
    wipe = make_card("Wrath", mana_cost="{2}{W}{W}", type_line="Sorcery",
                     oracle_text="Destroy all creatures. They can't be regenerated.")
    out = cv.build(_deck(make_card, wipe), [_stat("Wrath", stranded=0.7)])
    assert out["weak"] == []


def test_slows_kill_only_for_legible_clock_cards(make_card):
    boots = make_card("Boots", mana_cost="{2}", type_line="Artifact — Equipment",
                      oracle_text="Equipped creature has hexproof and haste.\nEquip {1}")
    arena = make_card("Arena", mana_cost="{1}{B}{B}", type_line="Enchantment",
                      oracle_text="At the beginning of your upkeep, you draw a card and "
                                  "you lose 1 life.")
    cultivate = make_card("Cultivate", mana_cost="{2}{G}", type_line="Sorcery",
                          oracle_text="Search your library for up to two basic land cards, "
                                      "reveal those cards, put one onto the battlefield tapped "
                                      "and the other into your hand, then shuffle.")
    stats = [_stat(n, up=-0.5, ci=(-0.7, -0.3)) for n in ("Boots", "Arena", "Cultivate")]
    out = cv.build(_deck(make_card, boots, arena, cultivate), stats)
    assert [v.name for v in out["weak"] if v.kind == "slows_kill"] == ["Cultivate"]


def test_legibility(make_card):
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature — Bear")
    flyer = make_card("Flyer", mana_cost="{3}", type_line="Creature — Bird",
                      oracle_text="Flying, vigilance", keywords=frozenset({"Flying", "Vigilance"}))
    doubler = make_card("Doubler", mana_cost="{3}{G}{G}", type_line="Enchantment",
                        oracle_text="If an effect would create one or more tokens, it creates "
                                    "twice that many instead.")
    assert cv.goldfish_legible(bear) and cv.goldfish_legible(flyer)
    assert not cv.goldfish_legible(doubler)


def test_commanders_are_never_named(make_card):
    out = cv.build(_deck(make_card), [_stat("Cmdr", up=1.0, ci=(0.8, 1.2))])
    assert out["strong"] == [] and out["weak"] == []


# ── planeswalker ultimates are unreachable on entry (CR 606.6) ─────────────────────────

def test_an_ultimate_above_starting_loyalty_is_not_tagged(make_card):
    ugin = make_card("Ugin Test", mana_cost="{8}", type_line="Legendary Planeswalker — Ugin",
                     oracle_text="+2: Ugin deals 3 damage to any target.\n"
                                 "−X: Exile each permanent with mana value X or less "
                                 "that's one or more colors.\n"
                                 "−10: You gain 7 life, draw seven cards, then put up to "
                                 "seven permanent cards from your hand onto the battlefield.")
    ugin.loyalty = "7"
    fx = tags.analyze(ugin)
    assert fx.draw_cards == 0 and not fx.cheats_creatures
    assert fx.removal >= 1                       # +2 and -X stay: those get used


def test_a_reachable_minus_ability_still_counts(make_card):
    ral = make_card("Ral Test", mana_cost="{2}{U}{R}", type_line="Legendary Planeswalker — Ral",
                    oracle_text="−3: Draw three cards.\n−10: Draw ten cards.")
    ral.loyalty = "4"
    assert tags.analyze(ral).draw_cards == 3


def test_non_planeswalkers_are_untouched(make_card):
    odd = make_card("Odd", mana_cost="{1}", type_line="Artifact",
                    oracle_text="−9: Draw nine cards.")
    assert tags._reachable_text(odd) == odd.oracle_text
    walker = make_card("Walker", mana_cost="{3}", type_line="Legendary Planeswalker — X",
                       oracle_text="+1: Draw a card.\n−9: Draw nine cards.")
    walker.loyalty = "X"                         # unknown starting loyalty: nothing dropped
    assert tags._reachable_text(walker) == walker.oracle_text
