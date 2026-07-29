"""Scryfall bulk data: download -> slim local store -> CardDb (docs/DATA_SOURCES.md).

We use the `oracle_cards` bulk file (one printing per unique card, ~35k records) — unlike
MythScanner we don't need every printing. The raw download is slimmed to simulation-relevant
fields and deleted; everything afterwards is offline.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import requests

from mythgauntlet import __version__
from mythgauntlet.config import data_dir
from mythgauntlet.model.card import Card, normalize_name

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
HEADERS = {
    "User-Agent": f"MythGauntlet/{__version__} (github.com/onemorethan0/mythgauntlet)",
    "Accept": "application/json",
}
SKIP_LAYOUTS = {
    "token", "double_faced_token", "emblem", "art_series",
    "vanguard", "scheme", "planar", "augment", "host",
}
SLIM_FILENAME = "cards_slim.json"
SLIM_SCHEMA = 2  # v2: adds game_changer (Scryfall's WotC Game Changers flag)


def slim_path() -> Path:
    return data_dir() / SLIM_FILENAME


def _face_fields(raw: dict) -> dict:
    """Front-face fields for layouts where the top level lacks them (transform, MDFC...)."""
    faces = raw.get("card_faces") or []
    if faces and "oracle_text" not in raw:
        return faces[0]
    return raw


def _slim(raw: dict) -> dict | None:
    if raw.get("layout") in SKIP_LAYOUTS:
        return None
    face = _face_fields(raw)
    return {
        "name": raw.get("name", ""),
        "mana_cost": face.get("mana_cost", raw.get("mana_cost", "")),
        "type_line": face.get("type_line", raw.get("type_line", "")),
        "oracle_text": face.get("oracle_text", ""),
        "colors": face.get("colors", raw.get("colors", [])),
        "color_identity": raw.get("color_identity", []),
        "produced_mana": raw.get("produced_mana", face.get("produced_mana", [])),
        "power": face.get("power"),
        "toughness": face.get("toughness"),
        "edhrec_rank": raw.get("edhrec_rank"),
        "game_changer": bool(raw.get("game_changer", False)),
        "layout": raw.get("layout", "normal"),
        "oracle_id": raw.get("oracle_id", ""),
    }


def fetch_bulk(force: bool = False) -> Path:
    """Download + slim the oracle_cards bulk file. Returns the slim store path."""
    out = slim_path()
    if out.exists() and not force:
        return out

    resp = requests.get(BULK_INDEX_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    index = resp.json()
    entry = next(
        (d for d in index.get("data", []) if d.get("type") == "oracle_cards"), None
    )
    if entry is None or not entry.get("download_uri"):
        raise RuntimeError(
            "Scryfall bulk-data index has no usable 'oracle_cards' entry "
            "(unexpected response or API change)."
        )
    uri = entry["download_uri"]

    raw_path = data_dir() / "oracle_cards.json"
    part = raw_path.with_suffix(".part")
    with requests.get(uri, headers=HEADERS, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(part, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    part.replace(raw_path)

    with open(raw_path, encoding="utf-8") as fh:
        records = json.load(fh)
    slimmed = [s for s in (_slim(r) for r in records) if s is not None]
    tmp = out.with_suffix(".part")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"schema": SLIM_SCHEMA, "cards": slimmed}, fh, ensure_ascii=False)
    tmp.replace(out)
    raw_path.unlink()  # raw file is ~150 MB; the slim store is what we keep
    return out


def _card_from_slim(rec: dict) -> Card:
    return Card(
        name=rec.get("name", ""),
        mana_cost_str=rec.get("mana_cost") or "",
        type_line=rec.get("type_line") or "",
        oracle_text=rec.get("oracle_text") or "",
        colors=tuple(rec.get("colors") or ()),
        color_identity=tuple(rec.get("color_identity") or ()),
        produced_mana=tuple(rec.get("produced_mana") or ()),
        power=rec.get("power"),
        toughness=rec.get("toughness"),
        edhrec_rank=rec.get("edhrec_rank"),
        game_changer=bool(rec.get("game_changer", False)),
        layout=rec.get("layout") or "normal",
        oracle_id=rec.get("oracle_id") or "",
    )


class CardDb:
    """In-memory card index keyed by normalized name (front-face names aliased)."""

    def __init__(self, cards: Iterable[Card]) -> None:
        self._by_name: dict[str, Card] = {}
        for card in cards:
            self._by_name.setdefault(normalize_name(card.name), card)
            if " // " in card.name:
                self._by_name.setdefault(normalize_name(card.front_name), card)

    def get(self, name: str) -> Card | None:
        return self._by_name.get(normalize_name(name))

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def __len__(self) -> int:
        return len({id(c) for c in self._by_name.values()})


_card_db_cache: tuple[str, float, CardDb] | None = None


def load_card_db(path: Path | None = None) -> CardDb:
    """Load the slim store. Raises FileNotFoundError with a hint if fetch-data hasn't run.

    Cached per-process by (path, mtime): a command that builds the CardDb twice, or a
    benchmark looping decks in one process, parses the ~34k-record store only once.
    """
    global _card_db_cache
    store = path or slim_path()
    if not store.exists():
        raise FileNotFoundError(
            f"Card store not found at {store}. Run `mythgauntlet fetch-data` first."
        )
    mtime = store.stat().st_mtime
    if _card_db_cache and _card_db_cache[0] == str(store) and _card_db_cache[1] == mtime:
        return _card_db_cache[2]

    with open(store, encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, list):  # schema v1 (no game_changer flags)
        raise RuntimeError(
            "Card store is an old schema (missing Game Changers flags). "
            "Run `mythgauntlet fetch-data --force` to refresh."
        )
    if payload.get("schema") != SLIM_SCHEMA or "cards" not in payload:
        raise RuntimeError(
            f"Card store schema is {payload.get('schema')}, expected {SLIM_SCHEMA}. "
            "Run `mythgauntlet fetch-data --force` to refresh."
        )
    db = CardDb(_card_from_slim(r) for r in payload["cards"])
    _card_db_cache = (str(store), mtime, db)
    return db
