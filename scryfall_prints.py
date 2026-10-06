"""Local, offline per-PRINTING store built from Scryfall's `default_cards` bulk file.

`scryfall_bulk` keeps one record per card NAME (oracle_cards). The collection views need one
record per PRINTING (set, collector number, finishes, prices, art), so a row's exact printing
can be shown and valued without an API call. Same lifecycle as `scryfall_bulk`: SQLite under
`cache/`, refreshed in a background thread when older than a week, kill switch
`MYTHFORGE_SCRYFALL_PRINTS=off`. Digital-only prints and tokens/emblems/art cards are dropped.

Worked examples:

| call | result |
|---|---|
| `slim_print({... "set": "c21", "collector_number": "263", "digital": False ...})["set"]` | `"C21"` |
| `slim_print({..., "digital": True})` | `None` |
| `slim_print(<transform card>)["back_images"]` | `{"small":..., "normal":..., "art_crop":...}` |
| `slim_print(<split/adventure card>)["back_images"]` | `None` |
| `resolve("Sol Ring", scryfall_id="id-c21")` | that exact print |
| `resolve("Sol Ring", "cmr", "472")` | the CMR #472 print |
| `resolve("Sol Ring", "C21")` | the C21 print, only if C21 holds exactly one Sol Ring |
| `resolve("Forest", "C21")` | `None` (several Forests in C21: ambiguous) |
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

import requests

from app_paths import app_path
from scryfall_bulk import (BULK_INDEX_URL, HEADERS, SKIP_LAYOUTS, _decode, _encode, _keys,
                           _read_records)

MAX_AGE_DAYS = 7.0
_IMAGE_KEYS = ("small", "normal", "art_crop")

_LOCK = threading.RLock()   # re-entrant: queries hold it around _conn()
_CONN: Optional[sqlite3.Connection] = None
_CONN_KEY: Optional[tuple] = None   # (path, mtime): a different file or a rebuild reopens


def enabled() -> bool:
    return os.environ.get("MYTHFORGE_SCRYFALL_PRINTS", "").lower() != "off"


def db_path() -> Path:
    return app_path("cache", "scryfall_prints.sqlite")


def age_days() -> Optional[float]:
    path = db_path()
    if not path.exists():
        return None
    return (time.time() - path.stat().st_mtime) / 86400.0


def _price(value) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _images(uris) -> Optional[dict]:
    if not isinstance(uris, dict):
        return None
    out = {k: uris.get(k) for k in _IMAGE_KEYS}
    return out if any(out.values()) else None


def slim_print(card: dict) -> Optional[dict]:
    """Reduce a Scryfall card record to the fields the collection views read."""
    if not card or card.get("digital") or card.get("layout") in SKIP_LAYOUTS:
        return None
    faces = card.get("card_faces") or []
    images = _images(card.get("image_uris"))
    back = None
    if images is None:
        # transform / MDFC: the images live on the faces, front first
        if faces:
            images = _images((faces[0] or {}).get("image_uris"))
        if len(faces) > 1:
            back = _images((faces[1] or {}).get("image_uris"))
    prices = card.get("prices") or {}
    return {
        "id": card.get("id"),
        "oracle_id": card.get("oracle_id"),
        "name": card.get("name"),
        "set": str(card.get("set") or "").upper(),
        "set_name": card.get("set_name"),
        "cn": str(card.get("collector_number") or ""),
        "rarity": card.get("rarity"),
        "released_at": card.get("released_at"),
        "lang": card.get("lang"),
        "finishes": list(card.get("finishes") or []),
        "frame": card.get("frame"),
        "frame_effects": list(card.get("frame_effects") or []),
        "full_art": bool(card.get("full_art")),
        "promo": bool(card.get("promo")),
        "promo_types": list(card.get("promo_types") or []),
        "border_color": card.get("border_color"),
        "artist": card.get("artist"),
        "layout": card.get("layout"),
        "prices": {k: _price(prices.get(k)) for k in ("usd", "usd_foil", "usd_etched")},
        "images": images,
        "back_images": back,
    }


def _build_db(records: Iterable[dict], out: Path) -> int:
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(out))
    try:
        conn.execute("CREATE TABLE prints (id TEXT PRIMARY KEY, name_key TEXT, set_code TEXT, "
                     "cn TEXT, released_at TEXT, card BLOB NOT NULL)")
        conn.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
        count = 0
        for record in records:
            slim = slim_print(record)
            if not slim or not slim["id"] or not slim["name"]:
                continue
            conn.execute("INSERT OR REPLACE INTO prints VALUES (?, ?, ?, ?, ?, ?)",
                         (slim["id"], _keys(slim)[0], slim["set"], slim["cn"].lower(),
                          slim["released_at"] or "", _encode(slim)))
            count += 1
        conn.execute("CREATE INDEX idx_prints_set_cn ON prints (set_code, cn)")
        conn.execute("CREATE INDEX idx_prints_name ON prints (name_key)")
        conn.execute("INSERT INTO meta VALUES ('fetched_at', ?)", (str(time.time()),))
        conn.execute("INSERT INTO meta VALUES ('count', ?)", (str(count),))
        conn.commit()
    except BaseException:
        conn.close()
        out.unlink(missing_ok=True)
        raise
    conn.close()
    return count


def refresh(force: bool = False, max_age_days: Optional[float] = MAX_AGE_DAYS) -> Optional[Path]:
    """Download + index `default_cards` when the store is missing, older than `max_age_days`
    (None = accept any existing store), or `force`. Raises on failure; a failed build leaves
    the existing store untouched and no stray download or .part file."""
    path = db_path()
    if not force and path.exists():
        age = age_days()
        if max_age_days is None or (age is not None and age <= max_age_days):
            return path
    path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(BULK_INDEX_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    entry = next((e for e in response.json().get("data", []) if e.get("type") == "default_cards"), None)
    if entry is None:
        raise RuntimeError("Scryfall bulk-data index has no 'default_cards' entry")
    uri = entry.get("jsonl_download_uri") or entry.get("download_uri")
    if not uri:
        raise RuntimeError(f"'default_cards' entry has no download uri (fields: {sorted(entry)})")
    jsonl = uri.endswith((".jsonl", ".jsonl.gz"))
    download_path = path.with_name("default_cards.download" + (".gz" if uri.endswith(".gz") else ""))
    part_path = path.with_suffix(".sqlite.part")
    try:
        with requests.get(uri, headers=HEADERS, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with open(download_path, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
        count = _build_db(_read_records(download_path, jsonl), part_path)
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise
    finally:
        download_path.unlink(missing_ok=True)
    if count == 0:
        part_path.unlink(missing_ok=True)
        raise RuntimeError("Scryfall default_cards yielded 0 prints; keeping the existing store")
    with _LOCK:   # no reader may reopen the old file between close and replace (Windows)
        _close()
        os.replace(part_path, path)
    return path


def refresh_async() -> None:
    if not enabled():
        return

    def run() -> None:
        try:
            refresh()
        except Exception as exc:   # noqa: BLE001 -- a background refresh must never crash the app
            print(f"  [scryfall-prints] refresh failed: {exc}")
    threading.Thread(target=run, name="scryfall-prints", daemon=True).start()


def _conn() -> Optional[sqlite3.Connection]:
    global _CONN, _CONN_KEY
    with _LOCK:
        path = db_path()
        if not path.exists():
            if _CONN:
                _CONN.close()
                _CONN = None
                _CONN_KEY = None
            return None
        key = (str(path), path.stat().st_mtime)
        if _CONN and _CONN_KEY == key:
            return _CONN
        if _CONN:
            _CONN.close()
        _CONN = sqlite3.connect(str(path), check_same_thread=False)
        _CONN_KEY = key
        return _CONN


def _close() -> None:
    global _CONN, _CONN_KEY
    with _LOCK:
        if _CONN:
            _CONN.close()
            _CONN = None
            _CONN_KEY = None


def _query(sql: str, params: tuple) -> list[dict]:
    if not enabled():
        return []
    with _LOCK:
        conn = _conn()
        if conn is None:
            return []
        rows = conn.execute(sql, params).fetchall()
    return [_decode(r[0]) for r in rows]


def _name_clause(name: str) -> tuple[str, tuple]:
    """Exact full-name match, or the front face of a '//' card (collections store front faces)."""
    key = (name or "").lower().strip()
    esc = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "(name_key = ? OR name_key LIKE ? ESCAPE '\\')", (key, esc + " // %")


def by_id(sid: str) -> Optional[dict]:
    if not sid:
        return None
    rows = _query("SELECT card FROM prints WHERE id = ?", (str(sid).strip().lower(),))
    return rows[0] if rows else None


def by_set_cn(set_code: str, cn: str) -> Optional[dict]:
    if not set_code or not cn:
        return None
    rows = _query("SELECT card FROM prints WHERE set_code = ? AND cn = ?",
                  (set_code.strip().upper(), str(cn).strip().lower()))
    return rows[0] if rows else None


def prints_of(name: str) -> list[dict]:
    if not name or not name.strip():
        return []
    clause, params = _name_clause(name)
    return _query(f"SELECT card FROM prints WHERE {clause} "
                  "ORDER BY released_at DESC, set_code, cn", params)


def resolve(name: str, set_code: str = "", cn: str = "", scryfall_id: str = "") -> Optional[dict]:
    """The printing a collection row names. Id first, then set + collector number, then the
    set alone only when that set holds exactly ONE printing of the name (several Forests in
    one set are ambiguous, and a guess would be a confident wrong printing)."""
    if not enabled():
        return None
    if scryfall_id:
        hit = by_id(scryfall_id)
        if hit:
            return hit
    set_code = (set_code or "").strip().upper()
    if not set_code or not name or not name.strip():
        return None
    clause, params = _name_clause(name)
    if cn and str(cn).strip():
        rows = _query(f"SELECT card FROM prints WHERE set_code = ? AND cn = ? AND {clause}",
                      (set_code, str(cn).strip().lower()) + params)
        if rows:
            return rows[0]
    rows = _query(f"SELECT card FROM prints WHERE set_code = ? AND {clause}", (set_code,) + params)
    return rows[0] if len(rows) == 1 else None
