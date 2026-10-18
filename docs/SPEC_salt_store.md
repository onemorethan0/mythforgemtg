# SPEC: `src/mythgauntlet/data/salt.py` — EDHREC community salt store

/no_think

Output ONLY the complete Python module in one ```python fenced block.

## Purpose
EDHREC runs a yearly community survey where Commander players rate how much each card
annoys the table ("salt", 0.0-4.0). MTGJSON republishes it per card as the field
`edhrecSaltiness` in `AtomicCards.json.xz`. This module downloads that file, keeps only
`name -> salt`, writes a small JSON store in the engine's data dir, and loads it. The
engine's "Table feel" axis reads it. The store is OPTIONAL: when it is absent, callers get
`None` and must report the axis as unavailable — never as zero salt.

## Imports (exactly these, nothing else)
```python
from __future__ import annotations

import json
import lzma
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from mythgauntlet import __version__
from mythgauntlet.config import data_dir
from mythgauntlet.model.card import Card, normalize_name
```
`normalize_name(s)` returns `" ".join(s.casefold().split())`. `Card` has `.name: str`
(may be `"Front // Back"`) and `.front_name: str` (the front face's name).

## Constants
```python
MTGJSON_ATOMIC_URL = "https://mtgjson.com/api/v5/AtomicCards.json.xz"
HEADERS = {"User-Agent": f"MythGauntlet/{__version__} (github.com/onemorethan0/mythgauntlet)"}
SALT_FILENAME = "salt.json"
SALT_SCHEMA = 1
MAX_AGE_DAYS = 30.0   # EDHREC refreshes salt about once a year; monthly is plenty
```

## Input shape (verified live 2026-10-18)
`AtomicCards.json.xz` decompresses to `{"meta": {"date": "2026-10-18", "version": "..."}, "data": {...}}`.
`data` maps a card name (`"Sol Ring"`, `"Fire // Ice"`) to a LIST of face dicts. Salt lives
on the FIRST face: `data[name][0].get("edhrecSaltiness")` — a float, or absent. 32,106 of
35,124 entries carry it.

## Functions (exact signatures)

```python
def salt_path() -> Path:
    """data_dir() / SALT_FILENAME"""

def salt_age_days() -> float | None:
    """Age of the store file in days (from its mtime), or None if it does not exist."""

def extract_salt(atomic: dict) -> dict[str, float]:
    """From the decoded AtomicCards document, map normalize_name(name) -> salt for every
    entry whose first face has a non-None edhrecSaltiness. ALSO add the front-face key
    normalize_name(name.split(" // ")[0]) when that key is not already present (use
    dict.setdefault so a real single-faced card named the same is never overwritten).
    Values are float(...) rounded to 2 decimals. Entries with an empty face list are
    skipped."""

def fetch_salt(force: bool = False, max_age_days: float | None = MAX_AGE_DAYS) -> Path:
    """Download AtomicCards.json.xz, extract salt, write the store. Returns salt_path().
    If the store exists, not force, and (max_age_days is None or age <= max_age_days):
    return it without downloading.
    Download with requests.get(MTGJSON_ATOMIC_URL, headers=HEADERS, stream=True, timeout=300),
    raise_for_status(), write chunks (1 MiB) to data_dir() / "AtomicCards.json.xz.part",
    then decode with lzma.open(part, "rt", encoding="utf-8") + json.load.
    Write the store as JSON (ensure_ascii=False, utf-8) to a temp file
    salt_path().with_suffix(".json.tmp") then Path.replace() it onto salt_path() (atomic).
    Store document: {"schema": SALT_SCHEMA, "source": "MTGJSON AtomicCards edhrecSaltiness",
    "mtgjson_date": atomic.get("meta", {}).get("date"), "fetched_at": time.strftime("%Y-%m-%d"),
    "cards": <extract_salt result>}.
    ALWAYS delete the .part file afterwards, also when decoding fails (try/finally,
    Path.unlink(missing_ok=True))."""

@dataclass(frozen=True)
class SaltDb:
    cards: dict[str, float]
    mtgjson_date: str | None
    fetched_at: str | None

    def get(self, card: Card) -> float | None:
        """Salt for a card: look up normalize_name(card.name), then
        normalize_name(card.front_name). None when neither is present (UNMEASURED,
        not zero)."""

    def __len__(self) -> int: ...

def load_salt(path: Path | None = None) -> SaltDb | None:
    """Load the store, or None when the file does not exist, is not valid JSON, or its
    "schema" != SALT_SCHEMA. Never raises for those cases. Cache by (resolved path,
    st_mtime_ns) in a module-level dict `_CACHE` so repeated calls are free and a refetch
    is picked up."""
```

## Module docstring (required)
Explain: what salt is (EDHREC yearly survey, 0-4), that MTGJSON is the bulk route
(EDHREC has no bulk API), that the store is optional and absence means "unavailable, not
zero", and the cadence (monthly). Include this worked example table:

| card | salt |
|---|---|
| Stasis | 3.05 |
| Armageddon | 2.98 |
| Rhystic Study | 2.82 |
| Cyclonic Rift | 2.35 |
| Sol Ring | 1.59 |
| Counterspell | 0.96 |
| Llanowar Elves | 0.25 |
| Grizzly Bears | 0.0 |
