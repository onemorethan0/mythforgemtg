"""Scryfall printings store: every printing of every card (art / set / collector number).

The main card store (`data/scryfall.py`) uses the `oracle_cards` bulk file -- one printing
per unique card, which is all the *simulation* needs. Art export is different: to let a deck
render a chosen art on EDHPlay we need to know *which printings exist* for each card and pick
one, because EDHPlay identifies a card's art by its (set_code, collector_number) printing
(see docs/EDHPLAY_EXPORT.md). So this module downloads the `default_cards` bulk file (all
printings, best language each, ~140k records), slims it to art-relevant fields and deletes
the raw download; everything afterwards is offline.

This store is *only* consumed by the `edhplay` export path. Nothing in `sim/` or `semantics/`
depends on it -- printings carry no gameplay meaning.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import requests

from mythgauntlet.config import USER_AGENT, data_dir
from mythgauntlet.model.card import normalize_name

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

# Layouts that are never real deck cards (tokens/emblems/etc). Kept in sync in spirit with
# scryfall.SKIP_LAYOUTS, but printings also carry double-faced *cards* we DO want.
SKIP_LAYOUTS = {
    "token", "double_faced_token", "emblem", "art_series",
    "vanguard", "scheme", "planar", "augment", "host",
}

SLIM_FILENAME = "printings_slim.json"
SLIM_SCHEMA = 1


def slim_path() -> Path:
    return data_dir() / SLIM_FILENAME


@dataclass(frozen=True)
class Printing:
    """One physical printing of a card -- what EDHPlay needs to pin an art.

    `set_code` + `collector_number` is the (case-insensitive) key EDHPlay's bulk importer
    resolves to a specific Scryfall printing. Everything else is here so art *policies*
    (newest, borderless, showcase, ...) can rank printings without another Scryfall call.
    """

    name: str
    oracle_id: str
    scryfall_id: str
    set_code: str
    collector_number: str
    set_name: str = ""
    released_at: str = ""
    lang: str = "en"
    rarity: str = ""
    border_color: str = ""
    frame: str = ""
    frame_effects: tuple[str, ...] = ()
    full_art: bool = False
    textless: bool = False
    promo: bool = False
    variation: bool = False
    digital: bool = False
    games: tuple[str, ...] = ()
    image_status: str = ""
    image_uri: str = ""

    @property
    def paper(self) -> bool:
        return "paper" in self.games and not self.digital

    @property
    def has_image(self) -> bool:
        # 'placeholder' / 'missing' render as a grey card box on EDHPlay -- avoid by default.
        return self.image_status in ("highres_scan", "lowres")

    @property
    def borderless(self) -> bool:
        return self.border_color == "borderless"

    @property
    def showcase(self) -> bool:
        return "showcase" in self.frame_effects

    @property
    def extended(self) -> bool:
        return "extendedart" in self.frame_effects

    @property
    def retro(self) -> bool:
        return self.frame in ("1993", "1997")

    def label(self) -> str:
        """Short human tag, e.g. '(dmu) 123 borderless'."""
        tags = []
        if self.borderless:
            tags.append("borderless")
        if self.showcase:
            tags.append("showcase")
        if self.extended:
            tags.append("extended")
        if self.full_art:
            tags.append("full-art")
        if self.textless:
            tags.append("textless")
        if self.retro:
            tags.append("retro")
        suffix = (" " + " ".join(tags)) if tags else ""
        return f"({self.set_code}) {self.collector_number}{suffix}"


def _image_uri(raw: dict) -> str:
    uris = raw.get("image_uris")
    if not uris:
        faces = raw.get("card_faces") or []
        if faces:
            uris = faces[0].get("image_uris")
    if not uris:
        return ""
    return uris.get("normal") or uris.get("large") or uris.get("small") or ""


def _slim(raw: dict) -> dict | None:
    if raw.get("layout") in SKIP_LAYOUTS:
        return None
    set_code = raw.get("set", "")
    cn = raw.get("collector_number", "")
    if not set_code or not cn:
        return None
    return {
        "name": raw.get("name", ""),
        "oracle_id": raw.get("oracle_id", ""),
        "id": raw.get("id", ""),
        "set": set_code,
        "cn": cn,
        "set_name": raw.get("set_name", ""),
        "released_at": raw.get("released_at", ""),
        "lang": raw.get("lang", "en"),
        "rarity": raw.get("rarity", ""),
        "border_color": raw.get("border_color", ""),
        "frame": raw.get("frame", ""),
        "frame_effects": raw.get("frame_effects", []),
        "full_art": bool(raw.get("full_art", False)),
        "textless": bool(raw.get("textless", False)),
        "promo": bool(raw.get("promo", False)),
        "variation": bool(raw.get("variation", False)),
        "digital": bool(raw.get("digital", False)),
        "games": raw.get("games", []),
        "image_status": raw.get("image_status", ""),
        "image_uri": _image_uri(raw),
    }


def fetch_bulk(force: bool = False) -> Path:
    """Download + slim the `default_cards` bulk file. Returns the slim store path.

    ~450 MB raw download, streamed to disk then deleted; the slim store is what we keep.
    """
    out = slim_path()
    if out.exists() and not force:
        return out

    resp = requests.get(BULK_INDEX_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    index = resp.json()
    entry = next(
        (d for d in index.get("data", []) if d.get("type") == "default_cards"), None
    )
    if entry is None or not entry.get("download_uri"):
        raise RuntimeError(
            "Scryfall bulk-data index has no usable 'default_cards' entry "
            "(unexpected response or API change)."
        )
    uri = entry["download_uri"]

    raw_path = data_dir() / "default_cards.json"
    part = raw_path.with_suffix(".part")
    with requests.get(uri, headers=HEADERS, stream=True, timeout=300) as resp:
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
        json.dump({"schema": SLIM_SCHEMA, "printings": slimmed}, fh, ensure_ascii=False)
    tmp.replace(out)
    raw_path.unlink()
    return out


def _printing_from_slim(rec: dict) -> Printing:
    return Printing(
        name=rec.get("name", ""),
        oracle_id=rec.get("oracle_id", ""),
        scryfall_id=rec.get("id", ""),
        set_code=rec.get("set", ""),
        collector_number=rec.get("cn", ""),
        set_name=rec.get("set_name", ""),
        released_at=rec.get("released_at", ""),
        lang=rec.get("lang", "en"),
        rarity=rec.get("rarity", ""),
        border_color=rec.get("border_color", ""),
        frame=rec.get("frame", ""),
        frame_effects=tuple(rec.get("frame_effects") or ()),
        full_art=bool(rec.get("full_art", False)),
        textless=bool(rec.get("textless", False)),
        promo=bool(rec.get("promo", False)),
        variation=bool(rec.get("variation", False)),
        digital=bool(rec.get("digital", False)),
        games=tuple(rec.get("games") or ()),
        image_status=rec.get("image_status", ""),
        image_uri=rec.get("image_uri", ""),
    )


class PrintingDb:
    """All printings, indexed by normalized name (front-face aliased) and by print id.

    `by_name` groups every printing that shares a name; `get_print` resolves an exact
    (set, collector) or a Scryfall print id back to a single Printing.
    """

    def __init__(self, printings: Iterable[Printing]) -> None:
        self._by_name: dict[str, list[Printing]] = {}
        self._by_id: dict[str, Printing] = {}
        self._by_set_cn: dict[tuple[str, str], Printing] = {}
        for p in printings:
            self._by_name.setdefault(normalize_name(p.name), []).append(p)
            if " // " in p.name:
                front = p.name.split(" // ", 1)[0]
                self._by_name.setdefault(normalize_name(front), []).append(p)
            if p.scryfall_id:
                self._by_id[p.scryfall_id] = p
            self._by_set_cn.setdefault(
                (p.set_code.casefold(), p.collector_number.casefold()), p
            )

    def printings(self, name: str) -> list[Printing]:
        return self._by_name.get(normalize_name(name), [])

    def get_print(self, scryfall_id: str) -> Printing | None:
        return self._by_id.get(scryfall_id)

    def get_set_cn(self, set_code: str, collector_number: str) -> Printing | None:
        return self._by_set_cn.get((set_code.casefold(), collector_number.casefold()))

    def __contains__(self, name: str) -> bool:
        return normalize_name(name) in self._by_name

    def __len__(self) -> int:
        return len(self._by_name)


_cache: tuple[str, float, PrintingDb] | None = None


def load_printing_db(path: Path | None = None) -> PrintingDb:
    """Load the slim printings store. Cached per-process by (path, mtime).

    Raises FileNotFoundError with a hint if the store hasn't been fetched.
    """
    global _cache
    store = path or slim_path()
    if not store.exists():
        raise FileNotFoundError(
            f"Printings store not found at {store}. "
            "Run `mythgauntlet edhplay --fetch-printings` (or `edhplay DECK.txt` will "
            "offer to fetch it) to download it."
        )
    mtime = store.stat().st_mtime
    if _cache and _cache[0] == str(store) and _cache[1] == mtime:
        return _cache[2]

    with open(store, encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema") != SLIM_SCHEMA or "printings" not in payload:
        raise RuntimeError(
            f"Printings store schema is {payload.get('schema')}, expected {SLIM_SCHEMA}. "
            "Run `mythgauntlet edhplay --fetch-printings --force` to refresh."
        )
    db = PrintingDb(_printing_from_slim(r) for r in payload["printings"])
    _cache = (str(store), mtime, db)
    return db
