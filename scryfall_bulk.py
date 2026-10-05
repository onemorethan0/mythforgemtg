"""Local, offline card store built from Scryfall's daily `oracle_cards` bulk file.

Name lookups (imports, collection hydration, commander resolution, strict collection builds)
need no API call once the store exists; `scryfall_client.ScryfallClient` consults it first
and falls back to the live API for a miss (a card newer than the store, a fuzzy typo).
`otag:` searches can NOT come from here -- the bulk files carry no oracle tags.

Drafted by qwen3:14b from a spec and reviewed; the review fixed constants the draft renamed
but still referenced (an import-time NameError), unlocked queries on a shared connection,
a refresh that swallowed every error, and a download into a directory that may not exist.

Worked examples:

| call | result |
|---|---|
| `_keys({"name": "Sol Ring"})` | `["sol ring"]` |
| `_keys({"name": "Fire // Ice"})` | `["fire // ice", "fire", "ice"]` |
| `_keys({"name": "Delver of Secrets // Insectile Aberration"})` | `["delver of secrets // insectile aberration", "delver of secrets", "insectile aberration"]` |
| a record with layout `"token"` | not stored |
| `lookup("SOL RING ")` after a build containing Sol Ring | the Sol Ring card dict |
| `lookup_many(["sol ring", "nope"])` | `{"sol ring": {...}}` |
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Iterable, Iterator, Optional

import requests

from app_paths import app_path

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
HEADERS = {"User-Agent": "MythForge/1.0 (personal project)", "Accept": "application/json"}
MAX_AGE_DAYS = 7.0
SKIP_LAYOUTS = frozenset({"token", "double_faced_token", "emblem", "art_series", "vanguard",
                          "scheme", "planar", "reversible_card"})
DROP_FIELDS = frozenset({"all_parts", "purchase_uris", "related_uris", "multiverse_ids",
                         "mtgo_id", "mtgo_foil_id", "arena_id", "tcgplayer_id",
                         "tcgplayer_etched_id", "cardmarket_id", "uri", "scryfall_uri",
                         "rulings_uri", "prints_search_uri", "preview"})

_LOCK = threading.RLock()   # re-entrant: queries hold it around _conn()
_CONN: Optional[sqlite3.Connection] = None
_CONN_MTIME: Optional[float] = None

def enabled() -> bool:
    return os.environ.get("MYTHFORGE_SCRYFALL_BULK", "").lower() != "off"

def db_path() -> Path:
    return app_path("cache", "scryfall_bulk.sqlite")

def age_days() -> Optional[float]:
    path = db_path()
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    return (time.time() - mtime) / 86400.0

def _keys(card: dict) -> list[str]:
    name = card.get("name", "")
    if not name:
        return []
    keys = [name.lower().strip()]
    if " // " in name:
        parts = name.split(" // ")
        keys.extend(part.lower().strip() for part in parts)
    return list(dict.fromkeys(keys))  # deduplicate while preserving order

def _read_records(path: Path, jsonl: bool) -> Iterator[dict]:
    if jsonl:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)
        else:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)
    else:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    yield item

def _face_priority(card: dict) -> tuple:
    """Which card owns a FACE name two cards share. "Fire" is a face of both Fire // Ice and
    Start // Fire (not Commander-legal); first-in-file used to win and handed back the wrong
    card, where Scryfall's own exact lookup returns Fire // Ice. Commander-legal first, then
    the more-played card (lower EDHREC rank)."""
    legal = (card.get("legalities") or {}).get("commander") == "legal"
    rank = card.get("edhrec_rank")
    return (0 if legal else 1, rank if isinstance(rank, int) else 10**9)


def _encode(card: dict) -> bytes:
    # zlib per row: the JSON compresses ~4x, and the store stays small enough to live in cache/
    return zlib.compress(json.dumps(card, ensure_ascii=False).encode("utf-8"), 6)


def _decode(blob) -> dict:
    return json.loads(zlib.decompress(blob).decode("utf-8"))


def _build_db(records: Iterable[dict], out: Path) -> int:
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(out))
    conn.execute("CREATE TABLE cards (key TEXT PRIMARY KEY, card BLOB NOT NULL)")
    conn.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    count = 0
    faces: dict[str, tuple[tuple, bytes]] = {}
    for record in records:
        if not record.get("name") or record.get("layout") in SKIP_LAYOUTS:
            continue
        stripped = {k: v for k, v in record.items() if k not in DROP_FIELDS}
        blob = _encode(stripped)
        full, *face_keys = _keys(stripped)
        # A card's FULL name always wins its key; face names are resolved after, by priority.
        conn.execute("INSERT OR REPLACE INTO cards VALUES (?, ?)", (full, blob))
        prio = _face_priority(stripped)
        for key in face_keys:
            if key not in faces or prio < faces[key][0]:
                faces[key] = (prio, blob)
        count += 1
    for key, (_prio, blob) in faces.items():
        conn.execute("INSERT OR IGNORE INTO cards VALUES (?, ?)", (key, blob))
    conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)", ("fetched_at", str(time.time())))
    conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)", ("count", str(count)))
    conn.commit()
    conn.close()
    return count


def refresh(force: bool = False, max_age_days: Optional[float] = MAX_AGE_DAYS) -> Optional[Path]:
    """Download + index `oracle_cards` when the store is missing, older than `max_age_days`
    (None = accept any existing store), or `force`. Raises on failure; never replaces a good
    store with an empty one."""
    path = db_path()
    if not force and path.exists():
        age = age_days()
        if max_age_days is None or (age is not None and age <= max_age_days):
            return path
    path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(BULK_INDEX_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    entry = next((e for e in response.json().get("data", []) if e.get("type") == "oracle_cards"), None)
    if entry is None:
        raise RuntimeError("Scryfall bulk-data index has no 'oracle_cards' entry")
    uri = entry.get("jsonl_download_uri") or entry.get("download_uri")
    if not uri:
        raise RuntimeError(f"'oracle_cards' entry has no download uri (fields: {sorted(entry)})")
    jsonl = uri.endswith((".jsonl", ".jsonl.gz"))
    download_path = path.with_name("oracle_cards.download" + (".gz" if uri.endswith(".gz") else ""))
    part_path = path.with_suffix(".sqlite.part")
    try:
        with requests.get(uri, headers=HEADERS, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with open(download_path, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
        count = _build_db(_read_records(download_path, jsonl), part_path)
    finally:
        download_path.unlink(missing_ok=True)
    if count == 0:
        part_path.unlink(missing_ok=True)
        raise RuntimeError("Scryfall bulk download yielded 0 cards; keeping the existing store")
    with _LOCK:   # no reader may reopen the old file between close and replace (Windows)
        _close()
        part_path.replace(path)
    return path


def refresh_async() -> None:
    if not enabled():
        return
    def run() -> None:
        try:
            refresh()
        except Exception as exc:   # noqa: BLE001 -- a background refresh must never crash the app
            print(f"  [scryfall-bulk] refresh failed: {exc}")
    threading.Thread(target=run, name="scryfall-bulk", daemon=True).start()

def lookup(name: str) -> Optional[dict]:
    if not enabled() or not name:
        return None
    key = name.lower().strip()
    if not key:
        return None
    with _LOCK:
        conn = _conn()
        if conn is None:
            return None
        row = conn.execute("SELECT card FROM cards WHERE key = ?", (key,)).fetchone()
    return _decode(row[0]) if row else None

def lookup_many(names: Iterable[str]) -> dict[str, dict]:
    if not enabled():
        return {}
    keys = list(dict.fromkeys(k for k in (str(n or "").lower().strip() for n in names) if k))
    if not keys:
        return {}
    result: dict[str, dict] = {}
    with _LOCK:
        conn = _conn()
        if conn is None:
            return {}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            rows = conn.execute(
                "SELECT key, card FROM cards WHERE key IN (" + ",".join("?" * len(chunk)) + ")",
                chunk).fetchall()
            for key, card in rows:
                result[key] = _decode(card)
    return result

def _conn() -> Optional[sqlite3.Connection]:
    global _CONN, _CONN_MTIME
    with _LOCK:
        path = db_path()
        if not path.exists():
            if _CONN:
                _CONN.close()
                _CONN = None
                _CONN_MTIME = None
            return None
        mtime = path.stat().st_mtime
        if _CONN and _CONN_MTIME == mtime:
            return _CONN
        if _CONN:
            _CONN.close()
        _CONN = sqlite3.connect(str(path), check_same_thread=False)
        _CONN_MTIME = mtime
        return _CONN

def _close() -> None:
    global _CONN, _CONN_MTIME
    with _LOCK:
        if _CONN:
            _CONN.close()
            _CONN = None
            _CONN_MTIME = None
