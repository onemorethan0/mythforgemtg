"""Denial: how much a deck stops OTHER players from playing (D2, docs/DESIGN_table_brackets.md).

The official brackets gate on famous cards; what makes a casual game feel bad is often a card
that takes the game away from three people -- a lock piece, a counterspell wall, a stolen
board. This module names those cards, so a deck can say "plays two lock pieces and eleven
counterspells" next to its bracket. It does not move the bracket: that is D3's dial and a
measured decision, not a list.

A LOCK is a continuous effect (a permanent, never a one-shot spell) that, while it stays, stops
opponents -- or every player -- from doing a core thing, with no per-instance payment that gets
around it. Six kinds, each read from the card's own text, gated on its object and its scope:

  untap         permanents don't untap (Stasis, Winter Orb, Smoke, Damping Field)
  spell_limit   one spell a turn, or spells only from hand (Rule of Law, Drannith Magistrate)
  draw_limit    one card a turn (Spirit of the Labyrinth, Narset, Parter of Veils)
  attack        creatures can't attack, or only one can (Moat, Ensnaring Bridge, Silent Arbiter)
  cant_lose     damage or life loss can't finish you (Solitary Confinement, Platinum Emperion)
  ability       whole classes of activated abilities are off (Cursed Totem, Null Rod)

Not locks, on purpose: taxes a player can pay (Ghostly Prison, Propaganda, Sphere of
Resistance, Grand Arbiter's cost increase) -- a later "stax" role; one-shot effects (Fog,
Teferi's Protection); locks on ONE target (Pithing Needle's chosen name, an Arrest); limits on
yourself (Celestial Dawn); and effects only on your own turn (Grand Abolisher), which stop
interaction, not play. Under-count rather than fabricate: a card the patterns can't read and the
list doesn't name is simply not a lock.

`LOCK_LIST` names the few locks no pattern reaches without reading other cards' text too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mythgauntlet.model.card import Card

# Locks whose text no object-gated pattern reads safely. Each with the reason it is a lock.
LOCK_LIST: dict[str, tuple[str, str]] = {
    "The Tabernacle at Pendrell Vale": (
        "untap", "every creature costs {1} each upkeep or is destroyed -- mana creatures and "
                 "wide boards stop working"),
    "Smokestack": ("untap", "each upkeep every player sacrifices a growing number of permanents"),
    "Opposition": ("untap", "taps down opponents' lands and creatures every turn"),
}

_PERMANENT_TYPES = ("Artifact", "Creature", "Enchantment", "Land", "Planeswalker", "Battle")

# Not locks although a pattern reads them as one, each with the reason.
NOT_LOCKS: dict[str, str] = {
    "Intruder Alarm": "untaps every creature whenever a creature enters -- a combo piece, not a lock",
}

# Scope: who the effect binds. The SUBJECT must open the sentence and be generic ("Creatures",
# "Players", "Each player", "Your opponents"): a colour ("Blue creatures"), a target ("those
# creatures", "enchanted"), a narrow subset ("Creatures with flying", "with power 2 or less",
# "with counters on them") or your own permanents is a hoser or a removal spell, not a lock.
_S = r"(?:^|(?<=[.!] ))"   # start of a sentence
_LOCK_RES: tuple[tuple[str, re.Pattern], ...] = (
    ("untap", re.compile(
        _S + r"(?:as long as [^,]+, )?players can'?t untap more than (?:one|two)\b"
        r"|" + _S + r"players skip their untap steps\b"
        r"|" + _S + r"(?:nonbasic |nonland |legendary )?(?:lands|creatures|artifacts|permanents)"
        r" don'?t untap during their controllers'? untap steps\b",
        re.IGNORECASE | re.MULTILINE)),
    ("spell_limit", re.compile(
        _S + r"(?:each player|players|your opponents|each opponent) can'?t cast more than one\b"
        r"|" + _S + r"each player who has cast a nonartifact spell this turn can'?t cast additional\b"
        r"|" + _S + r"(?:your opponents|each opponent|players) can'?t cast spells from anywhere"
        r" other than their hands?\b",
        re.IGNORECASE | re.MULTILINE)),
    ("draw_limit", re.compile(
        _S + r"(?:each player|each opponent|players|your opponents) can'?t draw more than one"
        r" card each turn\b",
        re.IGNORECASE | re.MULTILINE)),
    ("attack", re.compile(
        _S + r"creatures(?: without flying(?: or islandwalk)?| with power greater than the number"
        r" of cards in your hand)? can'?t attack(?: you)?(?: or planeswalkers you control)?\.(?:$| )"
        r"|" + _S + r"no more than one creature can attack each combat\b",
        re.IGNORECASE | re.MULTILINE)),
    ("cant_lose", re.compile(
        _S + r"prevent all damage that would be dealt to you\.(?:$| )"
        r"|\byour life total can'?t change\b"
        r"|" + _S + r"(?:if you control a creature, )?damage that would reduce your life total to"
        r" less than 1 reduces it to 1 instead\b"
        r"|\byou can'?t lose the game\b",
        re.IGNORECASE | re.MULTILINE)),
    ("ability", re.compile(
        _S + r"activated abilities of (?:artifacts|creatures|artifacts and creatures)(?: your"
        r" opponents control)? can'?t be activated",
        re.IGNORECASE | re.MULTILINE)),
)
# A payment, a one-turn window or a choice to untap anyway makes it a tax or a trick, not a lock.
_ESCAPE_RE = re.compile(r"\buntil end of turn\b|\bunless\b", re.IGNORECASE)
_PAY_TO_UNTAP_RE = re.compile(r"\bmay choose any number of tapped\b[^.]*\bpay\b", re.IGNORECASE)

# Theft: a lasting change of control. "until end of turn" (Threaten, Insurrection) is a turn's
# loan, not denial of the board.
_THEFT_RE = re.compile(r"(?:\bgain control of (?:target|all|each|enchanted)\b"
                       r"|^you control enchanted (?:creature|permanent|artifact|land|planeswalker)\b)"
                       r"(?![^.]*until end of turn)(?![^.]*\byou own\b)",
                       re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Lock:
    name: str
    kind: str
    reason: str


def _is_permanent(card: Card) -> bool:
    front = (card.type_line or "").split(" // ")[0]
    return any(t in front for t in _PERMANENT_TYPES)


def lock_of(card: Card) -> Lock | None:
    """The card's lock, or None. Permanents only: a one-turn effect is not a lock."""
    from mythgauntlet.ratings.bracket import _gate_text   # planeswalker ultimates stripped

    listed = LOCK_LIST.get(card.name)
    if listed:
        return Lock(card.name, listed[0], listed[1])
    if card.name in NOT_LOCKS or not _is_permanent(card):
        return None
    if _PAY_TO_UNTAP_RE.search(card.oracle_text or ""):   # Dream Tides: a tax in its own sentence
        return None
    for sentence_block in _gate_text(card.oracle_text).split("\n"):
        for kind, rx in _LOCK_RES:
            m = rx.search(sentence_block)
            if m and not _ESCAPE_RE.search(_sentence_at(sentence_block, m.start())):
                return Lock(card.name, kind, m.group(0).strip(" .").rstrip())
    return None


def _sentence_at(text: str, pos: int) -> str:
    """The sentence of `text` containing `pos` (an escape clause must be in the SAME sentence:
    Peacekeeper's upkeep "unless you pay" does not make "Creatures can't attack" a tax)."""
    start = max(text.rfind(". ", 0, pos), -1) + 1
    end = text.find(". ", pos)
    return text[start:] if end == -1 else text[start:end + 1]


def steals(card: Card) -> bool:
    return bool(_THEFT_RE.search(card.oracle_text or ""))


@dataclass
class DeckDenial:
    locks: list[Lock] = field(default_factory=list)
    counterspells: int = 0
    theft: int = 0
    extra_turn_cards: int = 0
    mass_land_denial: list[str] = field(default_factory=list)


def deck_denial(cards: list[tuple[Card, int]], commanders: list[Card]) -> DeckDenial:
    """Every denial role in a deck: lock pieces by name, counterspells (the tagger's own
    `counterspell` fact), lasting theft, extra-turn cards and mass land denial (the bracket
    gate's own reader, so the numbers agree with the bracket reasons)."""
    from mythgauntlet.ratings.bracket import _scan
    from mythgauntlet.semantics import tags

    out = DeckDenial()
    seen: set[str] = set()
    for card, n in list(cards) + [(c, 1) for c in commanders]:
        lock = lock_of(card)
        if lock is not None and card.name not in seen:
            out.locks.append(lock)
        seen.add(card.name)
        if not card.is_land and tags.analyze(card).counterspell:
            out.counterspells += n
        if steals(card):
            out.theft += n
        extra, mld = _scan([(card, n)])
        out.extra_turn_cards += extra
        if mld and card.name not in out.mass_land_denial:
            out.mass_land_denial.append(card.name)
    return out
