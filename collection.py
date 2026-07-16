"""Myth Suite collection contract (C1): read the user's owned-cards export.

The canonical file is ``%USERPROFILE%/Documents/MythSuite/collection.csv`` (a Moxfield-style
CSV written by MythScanner). Both ends of the suite honor the same ``MYTHSUITE_DIR`` override
(MythGauntlet's ``config.suite_collection_path`` and MythScanner's exporter mirror this) —
keep them in lock-step. See mythgauntlet/docs/SUITE_PLAN.md for the authoritative contract.

Collection-aware building only needs the SET of owned card names, normalized so it matches
Scryfall card names (front face, case-insensitive).
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

_NAME_COLUMNS = ("name", "card name", "card")


def suite_dir() -> Path:
    """The Myth Suite handoff directory (contract C1). Override: MYTHSUITE_DIR."""
    override = os.environ.get("MYTHSUITE_DIR")
    return Path(override) if override else Path.home() / "Documents" / "MythSuite"


def suite_collection_path() -> Path:
    """Canonical collection file (Moxfield CSV) — contract C1."""
    return suite_dir() / "collection.csv"


def owned_key(name: str) -> str:
    """Normalize a card name for owned-set membership: front face, casefolded.

    Double-faced/split cards are keyed on the front face so 'Fire // Ice' in a decklist
    matches an 'owned' entry written as either the full name or just 'Fire'.
    """
    n = (name or "").strip()
    if "//" in n:
        n = n.split("//", 1)[0].strip()
    return n.casefold()


def _find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {(f or "").strip().casefold(): f for f in fieldnames}
    for cand in candidates:
        if cand in lowered:
            return lowered[cand]
    return None


def parse_owned(text: str) -> set[str]:
    """Owned card names (normalized) from a Moxfield-style CSV or a plain decklist."""
    stripped = text.lstrip()
    first_line = stripped.splitlines()[0] if stripped else ""
    if "," in first_line and _find_column(first_line.split(","), _NAME_COLUMNS):
        return _from_csv(text)
    return _from_decklist(text)


def _from_csv(text: str) -> set[str]:
    reader = csv.DictReader(text.splitlines())
    name_col = _find_column(reader.fieldnames or [], _NAME_COLUMNS)
    if name_col is None:
        return set()
    owned: set[str] = set()
    for row in reader:
        name = (row.get(name_col) or "").strip()
        if name:
            owned.add(owned_key(name))
    return owned


def _from_decklist(text: str) -> set[str]:
    """'1 Sol Ring' / 'Sol Ring' / 'Commander: X' lines -> owned names."""
    owned: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        if ":" in line.split(" ", 1)[0]:  # 'Commander:' style header prefix
            line = line.split(":", 1)[1].strip()
        parts = line.split(" ", 1)
        if parts[0].isdigit() and len(parts) > 1:  # leading quantity
            line = parts[1].strip()
        line = line.split("(", 1)[0].strip()  # strip a trailing '(SET) 123' tag
        if line:
            owned.add(owned_key(line))
    return owned


def load_owned_names(path: Path | None = None) -> set[str]:
    """Load the owned-card name set from the collection file. Empty set if absent/unreadable."""
    p = path or suite_collection_path()
    try:
        return parse_owned(p.read_text(encoding="utf-8-sig"))
    except OSError:
        return set()


def owned_count(cards: list[dict], owned: set[str]) -> int:
    """How many of these card dicts (by name) are in the owned set."""
    if not owned:
        return 0
    return sum(1 for c in cards if owned_key(c.get("name", "")) in owned)
