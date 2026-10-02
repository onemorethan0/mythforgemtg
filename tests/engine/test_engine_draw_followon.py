"""A draw in a trigger's FOLLOW-ON sentence fires exactly as often as the trigger.

`tags._draw_counts` classified each sentence on its own, so only a sentence that itself opened
with "whenever" / "when" / "at the beginning of" was triggered. Gix, Yawgmoth Praetor's
"Whenever a creature deals combat damage to one of your opponents, its controller may pay 1
life. If they do, they draw a card." scored an IMMEDIATE draw — ~170 recurring triggers in the
store (Academy Raider, Archon of Cruelty, Erebos) read as one card of advantage instead of an
engine. A follow-on sentence now inherits the trigger kind of the sentence it hangs off, the way
a reflexive "when you do" already did — so a one-shot ETB's follow-on stays one-shot.

Inheriting the kind also brought the trigger's own semantics along:

* "... draw a card. If <condition>, instead draw two cards" is one or the other (The Destined
  Thief, Fblthp): the follow-on was ADDED to the first draw.
* A trigger that sacrifices the card on its way to the draw fires once (Impaler Shrike,
  Charitable Levy); a sacrifice AFTER the draw ends an engine that has been drawing (Tellah,
  Rent Is Due).
* An anaphor in a follow-on is the opponent's only when the condition is opponent-scoped and
  the effect opens on "that player" / "they" (Skullknocker Ogre, Miss Highwater) — Gix's "its
  controller ... they draw" stays ours.

Oracle text below is verbatim from the Scryfall store; `test_oracle_text_matches_the_store`
re-checks that whenever the live store is present (CI has none and skips it).
"""

from __future__ import annotations

import pytest

from mythgauntlet.ratings.swap_brief import card_functions
from mythgauntlet.semantics import tags

ORACLE = {
    # ── recurring trigger, draw in a follow-on sentence: engines ────────────────
    "Gix, Yawgmoth Praetor": (
        "Legendary Creature — Phyrexian Praetor",
        "Whenever a creature deals combat damage to one of your opponents, its controller may "
        "pay 1 life. If they do, they draw a card.\n"
        "{4}{B}{B}{B}, Discard X cards: Exile the top X cards of target opponent's library. "
        "You may play lands and cast spells from among cards exiled this way without paying "
        "their mana costs."),
    "Academy Raider": (
        "Creature — Human Warrior",
        "Intimidate (This creature can't be blocked except by artifact creatures and/or "
        "creatures that share a color with it.)\n"
        "Whenever this creature deals combat damage to a player, you may discard a card. If "
        "you do, draw a card."),
    "Archon of Cruelty": (
        "Creature — Archon",
        "Flying\nWhenever this creature enters or attacks, target opponent sacrifices a "
        "creature or planeswalker of their choice, discards a card, and loses 3 life. You draw "
        "a card and gain 3 life."),
    # "when this enters AND whenever ..." recurs
    "Flaring Cinder": (
        "Creature — Elemental Sorcerer",
        "When this creature enters and whenever you cast a spell with mana value 4 or greater, "
        "you may discard a card. If you do, draw a card."),
    # an additive follow-on draw adds
    "Rayne, Academy Chancellor": (
        "Legendary Creature — Human Wizard",
        "Whenever you or a permanent you control becomes the target of a spell or ability an "
        "opponent controls, you may draw a card. You may draw an additional card if Rayne is "
        "enchanted."),
    # "instead" is one or the other: MAX, not sum
    "Ceta Sanctuary": (
        "Enchantment",
        "At the beginning of your upkeep, if you control a red or green permanent, draw a "
        "card, then discard a card. If you control a red permanent and a green permanent, "
        "instead draw two cards, then discard a card."),
    "The Destined Thief": (
        "Legendary Creature — Human Rogue",
        "The Destined Thief can't be blocked.\n"
        "{U}, {T}: Another target creature you control can't be blocked this turn.\n"
        "Whenever one or more creatures you control deal combat damage to one or more "
        "players, draw a card, then discard a card. If you have a full party, instead draw "
        "three cards."),
    "Kumena's Awakening": (
        "Enchantment",
        "Ascend (If you control ten or more permanents, you get the city's blessing for the "
        "rest of the game.)\nAt the beginning of your upkeep, each player draws a card. If you "
        "have the city's blessing, instead only you draw a card."),
    # a one-shot ETB and a recurring upkeep trigger on one card
    "Eye of Vecna": (
        "Legendary Artifact",
        "When Eye of Vecna enters, you draw a card and you lose 2 life.\n"
        "At the beginning of your upkeep, you may pay {2}. If you do, you draw a card and you "
        "lose 2 life."),
    # a nested trigger keeps its own kind
    "Azra Oddsmaker": (
        "Creature — Azra Warrior",
        "At the beginning of combat on your turn, you may discard a card. If you do, choose a "
        "creature. Whenever that creature deals combat damage to a player this turn, you draw "
        "two cards."),
    # ── one-shot trigger, follow-on stays one-shot ──────────────────────────────
    "Discerning Peddler": (
        "Creature — Human Rogue",
        "When this creature enters, you may discard a card. If you do, draw a card."),
    "Fblthp, the Lost": (
        "Legendary Creature — Homunculus",
        "When Fblthp enters, draw a card. If it entered from your library or was cast from "
        "your library, draw two cards instead.\n"
        "When Fblthp becomes the target of a spell, shuffle Fblthp into its owner's library."),
    "Rix Maadi Reveler": (
        "Creature — Human Shaman",
        "Spectacle {2}{B}{R} (You may cast this spell for its spectacle cost rather than its "
        "mana cost if an opponent lost life this turn.)\n"
        "When this creature enters, discard a card, then draw a card. If this creature's "
        "spectacle cost was paid, instead discard your hand, then draw three cards."),
    # "if you don't draw a card this way" draws nothing
    "Trade Route Envoy": (
        "Creature — Dog Soldier",
        "When this creature enters, draw a card if you control a creature with a counter on "
        "it. If you don't draw a card this way, put a +1/+1 counter on this creature."),
    "Selfcraft Mechan": (
        "Artifact Creature — Robot Artificer",
        "When this creature enters, you may sacrifice an artifact. When you do, put a +1/+1 "
        "counter on target creature and draw a card."),
    "Nevermind": (
        "Instant — Arcane",
        "(Spells without mana costs can't be played)\n"
        "When this spell resolves, discard a card. Then draw a card.\n"
        "Splice onto Anything {1}{R} (As you cast a spell, you may reveal this card from your "
        "hand and pay its splice cost. If you do, add this card's effect to that spell.)"),
    # ── the card is used up to pay for the draw: one-shot ───────────────────────
    "Impaler Shrike": (
        "Creature — Phyrexian Bird",
        "Flying\nWhenever this creature deals combat damage to a player, you may sacrifice "
        "it. If you do, draw three cards."),
    "Dreamcatcher": (
        "Creature — Spirit",
        "Whenever you cast a Spirit or Arcane spell, you may sacrifice this creature. If you "
        "do, draw a card."),
    "Charitable Levy": (
        "Enchantment",
        "Noncreature spells cost {1} more to cast.\n"
        "Whenever a player casts a noncreature spell, put a collection counter on this "
        "enchantment. Then if there are three or more collection counters on it, sacrifice "
        "it. If you do, draw a card, then you may search your library for a Plains card, put "
        "it onto the battlefield tapped, then shuffle."),
    # ... but a sacrifice AFTER the draw ends an engine that has been drawing
    "Rent Is Due": (
        "Enchantment",
        "At the beginning of your end step, you may tap two untapped creatures and/or "
        "Treasures you control. If you do, draw a card. Otherwise, sacrifice this "
        "enchantment."),
    "Tellah, Great Sage": (
        "Legendary Creature — Human Wizard",
        "Whenever you cast a noncreature spell, create a 1/1 colorless Hero creature token. If "
        "four or more mana was spent to cast that spell, draw two cards. If eight or more mana "
        "was spent to cast that spell, sacrifice Tellah and it deals that much damage to each "
        "opponent."),
    # ── whose draw ──────────────────────────────────────────────────────────────
    "Skullknocker Ogre": (
        "Creature — Ogre",
        "Whenever this creature deals damage to an opponent, that player discards a card at "
        "random. If the player does, they draw a card."),
    "Miss Highwater": (
        "Legendary Creature — Demon Advisor",
        "Menace\nWhenever Miss Highwater deals combat damage to a player who doesn't have a "
        "contract counter, they may discard their hand. If they do, they draw seven cards and "
        "get a contract counter. For as long as they have a contract counter, when they lose "
        "the game, for each artifact and creature they controlled, create a token that's a "
        "copy of it."),
    # the opponent discards, but the draw names "you"
    "Urgoros, the Empty One": (
        "Legendary Creature — Specter",
        "Flying\nWhenever Urgoros deals combat damage to a player, that player discards a card "
        "at random. If the player can't, you draw a card."),
}


def _fx(make_card, name):
    type_line, text = ORACLE[name]
    return tags.analyze(make_card(name, mana_cost="{3}", type_line=type_line,
                                  oracle_text=text))


@pytest.mark.parametrize("name,draw,engine", [
    ("Gix, Yawgmoth Praetor", 0, 1),
    ("Academy Raider", 0, 1),
    ("Archon of Cruelty", 0, 1),
    ("Flaring Cinder", 0, 1),
    ("Rayne, Academy Chancellor", 0, 2),
    ("Ceta Sanctuary", 0, 2),
    ("The Destined Thief", 0, 2),
    ("Kumena's Awakening", 0, 1),
    ("Eye of Vecna", 1, 1),
    ("Azra Oddsmaker", 0, 2),
    ("Discerning Peddler", 1, 0),
    ("Fblthp, the Lost", 2, 0),
    ("Rix Maadi Reveler", 3, 0),
    ("Trade Route Envoy", 1, 0),
    ("Selfcraft Mechan", 1, 0),
    ("Nevermind", 1, 0),
    ("Impaler Shrike", 3, 0),
    ("Dreamcatcher", 1, 0),
    ("Charitable Levy", 1, 0),
    ("Rent Is Due", 0, 1),
    ("Tellah, Great Sage", 0, 2),
    ("Skullknocker Ogre", 0, 0),
    ("Miss Highwater", 0, 0),
    ("Urgoros, the Empty One", 0, 1),
])
def test_follow_on_draw_inherits_the_trigger(make_card, name, draw, engine):
    fx = _fx(make_card, name)
    assert (fx.draw_cards, fx.engine_draw) == (draw, engine), name


def test_a_follow_on_engine_is_repeatable_draw_in_the_swap_brief(make_card):
    assert "repeatable draw" in card_functions(_fx(make_card, "Academy Raider"))
    assert "repeatable draw" not in card_functions(_fx(make_card, "Discerning Peddler"))
    assert "repeatable draw" not in card_functions(_fx(make_card, "Impaler Shrike"))


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
