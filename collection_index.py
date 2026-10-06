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
# Print-level fields enrich_row adds on top (see its body): print_resolved, image_normal,
# art_crop, back_image, released_at, artist, finishes, treatments, image_representative,
# price, date_added.


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


def print_price(print_: dict, finish: str) -> float | None:
    """The price of `finish` on this printing, or None. D8: a finish with no price is
    None and NEVER borrows another finish's price — a foil valued at the nonfoil price
    is a confident wrong number."""
    key = {"foil": "usd_foil", "etched": "usd_etched"}.get(finish or "nonfoil", "usd")
    val = ((print_ or {}).get("prices") or {}).get(key)
    return float(val) if isinstance(val, (int, float)) else None


def treatments_of(print_: dict, finish: str) -> list[str]:
    """The visual treatments a printing carries, derived exactly from Scryfall's fields."""
    effects = print_.get("frame_effects") or []
    out = []
    if print_.get("border_color") == "borderless":
        out.append("borderless")
    if "showcase" in effects:
        out.append("showcase")
    if "extendedart" in effects:
        out.append("extended")
    if print_.get("full_art"):
        out.append("full_art")
    if print_.get("frame") in ("1993", "1997"):
        out.append("retro")
    if print_.get("promo"):
        out.append("promo")
    if finish == "etched":
        out.append("etched")
    return out


def _default_resolve_print(row: dict) -> dict | None:
    import scryfall_prints
    return scryfall_prints.resolve(row.get("name", ""), row.get("set", ""), row.get("cn", ""),
                                   row.get("scryfall_id", ""))


def enrich_row(row: dict, index: dict, resolve_print=None) -> dict:
    """A NEW row carrying the card's metadata alongside the collection's own fields.

    `resolve_print(row) -> print | None` finds the exact printing the row names; it
    defaults to the offline prints store and is injected in tests. A store that is missing,
    disabled or raising degrades to the oracle-level view, with the art marked
    representative."""
    meta = index.get(index_key(row.get("name", "")))
    src = meta or _EMPTY_META
    out = {**{k: src[k] for k in _EMPTY_META if k in src}, **row, "resolved": meta is not None}
    # The row's `set` is the ONLY authority on which printing the user owns, and it stays
    # empty when the collection doesn't know. Falling back to the card store's set here
    # would stamp every unknown row with whichever printing happened to be cached —
    # inventing a printing the user may not own, and hiding the rows that genuinely need
    # "Fill printings" behind a confident-looking set code. Only a RESOLVED print (by
    # Scryfall id, set + number, or the one printing a set holds) may fill a blank set/cn.
    out["set"] = row.get("set") or ""
    # So a set NAME is a label for the row's own printing or it is nothing.
    out["set_name"] = src.get("set_name") if (meta and src.get("set") == out["set"]) else None

    try:
        pr = (resolve_print or _default_resolve_print)(row)
    except Exception:
        pr = None
    finish = row.get("finish") or "nonfoil"
    out["print_resolved"] = pr is not None
    out["printing_mismatch"] = False
    oracle_image = out.get("image")
    out.update(image_normal=None, art_crop=None, back_image=None, released_at=None, artist=None,
               finishes=[], treatments=[], image_representative=True)
    if pr:
        # D2 / R10: a Scryfall id is authoritative. When the row resolved through its id
        # and the print's set or cn contradicts the row's non-blank ones, the PRINT wins
        # (the art, price and rarity below are that print's) and the row is flagged. The
        # CSV is never modified.
        by_id = bool(row.get("scryfall_id")) and pr.get("id") == row.get("scryfall_id")
        pset, pcn = pr.get("set") or "", str(pr.get("cn") or "")
        if by_id and ((out["set"] and out["set"].upper() != pset.upper())
                      or (out.get("cn") and str(out["cn"]).strip().lower() != pcn.lower())):
            out["printing_mismatch"] = True
            out["set"], out["cn"] = pset, pcn
        else:
            if not out["set"]:
                out["set"] = pset
            if not out.get("cn"):
                out["cn"] = pcn
        out["set_name"] = pr.get("set_name") if pset.upper() == out["set"].upper() else None
        out["rarity"] = pr.get("rarity") or out.get("rarity")
        out["released_at"] = pr.get("released_at")
        out["artist"] = pr.get("artist")
        out["finishes"] = list(pr.get("finishes") or [])
        out["treatments"] = treatments_of(pr, finish)
        imgs = pr.get("images")
        if imgs:
            out["image"] = imgs.get("small") or imgs.get("normal")
            out["image_normal"] = imgs.get("normal")
            out["art_crop"] = imgs.get("art_crop")
            out["image_representative"] = False
        back = pr.get("back_images")
        if back:
            out["back_image"] = back.get("normal") or back.get("small")
        out["price"] = print_price(pr, finish)      # D8: no fallback to another finish
    else:
        out["image"] = oracle_image
        # unresolved rows only: the finish-blind prices.json value the caller attached
        out["price"] = row.get("price")
    extra = row.get("_extra") or {}
    out["date_added"] = extra.get("Date Added") or None
    return out


def enrich_rows(rows: list[dict], index: dict | None = None, resolve_print=None) -> list[dict]:
    """Enrich every row. `index=None` loads (and caches) the merged store.

    A print is resolved once per distinct (scryfall_id, set, cn, name) per call: a
    collection holds many copies of the same printing in different finishes."""
    idx = load_card_index() if index is None else index
    fn = resolve_print or _default_resolve_print
    memo: dict[tuple, dict | None] = {}

    def cached(row: dict):
        key = (row.get("scryfall_id") or "", (row.get("set") or "").upper(),
               str(row.get("cn") or ""), index_key(row.get("name", "")))
        if key not in memo:
            memo[key] = fn(row)
        return memo[key]

    return [enrich_row(r, idx, resolve_print=cached) for r in rows]


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
                cmc_max: int | None = None, min_count: int | None = None,
                color_presence=None, game_changers_only: bool = False) -> list[dict]:
    """Rows matching every supplied criterion. Values within one criterion are ORed;
    an empty or None criterion constrains nothing.

    `colors` and `color_presence` ask two DIFFERENT questions about the same field and are
    deliberately separate params, matching `collection_stats.py`'s own colors/color_presence
    split: `colors` is the row's single EXCLUSIVE bucket (a Boros card is "Multicolor", not
    "W" or "R"), so it answers "show me my mono-white cards". `color_presence` asks "does
    this card have a white pip at all" — a Boros card matches "W" here, because a player
    asking "how much white do I actually have access to" needs their multicolor cards
    counted too, not hidden behind a bucket that only ever shows ONE colour per card.
    """
    ql = (q or "").strip().casefold()
    cset = set(colors or ())
    pset = set(color_presence or ())
    tset = set(types or ())
    rset = set(rarities or ())
    sset = {str(s).upper() for s in (sets or ())}

    out = []
    for row in rows:
        if ql and ql not in (row.get("name") or "").casefold():
            continue
        if cset and color_bucket(row.get("colors", [])) not in cset:
            continue
        if pset and not (set(row.get("color_identity") or ()) & pset):
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
        if game_changers_only and not row.get("game_changer"):
            continue
        out.append(row)
    return out


def _row_value(row: dict):
    price = row.get("price")
    return None if price is None else price * int(row.get("count") or 0)


FINISH_ORDER = ("nonfoil", "foil", "etched")
_WUBRG = ("W", "U", "B", "R", "G")
_CN_RE = re.compile(r"^(\d+)(.*)$")


def _index_of(order: tuple, value, default=None):
    try:
        return order.index(value)
    except ValueError:
        return default


def _color_key(row: dict):
    colors = {c for c in (row.get("colors") or ()) if c}
    return (COLOR_BUCKETS.index(color_bucket(list(colors))),
            tuple(sorted(_index_of(_WUBRG, c, 9) for c in colors)))


def _collector_key(row: dict):
    """Natural collector-number order inside a set: 2 < 10 < 10a < ★1 (no leading digits
    sorts after every numbered card; a blank number after that)."""
    cn = str(row.get("cn") or "").strip().casefold()
    m = _CN_RE.match(cn)
    if m:
        return ((row.get("set") or "").upper(), 0, int(m.group(1)), m.group(2))
    return ((row.get("set") or "").upper(), 1 if cn else 2, 0, cn)


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
    "rarity": (lambda r: _index_of(RARITY_ORDER, r.get("rarity")), True),
    "color":  (_color_key, False),
    "released": (lambda r: r.get("released_at") or None, True),
    "collector": (_collector_key, False),
    "added":  (lambda r: r.get("date_added") or None, True),
    "finish": (lambda r: _index_of(FINISH_ORDER, r.get("finish") or "nonfoil", 0), False),
}


def _stable_sort(rows: list[dict], key: str, direction: str) -> list[dict]:
    """One level of sort over rows already in tiebreak order. A nullable key partitions
    known from unknown, so unknown lands last whichever way the known ones run."""
    getter, nullable = _SORTS[key]
    desc = direction == "desc"
    if nullable:
        known = [r for r in rows if getter(r) is not None]
        unknown = [r for r in rows if getter(r) is None]
        known.sort(key=getter, reverse=desc)
        return known + unknown
    return sorted(rows, key=getter, reverse=desc)


def sort_rows(rows: list[dict], sort: str = "name", direction: str = "asc",
              then: str | None = None, then_direction: str = "asc") -> list[dict]:
    """A new sorted list. Unknown `sort` falls back to name; an unknown `then` is ignored;
    name is always the final tiebreak.

    Rows with no price / no EDHREC rank / no rarity sort LAST in BOTH directions — an
    unknown value is not a small one, and flipping to descending should not promote every
    unpriced card to the top of "most valuable". That holds at the secondary level too.

    Implemented as chained stable sorts, least significant first: name, then the
    secondary, then the primary. Python's sort is stable under reverse=True as well.
    """
    key = sort if sort in _SORTS else "name"
    out = sorted(rows, key=lambda r: (r.get("name") or "").casefold())
    if then in _SORTS:
        out = _stable_sort(out, then, then_direction)
    return _stable_sort(out, key, direction)


GROUP_BYS = ("none", "type", "color", "cmc", "rarity", "set", "finish", "card")
TYPE_GROUP_ORDER = ("Creature", "Planeswalker", "Battle", "Instant", "Sorcery",
                    "Artifact", "Enchantment", "Land", "Other")


def group_of(row: dict, by: str) -> tuple:
    """`(order_key, key, label)` for the group this row belongs to under `by`.

    `order_key` sorts groups among themselves. For "set" it is `(rank, date)` and is
    resolved by `group_rows` (newest first needs a descending date, unknown last); for
    "card" it is the card key and groups keep first-appearance order instead."""
    if by == "type":
        kind = row.get("type") or "Other"
        if kind not in TYPE_GROUP_ORDER:
            kind = "Other"
        return (TYPE_GROUP_ORDER.index(kind), kind, kind)
    if by == "color":
        bucket = color_bucket(row.get("colors", []))
        return (COLOR_BUCKETS.index(bucket), bucket, bucket)
    if by == "cmc":
        if row.get("is_land") or row.get("type") == "Land":
            return (8, "lands", "Lands")      # never under 0
        cmc = int(row.get("cmc") or 0)
        return (7, "7+", "7+") if cmc >= 7 else (cmc, str(cmc), str(cmc))
    if by == "rarity":
        rar = row.get("rarity")
        idx = _index_of(RARITY_ORDER, rar)
        return (idx, rar, rar) if idx is not None else (len(RARITY_ORDER), "unknown", "Unknown")
    if by == "set":
        code = (row.get("set") or "").upper()
        if not code:
            return ((1, ""), UNKNOWN_SET, UNKNOWN_SET)
        name = row.get("set_name")
        return ((0, row.get("released_at") or ""), code, f"{name} ({code})" if name else code)
    if by == "finish":
        fin = row.get("finish") or "nonfoil"
        return (_index_of(FINISH_ORDER, fin, 0), fin, fin)
    if by == "card":
        key = index_key(row.get("name", ""))
        return (key, key, row.get("name") or "")
    raise ValueError(by)


def group_rows(rows: list[dict], by: str) -> tuple[list[dict], list[dict]]:
    """`(ordered_rows, groups)` for rows that are ALREADY sorted.

    Rows are ordered by group and stay in their given order inside each group; each
    returned row is a copy carrying `group` (the group key). `groups` is
    `[{key, label, rows, cards, value, printings?}]`: `rows` distinct rows, `cards` the
    summed count, `value` the price x count of PRICED rows only (an unpriced row adds
    nothing rather than a fabricated zero-priced guess), and `printings` for "card".
    An unknown or "none" `by` returns the rows untouched and no groups.

    Callers group the WHOLE filtered set before paginating, so these totals never depend
    on where a page happens to cut.
    """
    if by not in GROUP_BYS or by == "none":
        return list(rows), []

    buckets: dict[str, dict] = {}
    for r in rows:
        order, key, label = group_of(r, by)
        g = buckets.get(key)
        if g is None:
            g = buckets[key] = {"order": order, "key": key, "label": label, "members": [],
                                "rows": 0, "cards": 0, "value": 0.0, "_dates": []}
        if by == "set" and order[1]:
            g["_dates"].append(order[1])
        g["members"].append({**r, "group": key})
        g["rows"] += 1
        count = int(r.get("count") or 0)
        g["cards"] += count
        if r.get("price") is not None:
            g["value"] += r["price"] * count

    groups = list(buckets.values())              # insertion order == first appearance
    if by == "set":
        # known sets newest first, undated known sets after the dated ones, unknown last
        groups.sort(key=lambda g: g["key"])
        groups.sort(key=lambda g: max(g["_dates"], default=""), reverse=True)
        groups.sort(key=lambda g: g["key"] == UNKNOWN_SET)
    elif by != "card":
        groups.sort(key=lambda g: g["order"])

    ordered: list[dict] = []
    out_groups: list[dict] = []
    for g in groups:
        ordered.extend(g["members"])
        entry = {"key": g["key"], "label": g["label"], "rows": g["rows"],
                 "cards": g["cards"], "value": round(g["value"], 2)}
        if by == "card":
            entry["printings"] = g["rows"]
        out_groups.append(entry)
    return ordered, out_groups
