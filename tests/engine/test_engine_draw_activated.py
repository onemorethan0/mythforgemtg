"""A permanent's repeatable ACTIVATED draw is a per-turn engine; whose draw it is matters too.

The converse of test_engine_draw_trigger_shape.py: `tags._draw_counts` read "{T}: Draw a card"
as an IMMEDIATE draw on resolution, so Jayemdae Tome was one card of advantage and Arcanis
the Omnipotent a three-card spell — ~500 permanents in the store. Only a cost that consumes
the card itself (Sunbeam Spellbomb, Courier's Briefcase), an ability capped at once per game,
or a planeswalker's − ability is really one-shot.

Same pass, the subject of the draw: "that player draws" after an opponent-scoped trigger is
the OPPONENT's draw (Coveted Jewel, Well of Ideas), and the old 30-character "opponent"
window threw away OUR draw whenever a trigger condition merely named an opponent
(Thieving Magpie).

Oracle text below is verbatim from the Scryfall store; `test_oracle_text_matches_the_store`
re-checks that whenever the live store is present (CI has none and skips it).
"""

from __future__ import annotations

import pytest

from mythgauntlet.ratings.swap_brief import card_functions
from mythgauntlet.semantics import tags

ORACLE = {
    # ── repeatable activations: engines ─────────────────────────────────────────
    "Jayemdae Tome": ("Artifact — Book", "{4}, {T}: Draw a card."),
    # the engine cap of 2 holds for an activation too
    "Arcanis the Omnipotent": (
        "Legendary Creature — Wizard",
        "{T}: Draw three cards.\n{2}{U}{U}: Return Arcanis to its owner's hand."),
    "Griselbrand": ("Legendary Creature — Demon", "Flying, lifelink\nPay 7 life: Draw seven cards."),
    # two {T} abilities are alternatives: MAX, not sum
    "Krovikan Sorcerer": (
        "Creature — Human Wizard Sorcerer",
        "{T}, Discard a nonblack card: Draw a card.\n"
        "{T}, Discard a black card: Draw two cards, then discard one of them."),
    # "draw a card ... draw two cards instead" is one or the other
    "Zimone, Quandrix Prodigy": (
        "Legendary Creature — Human Wizard",
        "{1}, {T}: You may put a land card from your hand onto the battlefield tapped.\n"
        "{4}, {T}: Draw a card. If you control eight or more lands, draw two cards instead."),
    # sacrificing OTHER permanents is a renewable cost
    "Ruthless Knave": (
        "Creature — Orc Pirate",
        "{2}{B}, Sacrifice a creature: Create two Treasure tokens. (They're artifacts with "
        "\"{T}, Sacrifice this token: Add one mana of any color.\")\n"
        "Sacrifice three Treasures: Draw a card."),
    # a Spacecraft station threshold in front of the cost
    "Hearthhull, the Worldseed": (
        "Legendary Artifact — Spacecraft",
        "Station (Tap another creature you control: Put charge counters equal to its power on "
        "this Spacecraft. Station only as a sorcery. It's an artifact creature at 8+.)\n"
        "2+ | {1}, {T}, Sacrifice a land: Draw two cards. You may play an additional land "
        "this turn.\n8+ | Flying, vigilance, haste\n"
        "Whenever you sacrifice a land, each opponent loses 2 life."),
    # + loyalty is every turn; − loyalty is one-shot
    "Ral, Caller of Storms": (
        "Legendary Planeswalker — Ral",
        "+1: Draw a card.\n−2: Ral deals 3 damage divided as you choose among one, two, or "
        "three targets.\n−7: Draw seven cards. Ral deals 7 damage to each creature your "
        "opponents control."),
    # ── self-consuming costs: one-shot ──────────────────────────────────────────
    "Sunbeam Spellbomb": (
        "Artifact",
        "{W}, Sacrifice this artifact: You gain 5 life.\n"
        "{1}, Sacrifice this artifact: Draw a card."),
    "Courier's Briefcase": (
        "Artifact — Treasure",
        "When this artifact enters, create a 1/1 green and white Citizen creature token.\n"
        "{T}, Sacrifice this artifact: Add one mana of any color.\n"
        "{W}{U}{B}{R}{G}, {T}, Sacrifice this artifact: Draw three cards."),
    "Commander's Sphere": (
        "Artifact",
        "{T}: Add one mana of any color in your commander's color identity.\n"
        "Sacrifice this artifact: Draw a card."),
    # old wording names the card instead of "this artifact"
    "Stone of Erech": (
        "Legendary Artifact",
        "If a creature an opponent controls would die, exile it instead.\n"
        "{2}, {T}, Sacrifice Stone of Erech: Exile target player's graveyard. Draw a card."),
    # the EFFECT puts the card away: it draws itself back, never an engine
    "Sensei's Divining Top": (
        "Artifact",
        "{1}: Look at the top three cards of your library, then put them back in any order.\n"
        "{T}: Draw a card, then put this artifact on top of its owner's library."),
    # one of each on one card
    "Compulsion": (
        "Enchantment",
        "{1}{U}, Discard a card: Draw a card.\n{1}{U}, Sacrifice this enchantment: Draw a card."),
    # ── whose draw ──────────────────────────────────────────────────────────────
    "Coveted Jewel": (
        "Artifact",
        "When this artifact enters, draw three cards.\n{T}: Add three mana of any one color.\n"
        "Whenever one or more creatures an opponent controls attack you and aren't blocked, "
        "that player draws three cards and gains control of this artifact. Untap it."),
    "Well of Ideas": (
        "Enchantment",
        "When this enchantment enters, draw two cards.\n"
        "At the beginning of each other player's draw step, that player draws an additional "
        "card.\nAt the beginning of your draw step, draw two additional cards."),
    "Soldevi Sentry": (
        "Artifact Creature — Soldier",
        "{1}: Choose target opponent. Regenerate this creature. When it regenerates this way, "
        "that player may draw a card."),
    "Forced Fruition": (
        "Enchantment", "Whenever an opponent casts a spell, that player draws seven cards."),
    "Words of Wisdom": (
        "Instant", "You draw two cards, then each other player draws a card."),
    # only an opponent can activate it, so the bare "Draw a card" is theirs ...
    "Oft-Nabbed Goat": (
        "Creature — Goat",
        "{1}: Draw a card. Gain control of this creature and put a -1/-1 counter on it. Only "
        "your opponents may activate this ability and only as a sorcery.\n"
        "When this creature dies, if it had one or more -1/-1 counters on it, its owner draws "
        "that many cards and each other player loses that much life."),
    # ... but this one names its controller (us) — on the opponent's schedule, not an engine
    "Soul Ransom": (
        "Enchantment — Aura",
        "Enchant creature\nYou control enchanted creature.\n"
        "Discard two cards: This Aura's controller sacrifices it, then draws two cards. Only "
        "your opponents may activate this ability."),
    # an opponent in the trigger condition does not make the draw theirs
    "Thieving Magpie": (
        "Creature — Bird",
        "Flying (This creature can't be blocked except by creatures with flying or reach.)\n"
        "Whenever this creature deals damage to an opponent, draw a card."),
    "Farsight Adept": (
        "Creature — Kor Wizard",
        "When this creature enters, you and target opponent each draw a card."),
    # the opponent's choice: a punisher, not card advantage we can plan on
    "Combustible Gearhulk": (
        "Artifact Creature — Construct",
        "First strike\nWhen this creature enters, target opponent may have you draw three "
        "cards. If the player doesn't, you mill three cards, then this creature deals damage "
        "to that player equal to the total mana value of those cards."),
    # "they" here is the damaging creature's controller — ours; the anaphor rule must not
    # reach across sentences
    "Gix, Yawgmoth Praetor": (
        "Legendary Creature — Phyrexian Praetor",
        "Whenever a creature deals combat damage to one of your opponents, its controller may "
        "pay 1 life. If they do, they draw a card.\n"
        "{4}{B}{B}{B}, Discard X cards: Exile the top X cards of target opponent's library. "
        "You may play lands and cast spells from among cards exiled this way without paying "
        "their mana costs."),
}


def _fx(make_card, name):
    type_line, text = ORACLE[name]
    return tags.analyze(make_card(name, mana_cost="{3}", type_line=type_line,
                                  oracle_text=text))


@pytest.mark.parametrize("name,draw,engine", [
    ("Jayemdae Tome", 0, 1),
    ("Arcanis the Omnipotent", 0, 2),
    ("Griselbrand", 0, 2),
    ("Krovikan Sorcerer", 0, 2),
    ("Zimone, Quandrix Prodigy", 0, 2),
    ("Ruthless Knave", 0, 1),
    ("Hearthhull, the Worldseed", 0, 2),
    ("Ral, Caller of Storms", 7, 1),
    ("Sunbeam Spellbomb", 1, 0),
    ("Courier's Briefcase", 3, 0),
    ("Commander's Sphere", 1, 0),
    ("Stone of Erech", 1, 0),
    ("Sensei's Divining Top", 1, 0),
    ("Compulsion", 1, 1),
    ("Coveted Jewel", 3, 0),
    ("Well of Ideas", 2, 2),
    ("Soldevi Sentry", 0, 0),
    ("Forced Fruition", 0, 0),
    ("Words of Wisdom", 2, 0),
    ("Oft-Nabbed Goat", 0, 0),
    ("Soul Ransom", 2, 0),
    ("Thieving Magpie", 0, 1),
    ("Farsight Adept", 1, 0),
    ("Combustible Gearhulk", 0, 0),
])
def test_draw_counts_activation_and_subject(make_card, name, draw, engine):
    fx = _fx(make_card, name)
    assert (fx.draw_cards, fx.engine_draw) == (draw, engine), name


def test_an_anaphor_outside_the_opponent_trigger_stays_ours(make_card):
    fx = _fx(make_card, "Gix, Yawgmoth Praetor")
    assert fx.draw_cards + fx.engine_draw == 1


def test_a_tap_to_draw_permanent_is_repeatable_draw_in_the_swap_brief(make_card):
    functions = card_functions(_fx(make_card, "Jayemdae Tome"))
    assert "repeatable draw" in functions
    assert "card draw" not in functions
    assert "repeatable draw" not in card_functions(_fx(make_card, "Sunbeam Spellbomb"))


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
