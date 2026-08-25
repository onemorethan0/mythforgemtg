"""Attach card metadata to collection rows, entirely offline.

The collection CSV stores only name/count/set/collector-number, so the browser can filter
by nothing but the name. This module joins each row against two card stores already on
disk — the Scryfall resolve cache and the MythGauntlet slim store — to supply colour,
type, mana value, rarity and EDHREC rank, then provides the facet/filter/sort primitives
the browser needs. No network, ever: browsing a collection is not a reason to hit an API.

    Verified offline coverage: 917/917 distinct names in the live 1040-row collection.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from app_paths import app_path

_MANA_SYM_RE = re.compile(r"\{([^{}]+)\}")

# Mutually exclusive colour buckets, in the order a UI should show them.
COLOR_BUCKETS = ("W", "U", "B", "R", "G", "Multicolor", "Colorless")
RARITY_ORDER  = ("common", "uncommon", "rare", "mythic", "special", "bonus")

# Key used for a row whose printing is unknown. Filtering on it is how a user finds the
# rows that still need "Fill printings".
UNKNOWN_SET = "—"

# What an unresolved row gets, so every enriched row has the same shape.
_EMPTY_META = {
    "mana_cost": "", "cmc": 0, "type_line": "", "type": "Other",
    "colors": [], "color_identity": [], "rarity": None, "set_name": None,
    "edhrec_rank": None, "game_changer": False, "is_land": False, "image": None,
}


def _thumb(card: dict) -> str | None:
    """A small card image URL, front face. Only the Scryfall cache carries these — the
    slim store has no images at all — so a grid tile falls back to /api/card-image."""
    uris = card.get("image_uris") or {}
    if not uris:
        faces = card.get("card_faces") or []
        uris = (faces[0].get("image_uris") or {}) if faces and isinstance(faces[0], dict) else {}
    return uris.get("small") or uris.get("normal") or None


def index_key(name: str) -> str:
    """Front face, casefolded — the join key between a collection row and a card store.

    Mirrors `collection.owned_key`; kept local so this module has no import cycle with
    `collection` (which imports nothing from here).
    """
    n = (name or "").strip()
    if "//" in n:
        n = n.split("//", 1)[0].strip()
    return n.casefold()


def mana_value(mana_cost: str) -> int:
    """Converted mana cost of a `{...}` cost string. Front face only.

    This is MTG-rules-facing, so it is pinned to a table rather than left to taste:

        ""            -> 0     "{W/U}"       -> 1   (hybrid colour/colour)
        "{0}"         -> 0     "{2/W}"       -> 2   (monocolour hybrid = HIGHER half,
        "{3}"         -> 3                           CR 202.3f; retagged 2026-08-24 from
                                                       a stale "202.3b" cite — that letter
                                                       now covers DFC mana value, content
                                                       unchanged, only the letter moved)
        "{10}"        -> 10    "{W/P}"       -> 1   (Phyrexian half is free)
        "{W}"         -> 1     "{X}{R}"      -> 1   (X is 0 outside the stack)
        "{C}"         -> 1     "{X}{X}{G}"   -> 1
        "{2}{W}{U}"   -> 4     "{1}{G} // {G}" -> 2 (MDFC: front face only)
    """
    front = (mana_cost or "").split("//", 1)[0]
    total = 0
    for group in _MANA_SYM_RE.findall(front):
        best = 0
        for part in group.split("/"):
            p = part.strip().upper()
            if p.isdigit():
                val = int(p)
            elif p in ("X", "Y", "Z", "P"):
                val = 0           # X/Y/Z are 0 here; P is the free half of Phyrexian
            elif p in ("W", "U", "B", "R", "G", "C", "S"):
                val = 1
            else:
                val = 0           # unknown symbol: under-count rather than invent mana
            best = max(best, val)
        total += best
    return total


def primary_type(type_line: str) -> str:
    """The single bucket a card browses under. Front face only.

    Precedence is deliberate and load-bearing: an Artifact Creature and an Enchantment
    Creature are Creatures, and an Artifact Land is a Land. Checking Artifact first would
    file half the creatures under Artifact.
    """
    tl = (type_line or "").split("//", 1)[0].lower()
    for kind in ("Land", "Creature", "Planeswalker", "Battle",
                 "Instant", "Sorcery", "Enchantment", "Artifact"):
        if kind.lower() in tl:
            return kind
    return "Other"


def _meta_from(card: dict, name: str, rich: bool) -> dict:
    """Normalize a store record into the meta shape. `rich` marks the Scryfall store,
    which alone carries cmc/rarity/set — the slim store has none of the three."""
    type_line = card.get("type_line") or ""
    kind = primary_type(type_line)
    # Scryfall's cmc is a float (2.0). Keeping it float leaks decimals into curve
    # buckets and JSON, so normalize; fall back to parsing the cost for the slim store.
    cmc = card.get("cmc") if rich else None
    mana_cost = card.get("mana_cost") or ""
    return {
        "name":           card.get("name") or name,
        "mana_cost":      mana_cost,
        "cmc":            int(cmc) if isinstance(cmc, (int, float)) else mana_value(mana_cost),
        "type_line":      type_line,
        "type":           kind,
        "colors":         list(card.get("colors") or []),
        "color_identity": list(card.get("color_identity") or []),
        "rarity":         (card.get("rarity") or None) if rich else None,
        "set":            ((card.get("set") or "").upper() or None) if rich else None,
        "set_name":       (card.get("set_name") or None) if rich else None,
        "edhrec_rank":    card.get("edhrec_rank"),
        "game_changer":   bool(card.get("game_changer")),
        "is_land":        kind == "Land",
        "image":          _thumb(card) if rich else None,
    }


def _read_json(path: Path):
    """Parse a store, or None. A missing store is a degraded mode, not an error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@functools.lru_cache(maxsize=1)
def load_card_index() -> dict[str, dict]:
    """`{index_key(name): meta}` merged from both stores, richest first.

    Cached for the process: the slim store is ~16 MB and re-parsing it per request would
    dominate every collection page load.
    """
    index: dict[str, dict] = {}

    # Slim store first, so the richer Scryfall cache can overwrite it.
    slim = _read_json(app_path("data", "cards_slim.json")) or {}
    for card in (slim.get("cards") if isinstance(slim, dict) else None) or []:
        name = card.get("name") or ""
        if name:
            index[index_key(name)] = _meta_from(card, name, rich=False)

    cache = _read_json(app_path("cache", "scryfall_cards.json")) or {}
    if isinstance(cache, dict):
        for lookup, card in cache.items():
            if not isinstance(card, dict) or not card.get("name"):
                continue
            meta = _meta_from(card, card["name"], rich=True)
            # The cache is keyed by whatever name was looked up, which may be an alias
            # ("Fire" for "Fire // Ice"), so register both.
            index[index_key(card["name"])] = meta
            if lookup:
                index.setdefault(index_key(lookup), meta)
    return index


def enrich_row(row: dict, index: dict) -> dict:
    """A NEW row carrying the card's metadata alongside the collection's own fields."""
    meta = index.get(index_key(row.get("name", "")))
    src = meta or _EMPTY_META
    out = {**{k: src[k] for k in _EMPTY_META}, **row, "resolved": meta is not None}
    # The row's `set` is the ONLY authority on which printing the user owns, and it stays
    # empty when the collection doesn't know. Falling back to the card store's set here
    # would stamp every unknown row with whichever printing happened to be cached —
    # inventing a printing the user may not own, and hiding the rows that genuinely need
    # "Fill printings" behind a confident-looking set code.
    out["set"] = row.get("set") or ""
    # So a set NAME is a label for the row's own printing or it is nothing.
    out["set_name"] = src.get("set_name") if (meta and src.get("set") == out["set"]) else None
    return out


def enrich_rows(rows: list[dict], index: dict | None = None) -> list[dict]:
    """Enrich every row. `index=None` loads (and caches) the merged store."""
    idx = load_card_index() if index is None else index
    return [enrich_row(r, idx) for r in rows]


def color_bucket(colors: list[str]) -> str:
    """The one colour bucket a card belongs to: a letter, Multicolor, or Colorless."""
    distinct = {c for c in (colors or []) if c}
    if not distinct:
        return "Colorless"
    if len(distinct) > 1:
        return "Multicolor"
    return next(iter(distinct))


def facets(rows: list[dict]) -> dict:
    """The filter values actually present, with row counts — so the UI never offers a
    filter that matches nothing."""
    colors: dict[str, int] = {}
    types: dict[str, int] = {}
    rarities: dict[str, int] = {}
    sets: dict[str, int] = {}
    cmc_max = 0
    unresolved = 0

    for row in rows:
        bucket = color_bucket(row.get("colors", []))
        colors[bucket] = colors.get(bucket, 0) + 1
        kind = row.get("type") or "Other"
        types[kind] = types.get(kind, 0) + 1
        rarity = row.get("rarity")
        if rarity:
            rarities[rarity] = rarities.get(rarity, 0) + 1
        code = (row.get("set") or "").upper() or UNKNOWN_SET
        sets[code] = sets.get(code, 0) + 1
        cmc_max = max(cmc_max, int(row.get("cmc") or 0))
        if not row.get("resolved"):
            unresolved += 1

    by_count = lambda d: sorted(({"key": k, "count": v} for k, v in d.items()),
                                key=lambda e: (-e["count"], e["key"]))
    return {
        "colors":   [{"key": b, "count": colors[b]} for b in COLOR_BUCKETS if b in colors],
        "types":    by_count(types),
        "rarities": [{"key": r, "count": rarities[r]} for r in RARITY_ORDER if r in rarities],
        "sets":     by_count(sets),
        "cmc_max":  cmc_max,
        "unresolved": unresolved,
    }


def filter_rows(rows: list[dict], q: str | None = None, colors=None, types=None,
                rarities=None, sets=None, cmc_min: int | None = None,
                cmc_max: int | None = None, min_count: int | None = None) -> list[dict]:
    """Rows matching every supplied criterion. Values within one criterion are ORed;
    an empty or None criterion constrains nothing."""
    ql = (q or "").strip().casefold()
    cset = set(colors or ())
    tset = set(types or ())
    rset = set(rarities or ())
    sset = {str(s).upper() for s in (sets or ())}

    out = []
    for row in rows:
        if ql and ql not in (row.get("name") or "").casefold():
            continue
        if cset and color_bucket(row.get("colors", [])) not in cset:
            continue
        if tset and (row.get("type") or "Other") not in tset:
            continue
        if rset and (row.get("rarity") or "") not in rset:
            continue
        if sset and ((row.get("set") or "").upper() or UNKNOWN_SET) not in sset:
            continue
        cmc = int(row.get("cmc") or 0)
        if cmc_min is not None and cmc < cmc_min:
            continue
        if cmc_max is not None and cmc > cmc_max:
            continue
        if min_count is not None and int(row.get("count") or 0) < min_count:
            continue
        out.append(row)
    return out


def _row_value(row: dict):
    price = row.get("price")
    return None if price is None else price * int(row.get("count") or 0)


# (getter, nullable). A nullable key can be genuinely unknown, which is not the same as
# "worst" — see sort_rows.
_SORTS = {
    "name":   (lambda r: (r.get("name") or "").casefold(), False),
    "count":  (lambda r: int(r.get("count") or 0), False),
    "cmc":    (lambda r: int(r.get("cmc") or 0), False),
    "price":  (lambda r: r.get("price"), True),
    "value":  (_row_value, True),
    "edhrec": (lambda r: r.get("edhrec_rank"), True),
    "type":   (lambda r: r.get("type") or "Other", False),
    "set":    (lambda r: (r.get("set") or ""), False),
}


def sort_rows(rows: list[dict], sort: str = "name", direction: str = "asc") -> list[dict]:
    """A new sorted list. Unknown `sort` falls back to name; name is always the tiebreak.

    Rows with no price / no EDHREC rank sort LAST in BOTH directions — an unknown value
    is not a small one, and flipping to descending should not promote every unpriced card
    to the top of "most valuable".
    """
    getter, nullable = _SORTS.get(sort) or _SORTS["name"]
    desc = direction == "desc"
    # Pre-sort by name so it acts as the tiebreak: Python's sort is stable, and stable
    # holds under reverse=True too (equal elements keep their relative order).
    out = sorted(rows, key=lambda r: (r.get("name") or "").casefold())
    if nullable:
        known = [r for r in out if getter(r) is not None]
        unknown = [r for r in out if getter(r) is None]
        known.sort(key=getter, reverse=desc)
        return known + unknown
    out.sort(key=getter, reverse=desc)
    return out
