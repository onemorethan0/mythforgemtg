"""Collection import: MythScanner/Moxfield-style CSV or plain decklist text.

CSV is detected by a header row containing a recognizable name column; anything else is
parsed as a plain decklist ("1 Sol Ring" lines). Column matching is case-insensitive and
liberal (MythScanner exports, Moxfield collection CSVs, and hand-rolled sheets all differ).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from mythgauntlet.model.card import normalize_name
from mythgauntlet.model.deck import Deck

_NAME_COLUMNS = ("name", "card name", "card")
_COUNT_COLUMNS = ("count", "quantity", "qty")


@dataclass
class Collection:
    counts: dict[str, int] = field(default_factory=dict)  # normalized name -> quantity

    def owned(self, name: str) -> int:
        return self.counts.get(normalize_name(name), 0)

    def add(self, name: str, count: int = 1) -> None:
        key = normalize_name(name)
        self.counts[key] = self.counts.get(key, 0) + count

    @property
    def total_cards(self) -> int:
        return sum(self.counts.values())

    @property
    def unique_cards(self) -> int:
        return len(self.counts)

    @classmethod
    def load(cls, path: str | Path) -> Collection:
        return cls.parse(Path(path).read_text(encoding="utf-8-sig"))

    @classmethod
    def parse(cls, text: str) -> Collection:
        """Sniff CSV vs plain decklist and parse accordingly (suite contract C1)."""
        first_line = text.lstrip().splitlines()[0] if text.strip() else ""
        if "," in first_line and _find_column(first_line.split(","), _NAME_COLUMNS):
            return cls.from_csv(text)
        return cls.from_decklist(text)

    @classmethod
    def from_csv(cls, text: str) -> Collection:
        collection = cls()
        reader = csv.DictReader(text.splitlines())
        fieldnames = reader.fieldnames or []
        name_col = _find_column(fieldnames, _NAME_COLUMNS)
        count_col = _find_column(fieldnames, _COUNT_COLUMNS)
        if name_col is None:
            raise ValueError(f"No recognizable name column in CSV header: {fieldnames}")
        for row in reader:
            name = (row.get(name_col) or "").strip()
            if not name:
                continue
            count = 1
            if count_col:
                raw = (row.get(count_col) or "").strip()
                try:
                    count = max(1, int(float(raw)))
                except ValueError:
                    count = 1
            collection.add(name, count)
        return collection

    @classmethod
    def from_decklist(cls, text: str) -> Collection:
        collection = cls()
        deck = Deck.parse_text(text)
        for name in deck.commanders:
            collection.add(name, 1)
        for entry in deck.entries:
            collection.add(entry.name, entry.count)
        return collection


def _find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {f.strip().casefold(): f for f in fieldnames if f}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None
