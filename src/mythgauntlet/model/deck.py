"""Decklist parsing and deck resolution.

Accepts the common plain-text shapes:

    1 Sol Ring
    2x Island
    Sol Ring                      (implicit quantity 1)
    1 Lightning Bolt (M21) 161    (Moxfield/Arena set suffix, stripped)
    1 Kess, Dissident Mage *CMDR* (TappedOut commander marker)

    Commander:                    (section headers, case-insensitive,
    1 Kess, Dissident Mage         trailing ':' optional)
    Deck:
    ...

Lines starting with '#' are comments. Sideboard/maybeboard sections are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mythgauntlet.data.scryfall import CardDb
    from mythgauntlet.model.card import Card

QTY_RE = re.compile(r"^(\d+)\s*[xX]?\s+(.+)$")
SET_SUFFIX_RE = re.compile(r"\s*\([A-Za-z0-9]{2,6}\)\s*[\w★-]*\s*$")
FOIL_RE = re.compile(r"\s*\*[FE]\*\s*$")
CMDR_RE = re.compile(r"\s*\*CMDR\*\s*", re.IGNORECASE)

COMMANDER_HEADERS = {"commander", "commanders"}
MAIN_HEADERS = {"deck", "main", "mainboard", "99"}
IGNORED_HEADERS = {"sideboard", "maybeboard", "considering", "tokens"}


@dataclass
class DeckEntry:
    name: str
    count: int = 1


@dataclass
class Deck:
    name: str = ""
    commanders: list[str] = field(default_factory=list)
    entries: list[DeckEntry] = field(default_factory=list)

    @property
    def total_cards(self) -> int:
        return len(self.commanders) + sum(e.count for e in self.entries)

    @classmethod
    def parse_text(cls, text: str, name: str = "") -> Deck:
        deck = cls(name=name)
        section = "main"
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            header = line.rstrip(":").strip().casefold()
            if header in COMMANDER_HEADERS:
                section = "commander"
                continue
            if header in MAIN_HEADERS:
                section = "main"
                continue
            if header in IGNORED_HEADERS:
                section = "ignored"
                continue
            if section == "ignored":
                continue

            count = 1
            m = QTY_RE.match(line)
            if m:
                count = int(m.group(1))
                line = m.group(2)
            is_cmdr = bool(CMDR_RE.search(line))
            line = CMDR_RE.sub(" ", line)
            line = FOIL_RE.sub("", line)
            line = SET_SUFFIX_RE.sub("", line).strip()
            if not line:
                continue
            if is_cmdr or section == "commander":
                deck.commanders.append(line)
            else:
                deck.entries.append(DeckEntry(name=line, count=count))
        return deck


@dataclass
class ResolvedDeck:
    """A Deck with names resolved against a CardDb."""

    deck: Deck
    commanders: list[Card]
    cards: list[tuple[Card, int]]
    missing: list[str]

    @property
    def card_count(self) -> int:
        return len(self.commanders) + sum(n for _, n in self.cards)


def resolve(deck: Deck, db: CardDb) -> ResolvedDeck:
    commanders: list[Card] = []
    cards: list[tuple[Card, int]] = []
    missing: list[str] = []
    for name in deck.commanders:
        card = db.get(name)
        if card is None:
            missing.append(name)
        else:
            commanders.append(card)
    for entry in deck.entries:
        card = db.get(entry.name)
        if card is None:
            missing.append(entry.name)
        else:
            cards.append((card, entry.count))
    return ResolvedDeck(deck=deck, commanders=commanders, cards=cards, missing=missing)
