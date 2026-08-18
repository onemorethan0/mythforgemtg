"""Who may share a command zone (rule 903.10 and friends).

Offline: every card is a literal, so no Scryfall call. The oracle text below is the real
printed wording — an approximation here would test the approximation, not the rule.
"""
from __future__ import annotations

import pytest

import commander_analysis as ca


def _c(name, oracle="", type_line="Legendary Creature — Human"):
    return {"name": name, "oracle_text": oracle, "type_line": type_line}


PLAIN = "Partner (You can have two commanders if both have partner.)"

TYMNA = _c("Tymna the Weaver", "Lifelink\n" + PLAIN)
THRASIOS = _c("Thrasios, Triton Hero", "{4}: Scry 1, then draw a card.\n" + PLAIN)
PIR = _c("Pir, Imaginative Rascal",
         "Partner with Toothy, Imaginary Friend (When this creature enters, target player "
         "may put Toothy into their hand from their library, then shuffle.)")
TOOTHY = _c("Toothy, Imaginary Friend",
            "Partner with Pir, Imaginative Rascal (When this creature enters, target player "
            "may put Pir into their hand from their library, then shuffle.)")
WILSON = _c("Wilson, Refined Grizzly", "Vigilance, trample\nChoose a Background")
FACELESS = _c("Faceless One", "Faceless One's name is every name.",
              "Legendary Enchantment — Background")
KRAV = _c("Krav, the Unredeemed", "Friends forever (You can have two commanders if both have "
                                  "friends forever.)")
REGNA = _c("Regna, the Redeemer", "Friends forever (You can have two commanders if both have "
                                  "friends forever.)")
PLAIN_CMDR = _c("Kozilek, Butcher of Truth", "When you cast this spell, draw four cards.")


# ── which mechanic ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("card,expected", [
    (TYMNA, ca.PARTNER_PLAIN),
    (PIR, ca.PARTNER_WITH),
    (WILSON, ca.BACKGROUND_CHOOSER),
    (FACELESS, ca.BACKGROUND),
    (KRAV, ca.FRIENDS_FOREVER),
    (PLAIN_CMDR, None),
])
def test_partner_mechanic(card, expected):
    """`Partner with X` must be detected as its OWN mechanic, not as bare Partner —
    its reminder text contains the word "partner" too, so order of testing matters."""
    assert ca.partner_mechanic(card) == expected


# ── legal pairings ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    (TYMNA, THRASIOS),          # plain Partner + plain Partner
    (PIR, TOOTHY),              # Partner with, naming each other
    (TOOTHY, PIR),              # ...and the same in reverse
    (WILSON, FACELESS),         # Choose a Background + a Background
    (FACELESS, WILSON),
    (KRAV, REGNA),              # Friends forever
])
def test_legal_pairs(a, b):
    ok, why = ca.can_pair(a, b)
    assert ok, why


# ── refusals, each naming the rule ──────────────────────────────────────────────

@pytest.mark.parametrize("a,b,fragment", [
    (TYMNA, PLAIN_CMDR, "no partner ability"),
    (PLAIN_CMDR, TYMNA, "no partner ability"),
    (PIR, TYMNA, "Partner with"),          # one-way pairings do not exist
    (TYMNA, PIR, "Partner with"),
    (TYMNA, TYMNA, "itself"),
    (WILSON, TYMNA, "different partner abilities"),
    (KRAV, TYMNA, "different partner abilities"),
])
def test_illegal_pairs_are_refused_with_a_reason(a, b, fragment):
    """An illegal pair must be REFUSED, not built.

    The command zone's colour identity filters every other card in the deck, so an illegal
    pair does not make a slightly-wrong deck — it makes 99 cards chosen against an identity
    that is not legal to play. The message names the actual rule so the user can fix it.
    """
    ok, why = ca.can_pair(a, b)
    assert not ok
    assert fragment.casefold() in why.casefold(), why


def test_a_background_is_not_a_partner_for_a_plain_commander():
    """Backgrounds pair ONLY with "Choose a Background"; they are not universal partners."""
    ok, _ = ca.can_pair(FACELESS, THRASIOS)
    assert not ok


def test_the_zone_identity_and_themes_are_the_union():
    """The reason any of this matters downstream — already true, pinned here beside it."""
    tymna = dict(TYMNA, color_identity=["W", "B"])
    thrasios = dict(THRASIOS, color_identity=["G", "U"])
    assert set(ca.command_zone_identity(tymna, [thrasios])) == {"W", "B", "G", "U"}
