"""Collection manager routes (/api/collection/*) and card image/lookup.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime as _dt
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import collection_repair as coll_repair
import scryfall_prints
from api.collection_data import (
    _collection_summary,
    _csv_param,
    _enriched_collection,
    _save_prices,
)
from api.state import _scryfall
from collection import _merge_row as _coll_merge_row
from collection import add_card as coll_add_card
from collection import bulk_apply as coll_bulk_apply
from collection import bulk_import as coll_bulk_import
from collection import find_by_id as coll_find_by_id
from collection import (
    load_collection,
    load_owned_names,
    owned_key,
    suite_collection_path,
)
from collection import normalize_finish as coll_normalize_finish
from collection import remove_by_id as coll_remove_by_id
from collection import remove_card as coll_remove_card
from collection import row_id as coll_row_id
from collection import set_count as coll_set_count
from collection import set_count_by_id as coll_set_count_by_id
from collection import set_printing as coll_set_printing
from collection import set_printing_by_id as coll_set_printing_by_id
from collection import write_collection as coll_write
from collection_index import GROUP_BYS, filter_rows, group_rows, sort_rows
from collection_index import facets as coll_facets
from collection_index import print_price as coll_print_price
from collection_index import treatments_of as coll_treatments_of
from collection_stats import collection_stats

logger = logging.getLogger("server")
router = APIRouter()


@router.get("/api/collection")
def get_collection(q: str = "", offset: int = 0, limit: int = 200,
                   colors: str = "", types: str = "", rarities: str = "", sets: str = "",
                   cmc_min: Optional[int] = None, cmc_max: Optional[int] = None,
                   min_count: Optional[int] = None, color_presence: str = "",
                   game_changers_only: bool = False,
                   sort: str = "name", direction: str = "asc",
                   then: str = "", then_direction: str = "asc", group: str = "none",
                   finishes: str = "", treatments: str = "", languages: str = "",
                   multi_printing: bool = False):
    """Owned cards, enriched with offline card metadata, filtered, sorted and paginated.

    The CSV stores only name/count/set/collector-number, so colour, type, mana value and
    rarity are joined in from the local card stores — no network. `colors`/`types`/
    `rarities`/`sets` are comma-separated; values within one are ORed, the criteria are
    ANDed. limit<=0 returns all matches (still capped at 5000 for safety).

    `color_presence` is `colors`' complement, not a duplicate: `colors=W` matches only
    mono-white rows (the CollectionStats "Colors" bar's exclusive bucket), while
    `color_presence=W` also matches a Boros card — "does this card have a white pip at
    all", the question CollectionStats' `color_presence` breakdown answers. See
    `collection_index.filter_rows`.
    """
    rows, enriched = _enriched_collection()
    matched = filter_rows(enriched, q=q, colors=_csv_param(colors), types=_csv_param(types),
                          rarities=_csv_param(rarities), sets=_csv_param(sets),
                          cmc_min=cmc_min, cmc_max=cmc_max, min_count=min_count,
                          color_presence=_csv_param(color_presence),
                          game_changers_only=game_changers_only,
                          finishes=_csv_param(finishes), treatments=_csv_param(treatments),
                          languages=_csv_param(languages), multi_printing=multi_printing)
    ordered = sort_rows(matched, sort, direction, then=then or None,
                        then_direction=then_direction)
    # Group the WHOLE filtered set, then paginate: the subtotals must not depend on where
    # a page (or the 5000 cap) cuts. An unknown `group` is "none".
    ordered, groups = group_rows(ordered, group if group in GROUP_BYS else "none")
    lim = 5000 if limit is None or limit <= 0 else min(limit, 5000)
    page = ordered[max(offset, 0): max(offset, 0) + lim]
    # Facets come from the WHOLE collection, not the filtered slice, so narrowing a
    # filter can never strand the user with no way back.
    return {"cards": page, "matched": len(matched), "groups": groups,
            "facets": coll_facets(enriched),
            **_collection_summary(rows, enriched=enriched)}


@router.get("/api/collection/stats")
def collection_stats_view(top_n: int = 10):
    """Value, colour spread, mana curve, type/rarity/set breakdown, most valuable cards."""
    _rows, enriched = _enriched_collection()
    return collection_stats(enriched, top_n=max(1, min(int(top_n), 50)))


@router.get("/api/collection/health")
def collection_health(limit: int = 300):
    """Rows whose NAME is really a whole decklist line, and what repairing them would do.

    Read-only: these are PROPOSALS. An older import parser stored lines like
    "13x Island (msh) 290 [Land]" verbatim as card names, and such a name matches nothing
    — so those cards are invisible to owned-aware building until they are repaired.
    """
    diag = coll_repair.diagnose(load_collection())
    shown = max(1, int(limit))
    return {**diag, "issues": diag["issues"][:shown],
            "shown": min(shown, diag["affected"]),
            "truncated": diag["affected"] > shown}


class CollectionRepairRequest(BaseModel):
    # Defaults to a dry run on purpose: this rewrites the canonical suite collection.
    dry_run: bool = True
    indexes: Optional[list[int]] = None   # issue indexes to accept; None = all of them


@router.post("/api/collection/repair")
def collection_repair_apply(req: CollectionRepairRequest):
    """Apply the repairs from /health. `dry_run` reports what WOULD change and writes
    nothing; a real run rewrites the CSV (leaving a .bak that /undo can restore)."""
    rows = load_collection()
    accept = set(req.indexes) if req.indexes is not None else None
    new_rows, report = coll_repair.apply_repairs(rows, accept)
    if not req.dry_run:
        coll_write(new_rows)
        rows = new_rows
    return {"dry_run": req.dry_run, **report, **_collection_summary(rows)}


@router.post("/api/collection/undo")
def collection_undo():
    """Restore the previous collection from the .bak every write leaves behind."""
    p = suite_collection_path()
    bak = p.with_suffix(p.suffix + ".bak")
    if not bak.exists():
        raise HTTPException(404, "No previous version to restore.")
    try:
        current, restored = (p.read_bytes() if p.exists() else b""), bak.read_bytes()
        # SWAP rather than overwrite, so Undo is itself undoable — press it twice and
        # you are back where you started. A plain restore would leave the .bak equal to
        # what we just wrote, stranding the newer version with no way to reach it.
        tmp = p.with_name(f".{p.name}.undo")
        tmp.write_bytes(restored)
        os.replace(tmp, p)          # atomic on the same volume, like write_collection
        bak.write_bytes(current)
    except OSError as e:
        logger.error("collection undo failed", exc_info=e)
        raise HTTPException(500, "Restore failed.")
    return {"restored": True, **_collection_summary(load_collection())}


_STALE_ROW = "Collection changed — reload."


class CollectionTarget(BaseModel):
    row_id: Optional[str] = None      # exact row (D6); wins over name/set/cn when present
    name: str = ""
    set:  str = ""
    cn:   str = ""


class CollectionBulkRequest(BaseModel):
    action:  str                      # "remove" | "set_count"
    targets: list[CollectionTarget]
    count:   int = 0                  # for set_count; <=0 removes


@router.post("/api/collection/bulk")
def collection_bulk(req: CollectionBulkRequest):
    """One action over many printings in a SINGLE write.

    Doing this a row at a time would rewrite the whole CSV per row and refresh the .bak
    each time — which quietly destroys Undo, since after the second write the backup is
    itself already-modified.
    """
    if req.action not in ("remove", "set_count"):
        raise HTTPException(400, "action must be 'remove' or 'set_count'.")
    if not req.targets:
        raise HTTPException(400, "No cards selected.")
    try:
        rows, affected = coll_bulk_apply([t.model_dump() for t in req.targets],
                                         req.action, int(req.count))
    except KeyError:
        raise HTTPException(409, _STALE_ROW)
    return {"affected": affected, "action": req.action, **_collection_summary(rows)}


class CollectionPrintingRequest(BaseModel):
    name:     str = ""
    set_code: str = ""
    cn:       str = ""
    from_set: Optional[str] = None    # which row to move; None = the first printing
    from_cn:  Optional[str] = None
    row_id:      Optional[str] = None  # exact row (D6); 409 when it no longer exists
    finish:      Optional[str] = None  # nonfoil | foil | etched; None keeps the row's finish
    scryfall_id: Optional[str] = None  # the chosen print; resolves set + cn from the store


def _print_for(name: str, set_code: str = "", cn: str = "", scryfall_id: str = "") -> dict | None:
    """The store's print for an id (authoritative, D2) or set + cn; None when the store
    is disabled/missing or has no such print."""
    if (scryfall_id or "").strip():
        hit = scryfall_prints.by_id(scryfall_id.strip())
        if hit:
            return hit
    return scryfall_prints.resolve(name, set_code, cn)


def _require_finish(print_: dict | None, finish: str) -> None:
    """400 when the store knows the print and it does not come in `finish`. A store that
    cannot answer cannot veto (the live fallback carries no finish data)."""
    finishes = (print_ or {}).get("finishes") or []
    if print_ and finishes and finish not in finishes:
        raise HTTPException(400, f"That printing is not available in {finish}.")


@router.patch("/api/collection/printing")
def collection_set_printing(req: CollectionPrintingRequest):
    """Point a row at a different printing (and finish) of the same card, keeping its count.

    This is how the rows whose printing is unknown get a real one without the user
    deleting and re-adding the card (which would lose the count). Merges into the target
    printing when the collection already holds it. With `row_id` the row is addressed
    exactly (409 when stale) and `finish` must be one the chosen print offers (400)."""
    rid = (req.row_id or "").strip()
    if rid:
        src = coll_find_by_id(load_collection(), rid)
        if src is None:
            raise HTTPException(409, _STALE_ROW)
        sid = (req.scryfall_id or "").strip()
        set_code = (req.set_code or "").strip().upper()
        cn = (req.cn or "").strip()
        name = (req.name or "").strip() or src["name"]
        if req.finish is not None:
            finish = coll_normalize_finish(req.finish)
        else:
            finish = coll_normalize_finish(src.get("finish", ""))
        if not sid and (set_code, cn) == ((src.get("set") or "").strip().upper(),
                                          (src.get("cn") or "").strip()):
            sid = (src.get("scryfall_id") or "").strip()   # finish-only change keeps the id
        print_ = _print_for(name, set_code, cn, sid)
        if print_:
            if owned_key(print_.get("name", "")) != owned_key(src["name"]):
                raise HTTPException(400, "That scryfall_id belongs to a different card.")
            set_code, cn, sid = print_["set"], print_["cn"], print_.get("id") or sid
        if not set_code:
            raise HTTPException(400, "A set code or scryfall_id is required.")
        _require_finish(print_, finish)
        try:
            rows = coll_set_printing_by_id(rid, set_code, cn, finish, sid)
        except KeyError:
            raise HTTPException(409, _STALE_ROW)
        return {"cards": rows[:200], **_collection_summary(rows)}
    if not (req.name or "").strip():
        raise HTTPException(400, "Card name is required.")
    if not (req.set_code or "").strip():
        raise HTTPException(400, "A set code is required.")
    rows = coll_set_printing(req.name.strip(), req.set_code, req.cn,
                             from_set=(req.from_set or None), from_cn=(req.from_cn or None))
    return {"cards": rows[:200], **_collection_summary(rows)}


@router.post("/api/collection/prices")
def collection_refresh_prices():
    """Refresh market prices for the whole collection from Scryfall and cache them.

    Batched 75 identifiers per request, so a ~750-card collection is ~10 calls. Rows
    with a known printing are priced as that printing; the rest by name."""
    rows = load_collection()
    if not rows:
        return {"priced": 0, "total_value": 0.0, **_collection_summary(rows)}
    try:
        prices = _scryfall.fetch_prices(rows)
    except Exception as e:
        logger.error("collection price refresh failed", exc_info=e)
        raise HTTPException(503, "Price lookup failed.")
    _save_prices({"updated": _dt.now().isoformat(timespec="seconds"), "prices": prices})
    # Resolved rows are priced from the per-printing store, so rebuild it too (R18). A failure
    # here must not undo the prices.json refresh above.
    try:
        scryfall_prints.refresh(force=True)
    except Exception as e:
        logger.error("prints store refresh failed during price refresh", exc_info=e)
    return _collection_summary(rows)


class CollectionAddRequest(BaseModel):
    name:     str
    count:    int = 1
    # Wire name stays "validate"; the attribute is renamed because it shadowed
    # BaseModel.validate and printed a warning on every server start.
    model_config = {"populate_by_name": True}
    validate_name: bool = Field(True, alias="validate")   # resolve the canonical Scryfall name first
    set_code: Optional[str] = None   # which printing; None -> default to the cheapest
    cn:       Optional[str] = None   # collector number (disambiguates within a set)
    finish:   str = "nonfoil"        # nonfoil | foil | etched (part of the row identity, D3)
    scryfall_id: Optional[str] = None  # the exact print; set + cn come from the store when it has it


def _cheapest_print(name: str, finish: str = "nonfoil", prints: list | None = None) -> tuple[str, str, str] | None:
    """(set, cn, scryfall_id) of the cheapest printing of `name` that offers `finish` and
    prices it (D8: another finish's price is never borrowed). Offline first; the live API
    only when the prints store knows nothing about the card. None when nothing is found."""
    if prints is None:
        prints = scryfall_prints.prints_of(name)
    if prints:
        best = None
        for p in prints:
            if finish not in (p.get("finishes") or []):
                continue
            price = coll_print_price(p, finish)
            if price is not None and (best is None or price < best[0]):
                best = (price, p)
        return (best[1]["set"], best[1]["cn"], best[1].get("id") or "") if best else None
    try:
        cheap = _scryfall.cheapest_printing(name)
    except Exception:
        cheap = None
    return (cheap["set"], cheap["collector_number"], "") if cheap else None


@router.post("/api/collection/add")
def collection_add(req: CollectionAddRequest):
    """Add copies of a card. When validate=True the name is resolved against Scryfall
    (fuzzy) so the stored spelling matches how decklists reference it; an unresolvable
    name is a 404 so the UI can warn instead of silently storing a typo."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Card name is required.")
    display = name
    if req.validate_name:
        # Exact match first so a correctly-typed name is never fuzzed into a
        # different card (fuzzy turned "sol rng" into "Oathsworn Giant"); only fall
        # back to fuzzy when the exact spelling isn't found.
        card = None
        try:
            card = _scryfall.get_card_by_name(name, fuzzy=False)
        except Exception:
            card = None
        if not card or not card.get("name"):
            try:
                card = _scryfall.get_card_by_name(name, fuzzy=True)
            except Exception:
                card = None
        if not card or not card.get("name"):
            raise HTTPException(404, f"No card found matching '{name}'. Add it with validate=false to store as-is.")
        display = card["name"]

    finish = coll_normalize_finish(req.finish)
    sid = (req.scryfall_id or "").strip()
    set_code, cn = (req.set_code or "").strip().upper() or None, (req.cn or "").strip() or None
    # An id names the print exactly (D2): the store fills set + cn. With no store, what the
    # caller gave is stored as provided.
    print_ = _print_for(display, set_code or "", cn or "", sid) if (sid or set_code) else None
    if print_ and sid:
        if owned_key(print_.get("name", "")) != owned_key(display):
            raise HTTPException(400, "That scryfall_id belongs to a different card.")
        set_code, cn, sid = print_["set"], print_["cn"], print_.get("id") or sid
    _require_finish(print_, finish)
    # Printing: use what the caller gave us, else default to the CHEAPEST printing (of this
    # finish) so a collection entry always names a concrete, sensibly-priced version.
    if not set_code and not sid:     # an id the store doesn't know is stored exactly as given
        cheap = _cheapest_print(display, finish)
        if cheap:
            set_code, cn, sid = cheap[0], cheap[1], (cheap[2] or sid)
    rows = coll_add_card(name, max(int(req.count), 1), display_name=display,
                         set_code=set_code, cn=cn, finish=finish, scryfall_id=sid)
    return {"cards": rows[:200], "resolved_name": display, "set_code": set_code, "cn": cn,
            "finish": finish, "scryfall_id": sid, **_collection_summary(rows)}


def _owned_on_print(print_: dict, rows: list[dict], n_in_set: int) -> list[dict]:
    """The collection rows that ARE this printing: by scryfall id when the row has one (the
    id wins over a contradicting set, D2), else set + cn; a row with a set but no cn counts
    only when that set holds exactly one printing of the card."""
    out = []
    for r in rows:
        rsid = (r.get("scryfall_id") or "").strip().lower()
        if rsid:
            hit = rsid == str(print_.get("id") or "").lower()
        else:
            rset = (r.get("set") or "").strip().upper()
            rcn = (r.get("cn") or "").strip().casefold()
            if not rset or rset != print_.get("set"):
                hit = False
            elif rcn:
                hit = rcn == str(print_.get("cn") or "").casefold()
            else:
                hit = n_in_set == 1
        if hit:
            out.append({"row_id": coll_row_id(r), "finish": coll_normalize_finish(r.get("finish", "")),
                        "count": int(r.get("count", 0))})
    return out


def _usd_alias(prices: dict):
    """R12 `usd`: the nonfoil price, else the foil price, else None."""
    v = prices.get("nonfoil")
    return v if v is not None else prices.get("foil")


@router.get("/api/collection/printings")
def collection_printings(name: str):
    """Every printing of a card, newest first, for the printing picker. Offline from the
    prints store; the live Scryfall search only when the store has nothing. Each item
    carries `owned`: the collection rows sitting on that exact printing."""
    nm = (name or "").strip()
    if not nm:
        raise HTTPException(400, "name required")
    key = owned_key(nm)
    rows = [r for r in load_collection() if owned_key(r["name"]) == key]
    prints = scryfall_prints.prints_of(nm)
    if prints:
        per_set: dict[str, int] = {}
        for p in prints:
            per_set[p["set"]] = per_set.get(p["set"], 0) + 1
        items = []
        for p in prints:
            imgs = p.get("images") or {}
            prices_by_finish = {f: coll_print_price(p, f) for f in ("nonfoil", "foil", "etched")}
            items.append({
                "id": p.get("id"), "set": p["set"], "set_name": p.get("set_name"), "cn": p["cn"],
                "released_at": p.get("released_at"), "rarity": p.get("rarity"),
                "finishes": list(p.get("finishes") or []),
                "prices": prices_by_finish,
                "treatments": coll_treatments_of(p, "nonfoil"),
                "image": imgs.get("normal") or imgs.get("small") or "",
                "art_crop": imgs.get("art_crop") or "",
                "collector_number": p["cn"],      # R12: back-compat aliases for the old modal
                "usd": _usd_alias(prices_by_finish),
                "owned": _owned_on_print(p, rows, per_set[p["set"]]),
            })
        return {"printings": items}
    try:
        live = _scryfall.get_printings(nm)
    except Exception as e:
        logger.error("collection printings lookup failed for %r", nm, exc_info=e)
        raise HTTPException(503, "Scryfall lookup failed.")
    items = []
    for p in live[:60]:
        shim = {"id": None, "set": p.get("set", ""), "cn": p.get("collector_number", "")}
        items.append({
            "id": None, "set": shim["set"], "set_name": p.get("set_name") or None, "cn": shim["cn"],
            "released_at": None, "rarity": None, "finishes": [],
            "prices": {"nonfoil": p.get("usd"), "foil": None, "etched": None},
            "treatments": [], "image": p.get("image") or "", "art_crop": "",
            "collector_number": shim["cn"], "usd": p.get("usd"),
            "owned": _owned_on_print(shim, rows, 2),    # 2: a set-only row cannot be matched blind
        })
    return {"printings": items}


@router.get("/api/card-image")
def card_image(name: str):
    """Resolve a card NAME to its Scryfall image URLs (for hover previews).

    Exact-first then fuzzy, via the cached ScryfallClient. Handles double-faced cards
    (image_uris live on the front face). Returns {name, normal, art_crop} or 404."""
    nm = (name or "").strip()
    if not nm:
        raise HTTPException(400, "name required")
    card = None
    try:
        card = _scryfall.get_card_by_name(nm, fuzzy=False) or _scryfall.get_card_by_name(nm, fuzzy=True)
    except Exception:
        card = None
    if not card:
        raise HTTPException(404, f"no card matching '{nm}'")
    imgs = card.get("image_uris") or {}
    if not imgs:
        faces = card.get("card_faces") or []
        if faces and isinstance(faces[0], dict):
            imgs = faces[0].get("image_uris") or {}
    return {
        "name": card.get("name", nm),
        "normal": imgs.get("normal") or imgs.get("large") or imgs.get("small") or "",
        "art_crop": imgs.get("art_crop") or "",
    }


@router.get("/api/card-lookup")
def card_lookup(name: str):
    """Full card data by NAME, shaped for the Single Card form.

    Lets a user proxy a REAL card: look it up, prefill every field with the real
    printed values (rules text verbatim), then generate new art for it. Exact-first
    then fuzzy (guarded), so a near-miss resolves but a typo doesn't silently become
    a different card."""
    nm = (name or "").strip()
    if not nm:
        raise HTTPException(400, "name required")
    card = None
    try:
        card = _scryfall.get_card_by_name(nm, fuzzy=False) or _scryfall.get_card_by_name(nm, fuzzy=True)
    except Exception:
        card = None
    if not card:
        raise HTTPException(404, f"No card found matching '{nm}'")
    imgs = card.get("image_uris") or {}
    if not imgs:
        faces = card.get("card_faces") or []
        if faces and isinstance(faces[0], dict):
            imgs = faces[0].get("image_uris") or {}
    return {
        "name":        card.get("name", nm),
        "mana_cost":   card.get("mana_cost", "") or "",
        "type_line":   card.get("type_line", "") or "",
        "oracle_text": card.get("oracle_text", "") or "",
        "flavor_text": card.get("flavor_text", "") or "",
        "power":       card.get("power") or "",
        "toughness":   card.get("toughness") or "",
        "loyalty":     card.get("loyalty") or "",
        "rarity":      card.get("rarity", "") or "",
        "colors":      card.get("color_identity", []) or [],
        "image":       imgs.get("normal") or imgs.get("large") or "",
    }


@router.get("/api/collection/suggest")
def collection_suggest(q: str = ""):
    """Card-name typeahead for the add box (Scryfall autocomplete). Returns up to
    ~20 canonical names; empty list on short/blank query or any upstream hiccup."""
    ql = (q or "").strip()
    if len(ql) < 2:
        return {"suggestions": []}
    try:
        # Use the ScryfallClient's session — Scryfall rejects requests without a
        # proper User-Agent/Accept header (a bare requests.get returns nothing).
        r = _scryfall.session.get("https://api.scryfall.com/cards/autocomplete",
                                  params={"q": ql}, timeout=5)
        if r.status_code == 200:
            return {"suggestions": (r.json().get("data") or [])[:20]}
    except Exception:
        pass
    return {"suggestions": []}


class CollectionCountRequest(BaseModel):
    name:  str = ""
    count: int
    row_id:   Optional[str] = None   # exact row (D6); name is then not needed
    set_code: Optional[str] = None   # target one printing; None = first printing
    cn:       Optional[str] = None


@router.patch("/api/collection/count")
def collection_set_count(req: CollectionCountRequest):
    """Set a card's exact count (0 removes it). With row_id, targets exactly that row (409
    when it no longer exists); else with set_code, targets that printing."""
    if (req.row_id or "").strip():
        try:
            rows = coll_set_count_by_id(req.row_id.strip(), int(req.count))
        except KeyError:
            raise HTTPException(409, _STALE_ROW)
        return {"cards": rows[:200], **_collection_summary(rows)}
    if not (req.name or "").strip():
        raise HTTPException(400, "Card name is required.")
    rows = coll_set_count(req.name.strip(), int(req.count),
                          set_code=(req.set_code or None), cn=(req.cn or None))
    return {"cards": rows[:200], **_collection_summary(rows)}


@router.post("/api/collection/backfill-printings")
def collection_backfill_printings(limit: int = 1000):
    """Fill in printings without ever replacing one. Offline from the prints store.

    - A row with a scryfall_id or a set already NAMES its printing: it is only normalized
      (a blank set / collector number filled from that print), never replaced.
    - A row with no printing data at all gets the cheapest printing that offers its finish
      (D8: priced in that finish). The live API is used only for a card the store does not
      know. One write for the whole pass; rows that become identical merge (counts sum)."""
    rows = load_collection()
    filled = failed = normalized = 0
    cheapest: dict = {}
    prints_cache: dict = {}          # prints_of once per distinct name, across finishes
    seen = 0
    for r in rows:
        sid = (r.get("scryfall_id") or "").strip()
        rset = (r.get("set") or "").strip()
        rcn = (r.get("cn") or "").strip()
        if sid or rset:
            if sid and rset and rcn:
                continue
            p = _print_for(r["name"], rset, rcn, sid)
            if not p:
                continue
            changed = False
            if not rset:
                r["set"], changed = p["set"], True
            if not rcn and r["set"].strip().upper() == p["set"]:
                r["cn"], changed = p["cn"], True
            if changed:
                normalized += 1
            continue
        if seen >= max(1, int(limit)):
            continue
        seen += 1
        fin = coll_normalize_finish(r.get("finish", ""))
        ck = (owned_key(r["name"]), fin)
        if ck not in cheapest:
            nk = ck[0]
            if nk not in prints_cache:
                prints_cache[nk] = scryfall_prints.prints_of(r["name"])
            cheapest[ck] = _cheapest_print(r["name"], fin, prints_cache[nk])
        cheap = cheapest[ck]
        if cheap:
            r["set"], r["cn"] = cheap[0], cheap[1]
            if cheap[2]:
                r["scryfall_id"] = cheap[2]
            filled += 1
        else:
            failed += 1
    if filled or normalized:
        merged: list[dict] = []
        exact: dict = {}
        for r in rows:                      # a changed row may now equal another (D4)
            _coll_merge_row(merged, exact, None, r)
        rows = merged
        coll_write(rows)
    remaining = sum(1 for r in rows
                    if not (r.get("set") or "").strip() and not (r.get("scryfall_id") or "").strip())
    return {"filled": filled, "failed": failed, "normalized": normalized, "remaining": remaining,
            **_collection_summary(rows)}


@router.delete("/api/collection")
def collection_remove(name: str = "", set_code: str | None = None, cn: str | None = None,
                      row_id: str | None = None):
    """Remove a card entirely (matched on front-face name, case-insensitive).

    The name is a QUERY param, not a path segment: double-faced/split card names
    contain '//', and an encoded slash in the path 405s under Starlette routing.

    `row_id` removes exactly that row (409 when it no longer exists) and needs no name."""
    if (row_id or "").strip():
        try:
            rows = coll_remove_by_id(row_id.strip())
        except KeyError:
            raise HTTPException(409, _STALE_ROW)
        return {"cards": rows[:200], **_collection_summary(rows)}
    if not (name or "").strip():
        raise HTTPException(400, "Card name is required.")
    rows = coll_remove_card(name, set_code=(set_code or None), cn=(cn or None))
    return {"cards": rows[:200], **_collection_summary(rows)}


class CollectionImportRequest(BaseModel):
    text: str
    mode: str = "merge"   # "merge" adds onto the current collection; "replace" overwrites


@router.post("/api/collection/import")
def collection_import(req: CollectionImportRequest):
    """Bulk-import a pasted Moxfield CSV or a plain decklist. No Scryfall validation
    (imports can be large); names are stored as written and normalized on read."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "Nothing to import.")
    mode = "replace" if req.mode == "replace" else "merge"
    rows = coll_bulk_import(text, mode=mode)
    return {"cards": rows[:200], "imported_mode": mode, **_collection_summary(rows)}


# Cache the buildable scan keyed on the collection file's mtime, so repeat views are
# instant and any edit (which rewrites the CSV) transparently invalidates it.
_buildable_cache: dict = {"key": None, "data": None}


@router.get("/api/collection/buildable")
def collection_buildable(limit: int = 8):
    """Which commanders you own could you build a B1-3 deck from, ranked by how
    complete each deck would be. Fast local scan (no simulation); 'Build this' then
    goes through the normal generate flow where the deck can be measured."""
    import buildable
    p = suite_collection_path()
    mtime = p.stat().st_mtime if p.exists() else 0
    key = (mtime, int(limit))
    if _buildable_cache["key"] == key and _buildable_cache["data"] is not None:
        return {**_buildable_cache["data"], "cached": True}
    owned = load_owned_names()
    try:
        data = buildable.find_buildable(owned, _scryfall, limit=int(limit))
    except Exception as e:
        logger.error("buildable collection scan failed", exc_info=e)
        raise HTTPException(503, "Could not scan the collection (Scryfall).")
    _buildable_cache.update({"key": key, "data": data})
    return {**data, "cached": False}
