"""`engine_draw` is a PER-TURN engine; a one-shot trigger is not one.

Found live 2026-10-01 (docs/MENTOR_HANDOFF.md, end of round 8): the swap brief called Solemn
Simulacrum's "When this creature dies, you may draw a card." a **repeatable draw**, and the
Deck Mentor repeated it — a wrong tool fact, not a model fabrication. `tags._draw_counts`
treated every trigger (including "when ...") as an engine; 406 cards in the store were
engines only through a dies / enters / leaves / cast trigger.

Oracle text below is verbatim from the Scryfall store; `test_oracle_text_matches_the_store`
re-checks that whenever the live store is present (CI has none and skips it).
"""

from __future__ import annotations

import pytest

from mythgauntlet.ratings.swap_brief import card_functions
from mythgauntlet.semantics import tags

ORACLE = {
    "Solemn Simulacrum": (
        "Artifact Creature — Golem",
        "When this creature enters, you may search your library for a basic land card, put "
        "that card onto the battlefield tapped, then shuffle.\n"
        "When this creature dies, you may draw a card."),
    "Mulldrifter": (
        "Creature — Elemental",
        "Flying\nWhen this creature enters, draw two cards.\n"
        "Evoke {2}{U} (You may cast this spell for its evoke cost. If you do, it's "
        "sacrificed when it enters.)"),
    "Rhystic Study": (
        "Enchantment",
        "Whenever an opponent casts a spell, you may draw a card unless that player pays {1}."),
    "Phyrexian Arena": (
        "Enchantment",
        "At the beginning of your upkeep, you draw a card and lose 1 life."),
    "Sylvan Library": (
        "Enchantment",
        "At the beginning of your draw step, you may draw two additional cards. If you do, "
        "choose two cards in your hand drawn this turn. For each of those cards, pay 4 life "
        "or put the card on top of your library."),
    # "when" + "whenever" in one condition: the whenever half recurs.
    "Up the Beanstalk": (
        "Enchantment",
        "When this enchantment enters and whenever you cast a spell with mana value 5 or "
        "greater, draw a card."),
    # the legendary name's own comma must not hide the event
    "Lutri, Pauper Otter": (
        "Legendary Creature — Elemental Otter",
        "Companion — Your starting deck contains no cards with a silver, gold, orange, or "
        "purple expansion symbol. (If this card is your chosen companion, you may put it into "
        "your hand from outside the game for {3} as a sorcery.)\n"
        "When Lutri, Pauper Otter enters the battlefield, discard your hand, then draw "
        "three cards."),
    # reflexive trigger under a one-shot ETB: one-shot
    "Selfcraft Mechan": (
        "Artifact Creature — Robot Artificer",
        "When this creature enters, you may sacrifice an artifact. When you do, put a +1/+1 "
        "counter on target creature and draw a card."),
    # reflexive trigger under an every-attack exert: repeatable
    "Watchful Naga": (
        "Creature — Snake Wizard",
        "You may exert this creature as it attacks. When you do, draw a card. (An exerted "
        "creature won't untap during your next untap step.)"),
    # "when" alone is not proof of one-shot: this recurs every combat
    "The Belligerent and Useless Island": (
        "Legendary Artifact Land — Vehicle Island",
        "({T}: Add {U}.)\nThe Belligerent and Useless Island enter the battlefield tapped.\n"
        "When The Belligerent and Useless Island deal combat damage to a player or battle, "
        "draw a card, then discard a card.\nCrew 2"),
    # two alternative one-shots: MAX, not sum
    "Market Gnome": (
        "Artifact Creature — Gnome",
        "When this creature dies, you gain 1 life and draw a card.\n"
        "When this creature is exiled from the battlefield while you're activating a craft "
        "ability, you gain 1 life and draw a card."),
    # a draw that replaces LOSING is not card advantage
    "Nira, Hellkite Duelist": (
        "Legendary Creature — Dragon",
        "Flash\nFlying, trample, haste\nWhen Nira, Hellkite Duelist enters, the next time you "
        "would lose the game this turn, instead draw three cards and your life total becomes "
        "5."),
    # a one-shot is uncapped, unlike the per-turn engine's 2
    "Kozilek, Butcher of Truth": (
        "Legendary Creature — Eldrazi",
        "When you cast this spell, draw four cards.\nAnnihilator 4 (Whenever this creature "
        "attacks, defending player sacrifices four permanents of their choice.)\nWhen "
        "Kozilek is put into a graveyard from anywhere, its owner shuffles their graveyard into their library."),
}


def _fx(make_card, name):
    type_line, text = ORACLE[name]
    return tags.analyze(make_card(name, mana_cost="{3}", type_line=type_line,
                                  oracle_text=text))


@pytest.mark.parametrize("name,draw,engine", [
    ("Solemn Simulacrum", 1, 0),
    ("Mulldrifter", 2, 0),
    ("Rhystic Study", 0, 1),
    ("Phyrexian Arena", 0, 1),
    ("Sylvan Library", 0, 2),
    ("Up the Beanstalk", 0, 1),
    ("Lutri, Pauper Otter", 3, 0),
    ("Selfcraft Mechan", 1, 0),
    ("Watchful Naga", 0, 1),
    ("The Belligerent and Useless Island", 0, 1),
    ("Market Gnome", 1, 0),
    ("Kozilek, Butcher of Truth", 4, 0),
    ("Nira, Hellkite Duelist", 0, 0),
])
def test_engine_draw_is_gated_on_trigger_shape(make_card, name, draw, engine):
    fx = _fx(make_card, name)
    assert (fx.draw_cards, fx.engine_draw) == (draw, engine), name


def test_solemn_is_card_draw_not_repeatable_draw_in_the_swap_brief(make_card):
    """The exact tool fact the mentor repeated."""
    functions = card_functions(_fx(make_card, "Solemn Simulacrum"))
    assert functions.get("card draw") == 1.0
    assert "repeatable draw" not in functions
    assert "repeatable draw" in card_functions(_fx(make_card, "Rhystic Study"))


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
