"""EDHREC community salt store (the "Table feel" axis's data).

EDHREC runs a yearly community survey where Commander players rate how much each card
annoys the table ("salt", 0.0-4.0). MTGJSON republishes it per card as the field
`edhrecSaltiness` in `AtomicCards.json.xz`. This module downloads that file, keeps only
`name -> salt`, writes a small JSON store in the engine's data dir, and loads it. The
engine's "Table feel" axis reads it. The store is OPTIONAL: when it is absent, callers get
`None` and must report the axis as unavailable — never as zero salt.

EDHREC has no bulk API, so MTGJSON is the bulk route: one ~26 MB download, refetched
monthly (EDHREC re-runs the survey about once a year). Measured 2026-10-18: 32,106 of 35,124
MTGJSON entries carry a score, and the median corpus deck has every card measured.

| card        | salt  |
|-------------|-------|
| Stasis      | 3.05  |
| Armageddon  | 2.98  |
| Rhystic Study | 2.82 |
| Cyclonic Rift | 2.35 |
| Sol Ring    | 1.59  |
| Counterspell | 0.96  |
| Llanowar Elves | 0.25 |
| Grizzly Bears | 0.0  |
"""

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

MTGJSON_ATOMIC_URL = "https://mtgjson.com/api/v5/AtomicCards.json.xz"
HEADERS = {"User-Agent": f"MythGauntlet/{__version__} (github.com/onemorethan0/mythgauntlet)"}
SALT_FILENAME = "salt.json"
SALT_SCHEMA = 1
MAX_AGE_DAYS = 30.0   # EDHREC refreshes salt about once a year; monthly is plenty

def salt_path() -> Path:
    """data_dir() / SALT_FILENAME"""
    return data_dir() / SALT_FILENAME

def salt_age_days() -> float | None:
    """Age of the store file in days (from its mtime), or None if it does not exist."""
    path = salt_path()
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    return (time.time() - mtime) / 86400

def extract_salt(atomic: dict) -> dict[str, float]:
    """From the decoded AtomicCards document, map normalize_name(name) -> salt for every
    entry whose first face has a non-None edhrecSaltiness. ALSO add the front-face key
    normalize_name(name.split(" // ")[0]) when that key is not already present (use
    dict.setdefault so a real single-faced card named the same is never overwritten).
    Values are float(...) rounded to 2 decimals. Entries with an empty face list are
    skipped."""
    salt = {}
    for name, faces in atomic["data"].items():
        if not faces:
            continue
        face = faces[0]
        salt_value = face.get("edhrecSaltiness")
        if salt_value is not None:
            normalized_name = normalize_name(name)
            salt[normalized_name] = round(float(salt_value), 2)
            if " // " in name:
                # setdefault: a real single-faced card of the same name keeps its own score
                salt.setdefault(normalize_name(name.split(" // ")[0]), salt[normalized_name])
    return salt

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
    path = salt_path()
    if not force:
        if path.exists():
            age = salt_age_days()
            if age is not None and (max_age_days is None or age <= max_age_days):
                return path
    part_path = data_dir() / "AtomicCards.json.xz.part"
    try:
        response = requests.get(MTGJSON_ATOMIC_URL, headers=HEADERS, stream=True, timeout=300)
        response.raise_for_status()
        with part_path.open("wb") as f:
            for chunk in response.iter_content(1024 * 1024):
                f.write(chunk)
        with lzma.open(part_path, "rt", encoding="utf-8") as f:
            atomic = json.load(f)
        salt_data = extract_salt(atomic)
        store = {
            "schema": SALT_SCHEMA,
            "source": "MTGJSON AtomicCards edhrecSaltiness",
            "mtgjson_date": atomic.get("meta", {}).get("date"),
            "fetched_at": time.strftime("%Y-%m-%d"),
            "cards": salt_data
        }
        temp_path = path.with_suffix(".json.tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False)
        temp_path.replace(path)  # atomic: a reader never sees a half-written store
    finally:
        part_path.unlink(missing_ok=True)
    return path

@dataclass(frozen=True)
class SaltDb:
    cards: dict[str, float]
    mtgjson_date: str | None
    fetched_at: str | None

    def get(self, card: Card) -> float | None:
        """Salt for a card: look up normalize_name(card.name), then
        normalize_name(card.front_name). None when neither is present (UNMEASURED,
        not zero)."""
        name = normalize_name(card.name)
        if name in self.cards:
            return self.cards[name]
        front_name = normalize_name(card.front_name)
        if front_name in self.cards:
            return self.cards[front_name]
        return None

    def __len__(self) -> int:
        return len(self.cards)

_CACHE: dict[tuple[Path, int], SaltDb] = {}

def load_salt(path: Path | None = None) -> SaltDb | None:
    """Load the store, or None when the file does not exist, is not valid JSON, or its
    "schema" != SALT_SCHEMA. Never raises for those cases. Cache by (resolved path,
    st_mtime_ns) in a module-level dict `_CACHE` so repeated calls are free and a refetch
    is picked up."""
    if path is None:
        path = salt_path()
    try:
        key = (path.resolve(), path.stat().st_mtime_ns)
    except OSError:
        return None
    if key in _CACHE:
        return _CACHE[key]
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("schema") != SALT_SCHEMA:
            return None
        salt_db = SaltDb(
            cards=dict(data["cards"]),
            mtgjson_date=data.get("mtgjson_date"),
            fetched_at=data.get("fetched_at")
        )
        _CACHE[key] = salt_db
        return salt_db
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
