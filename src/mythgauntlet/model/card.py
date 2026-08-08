"""Card record and mana-cost parsing.

The Card here is a *data* view (Layer 0): what Scryfall knows. What a card *does* is the
semantics layer's job (`mythgauntlet.semantics`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
COLORS = ("W", "U", "B", "R", "G")


def normalize_name(name: str) -> str:
    """Canonical lookup key for card names."""
    return " ".join(name.casefold().split())


@dataclass(frozen=True)
class ManaCost:
    """Parsed mana cost.

    Each pip is the set of colors that can pay it (mono = 1 color, hybrid = 2).
    Simplifications (documented, revisit at Phase 1):
      - Phyrexian pips ({G/P}) are treated as their color pip (life payment ignored).
      - Monocolor-hybrid ({2/W}) is treated as its color pip (never the generic option).
      - Snow ({S}) is treated as generic (snow-ness not tracked yet).
      - X contributes 0 to mana value and is cast for X=0.
    """

    generic: int = 0
    pips: tuple[frozenset[str], ...] = ()
    x_count: int = 0

    @property
    def mana_value(self) -> int:
        return self.generic + len(self.pips)

    @classmethod
    def parse(cls, text: str | None) -> ManaCost:
        if not text:
            return cls()
        generic = 0
        pips: list[frozenset[str]] = []
        x_count = 0
        for sym in MANA_SYMBOL_RE.findall(text):
            sym = sym.upper()
            if sym.isdigit():
                generic += int(sym)
            elif sym == "X":
                x_count += 1
            elif sym == "S":
                generic += 1
            elif sym == "C":
                pips.append(frozenset(("C",)))
            else:
                parts = [p for p in sym.split("/") if p != "P"]
                colors = frozenset(p for p in parts if p in COLORS or p == "C")
                if colors:
                    pips.append(colors)
                else:  # e.g. a lone numeric half after stripping (shouldn't occur)
                    nums = [int(p) for p in parts if p.isdigit()]
                    if nums:
                        generic += min(nums)
        return cls(generic=generic, pips=tuple(pips), x_count=x_count)


@dataclass
class Card:
    """One unique card (oracle identity, front face for multi-face layouts)."""

    name: str
    mana_cost_str: str = ""
    type_line: str = ""
    oracle_text: str = ""
    colors: tuple[str, ...] = ()
    color_identity: tuple[str, ...] = ()
    produced_mana: tuple[str, ...] = ()
    power: str | None = None
    toughness: str | None = None
    edhrec_rank: int | None = None
    game_changer: bool = False  # WotC Game Changers list, via Scryfall's game_changer flag
    # Scryfall legalities.commander == "legal". Defaults True so a hand-built Card (tests,
    # synthetic basics) is playable without having to say so; the store always sets it
    # explicitly from schema v3 on.
    commander_legal: bool = True
    layout: str = "normal"
    oracle_id: str = ""

    cost: ManaCost = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.cost = ManaCost.parse(self.mana_cost_str)

    @property
    def mana_value(self) -> int:
        return self.cost.mana_value

    def has_type(self, type_word: str) -> bool:
        return type_word.lower() in self.type_line.lower()

    @property
    def is_land(self) -> bool:
        return self.has_type("Land")

    @property
    def is_creature(self) -> bool:
        return self.has_type("Creature")

    @property
    def is_legendary(self) -> bool:
        return self.has_type("Legendary")

    @property
    def front_name(self) -> str:
        return self.name.split(" // ")[0]
