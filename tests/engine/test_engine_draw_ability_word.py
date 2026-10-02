"""A trigger behind an ability word is still a trigger.

`tags._draw_counts` recognised a trigger only at the START of its sentence (`_TRIGGER_RE`), so
an ability word or flavor word in front of it hid it: "Landfall — Whenever a land you control
enters, you gain 1 life and draw a card." was not a trigger at all. ~80 cards in the store:

* a recurring trigger read as an IMMEDIATE draw — Tatyova, Benthic Druid, Muse Seeker,
  Hollowmurk Siege were one card of advantage instead of an engine;
* a one-shot one was SUMMED with the card's other one-shot draws instead of max'd;
* a draw in the trigger CONDITION was counted as a draw — Starving Revenant's "Descend 8 —
  Whenever you draw a card, ..." and Aether Syphon's "Max speed — Whenever you draw a card,
  each opponent mills two cards" each scored a draw they don't have.

The prefix is now stripped when a trigger follows it: ability/flavor words, "Descend 8", a
Siege's "• Khans — " bullet, Unfinity sticker costs ("{TK}{TK}{TK}{TK} — ", chained before an
ability word on Snazzy Aether Homunculus). A Saga's chapter numeral is NOT stripped — "III —
Whenever you cast ... this turn" fires once, and its trigger lasts that turn only.

Oracle text below is verbatim from the Scryfall store; `test_oracle_text_matches_the_store`
re-checks that whenever the live store is present (CI has none and skips it).
"""

from __future__ import annotations

import pytest

from mythgauntlet.ratings.swap_brief import card_functions
from mythgauntlet.semantics import tags

ORACLE = {
    # ── recurring trigger behind an ability word: engines ───────────────────────
    "Tatyova, Benthic Druid": (
        "Legendary Creature — Merfolk Druid",
        "Landfall — Whenever a land you control enters, you gain 1 life and draw a card."),
    "Muse Seeker": (
        "Creature — Elf Wizard",
        "Opus — Whenever you cast an instant or sorcery spell, draw a card. Then discard a "
        "card unless five or more mana was spent to cast that spell."),
    # the follow-on sentence belongs to the prefixed trigger too
    "Rydia, Summoner of Mist": (
        "Legendary Creature — Human Shaman",
        "Landfall — Whenever a land you control enters, you may discard a card. If you do, "
        "draw a card.\n"
        "Summon — {X}, {T}: Return target Saga card with mana value X from your graveyard to "
        "the battlefield with a finality counter on it. It gains haste until end of turn. "
        "Activate only as a sorcery."),
    # "instead" follow-on: the max, at the engine cap
    "Tallyman of Nurgle": (
        "Creature — Astartes Warrior",
        "Lifelink\n"
        "The Seven-fold Chant — At the beginning of your end step, if a creature died this "
        "turn, you draw a card and you lose 1 life. If seven or more creatures died this turn, "
        "instead you draw seven cards and you lose 7 life."),
    # a Siege's mode bullet
    "Hollowmurk Siege": (
        "Enchantment",
        "As this enchantment enters, choose Sultai or Abzan.\n"
        "• Sultai — Whenever a counter is put on a creature you control, draw a card. This "
        "ability triggers only once each turn.\n"
        "• Abzan — Whenever you attack, put a +1/+1 counter on target attacking creature. It "
        "gains menace until end of turn."),
    "Monastery Siege": (
        "Enchantment",
        "As this enchantment enters, choose Khans or Dragons.\n"
        "• Khans — At the beginning of your draw step, draw an additional card, then discard "
        "a card.\n"
        "• Dragons — Spells your opponents cast that target you or a permanent you control "
        "cost {2} more to cast."),
    # an Unfinity sticker cost, alone and chained before an ability word
    "Playable Delusionary Hydra": (
        "Stickers",
        "{TK}{TK} — {T}: Draw a card, then discard a card.\n"
        "{TK}{TK}{TK}{TK} — Whenever this creature attacks, you gain 3 life and draw a card.\n"
        "{TK}{TK} — 1/5\n{TK}{TK}{TK} — 4/4"),
    "Snazzy Aether Homunculus": (
        "Stickers",
        "{TK}{TK} — {1}: Target creature gains all creature types until end of turn.\n"
        "{TK}{TK}{TK} — Magecraft — Whenever you cast or copy an instant or sorcery spell, "
        "draw a card.\n"
        "{TK}{TK} — 2/4\n{TK}{TK}{TK}{TK}{TK} — 8/7"),
    # a one-shot ETB and a prefixed recurring trigger on one card
    "Case of the Crimson Pulse": (
        "Enchantment — Case",
        "When this Case enters, discard a card, then draw two cards.\n"
        "To solve — You have no cards in hand. (If unsolved, solve at the beginning of your "
        "end step.)\n"
        "Solved — At the beginning of your upkeep, discard your hand, then draw two cards."),
    # ── a draw in the trigger CONDITION is not a draw ───────────────────────────
    "Starving Revenant": (
        "Creature — Spirit Horror",
        "When this creature enters, surveil 2. Then for each card you put on top of your "
        "library, you draw a card and you lose 3 life.\n"
        "Descend 8 — Whenever you draw a card, if there are eight or more permanent cards in "
        "your graveyard, target opponent loses 1 life and you gain 1 life."),
    "Aether Syphon": (
        "Artifact",
        "Start your engines! (If you have no speed, it starts at 1. It increases once on each "
        "of your turns when an opponent loses life. Max speed is 4.)\n"
        "{2}, {T}: Draw a card.\n"
        "Max speed — Whenever you draw a card, each opponent mills two cards. (Each opponent "
        "puts the top two cards of their library into their graveyard.)"),
    "Tataru Taru": (
        "Legendary Creature — Dwarf Advisor",
        "When Tataru Taru enters, you draw a card and target opponent may draw a card.\n"
        "Scions' Secretary — Whenever an opponent draws a card, if it isn't that player's "
        "turn, create a tapped Treasure token. This ability triggers only once each turn."),
    # ── one-shot trigger behind a flavor word: stays card draw ──────────────────
    "Sister Repentia": (
        "Creature — Human Warrior",
        "Martyrdom — When this creature dies, you gain 2 life and draw two cards.\n"
        "Miracle {W}{B} (You may cast this card for its miracle cost when you draw it if it's "
        "the first card you drew this turn.)"),
    "Lord of Change": (
        "Creature — Demon",
        "Flying, ward {3}\nArchitect of Deception — When this creature enters, draw three "
        "cards."),
    "Skyship Buccaneer": (
        "Creature — Human Pirate",
        "Flying\nRaid — When this creature enters, if you attacked this turn, draw a card."),
    "Cool Fluffy Loxodon": (
        "Stickers",
        "{TK}{TK} — When this permanent leaves the battlefield, draw a card.\n"
        "{TK}{TK}{TK}{TK}{TK} — Whenever a creature enters under your control, this permanent "
        "becomes a 13/13 Eldrazi creature in addition to its other types until end of turn.\n"
        "{TK}{TK} — 4/2\n{TK}{TK}{TK}{TK} — 5/6"),
    # events that happen once, newly visible behind a flavor word
    "Khârn the Betrayer": (
        "Legendary Creature — Astartes Berserker",
        "Berzerker — Khârn the Betrayer attacks or blocks each combat if able.\n"
        "Sigil of Corruption — When you lose control of Khârn the Betrayer, draw two cards.\n"
        "The Betrayer — If damage would be dealt to Khârn the Betrayer, prevent that damage "
        "and an opponent of your choice gains control of it."),
    "Plundered Statue": (
        "Artifact",
        "At the beginning of the Horde's first main phase, reveal an additional card from the "
        "top of the Horde's library. The Horde casts that card.\n"
        "Hero's Reward — When Plundered Statue is put into a graveyard from anywhere, each "
        "player draws a card."),
    # ── a Saga chapter is not a trigger prefix ──────────────────────────────────
    "Battle of Frost and Fire": (
        "Enchantment — Saga",
        "(As this Saga enters and after your draw step, add a lore counter. Sacrifice after "
        "III.)\n"
        "I — This Saga deals 4 damage to each non-Giant creature and each planeswalker.\n"
        "II — Scry 3.\n"
        "III — Whenever you cast a spell with mana value 5 or greater this turn, draw two "
        "cards, then discard a card."),
}


def _fx(make_card, name):
    type_line, text = ORACLE[name]
    return tags.analyze(make_card(name, mana_cost="{3}", type_line=type_line,
                                  oracle_text=text))


@pytest.mark.parametrize("name,draw,engine", [
    ("Tatyova, Benthic Druid", 0, 1),
    ("Muse Seeker", 0, 1),
    ("Rydia, Summoner of Mist", 0, 1),
    ("Tallyman of Nurgle", 0, 2),
    ("Hollowmurk Siege", 0, 1),
    ("Monastery Siege", 0, 1),
    ("Playable Delusionary Hydra", 0, 2),
    ("Snazzy Aether Homunculus", 0, 1),
    ("Case of the Crimson Pulse", 2, 2),
    ("Starving Revenant", 1, 0),
    ("Aether Syphon", 0, 1),
    ("Tataru Taru", 1, 0),
    ("Sister Repentia", 2, 0),
    ("Lord of Change", 3, 0),
    ("Skyship Buccaneer", 1, 0),
    ("Cool Fluffy Loxodon", 1, 0),
    ("Khârn the Betrayer", 2, 0),
    ("Plundered Statue", 1, 0),
    ("Battle of Frost and Fire", 2, 0),
])
def test_a_trigger_behind_an_ability_word_is_a_trigger(make_card, name, draw, engine):
    fx = _fx(make_card, name)
    assert (fx.draw_cards, fx.engine_draw) == (draw, engine), name


def test_prefixed_one_shot_draws_take_the_max_not_the_sum():
    # Two verbatim one-shot lines (Lord of Change's ETB, Sister Repentia's martyrdom) on one
    # text: alternatives over the card's life, so the larger one, never 3 + 2.
    text = ("architect of deception — when this creature enters, draw three cards.\n"
            "martyrdom — when this creature dies, you gain 2 life and draw two cards.")
    assert tags._draw_counts(text) == (3, 0)


def test_a_prefixed_engine_is_repeatable_draw_in_the_swap_brief(make_card):
    assert "repeatable draw" in card_functions(_fx(make_card, "Tatyova, Benthic Druid"))
    assert "repeatable draw" not in card_functions(_fx(make_card, "Sister Repentia"))


def test_oracle_text_matches_the_store():
    from mythgauntlet.data.scryfall import load_card_db

    try:
        db = load_card_db()
    except FileNotFoundError:
        pytest.skip("no card store (CI)")
    for name, (type_line, text) in ORACLE.items():
        card = db.get(name)
        assert card is not None, name
        assert card.oracle_text == text, name
        assert card.type_line == type_line, name
