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

    `mana_value` is computed directly per CR 202.3 (each symbol's own rule) and is
    exact, including monocolored hybrid ({2/W} -> 2, the LARGER of its two components
    per CR 202.3f — verified against the live corpus 2026-08-24; a prior version of
    this class took `generic + len(pips)`, which silently undercounted {2/W} as 1
    because `pips` only ever records the colored half) and Phyrexian ({W/P} -> 1 per
    CR 202.3g). X contributes 0, matching CR 107.3g/202.3e (X is 0 off the stack).

    `generic`/`pips`/`x_count` are a SEPARATE, simplified model used only for PAYMENT
    simulation (`_can_pay` in `sim/tier0.py`) — they answer "can this be paid with
    these sources", not "what is this worth on the curve", and intentionally do not
    need to reconstruct `mana_value`. Payment simplifications (documented, revisit at
    Phase 1):
      - Phyrexian pips ({G/P}) are treated as their color pip (life payment ignored).
      - Monocolor-hybrid ({2/W}) is treated as its color pip for PAYMENT ONLY (a deck
        can always tap 1 W instead of 2 generic, so this is conservative-correct for
        castability even though `mana_value` now reports the true cost of 2).
      - Snow ({S}) is treated as generic (snow-ness not tracked yet).
    """

    generic: int = 0
    pips: tuple[frozenset[str], ...] = ()
    x_count: int = 0
    mana_value: int = 0

    @classmethod
    def parse(cls, text: str | None) -> ManaCost:
        if not text:
            return cls()
        generic = 0
        pips: list[frozenset[str]] = []
        x_count = 0
        mana_value = 0
        for sym in MANA_SYMBOL_RE.findall(text):
            sym = sym.upper()
            if sym.isdigit():
                generic += int(sym)
                mana_value += int(sym)
            elif sym == "X":
                x_count += 1
            elif sym == "S":
                generic += 1
                mana_value += 1
            elif sym == "C":
                pips.append(frozenset(("C",)))
                mana_value += 1
            else:
                parts = [p for p in sym.split("/") if p != "P"]
                colors = frozenset(p for p in parts if p in COLORS or p == "C")
                if colors:
                    pips.append(colors)
                    # CR 202.3f: a hybrid symbol's mana-value contribution is the
                    # LARGER of its components. A pure-color hybrid ({W/U}) has no
                    # numeric half, so it's 1 either way; a monocolored hybrid
                    # ({2/W}) is 2, not the 1 that `len(pips)` alone would imply.
                    nums = [int(p) for p in parts if p.isdigit()]
                    mana_value += max(nums) if nums else 1
                else:  # e.g. a lone numeric half after stripping (shouldn't occur)
                    nums = [int(p) for p in parts if p.isdigit()]
                    if nums:
                        generic += min(nums)
                        mana_value += min(nums)
        return cls(generic=generic, pips=tuple(pips), x_count=x_count, mana_value=mana_value)


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
