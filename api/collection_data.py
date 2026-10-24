"""Collection reads shared by the deck and collection routes: the owned-card and
owned-printing caches (deck-load annotation) and price-enriched collection rows.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime as _dt
from typing import Optional

import scryfall_prints
from app_paths import app_path
from collection import (
    load_collection,
    load_owned_names,
    owned_key,
    suite_collection_path,
)
from collection import row_id as coll_row_id
from collection_index import enrich_rows, owned_printings_index, pick_owned_printing
from collection_index import index_key as coll_index_key
from scryfall_client import price_key as _price_key

logger = logging.getLogger("server")


# ── Owned-card annotation (served with every deck) ──────────────────────────

# Owned-set cache (mtime-keyed on the collection CSV) so every card->dict call can
# cheaply tag whether the user owns a real copy vs it being a proxy they don't own.
_owned_cache: dict = {"mtime": None, "set": set()}


def _owned_names_cached() -> set:
    p = suite_collection_path()
    mtime = p.stat().st_mtime if p.exists() else 0
    if _owned_cache["mtime"] != mtime:
        _owned_cache.update({"mtime": mtime, "set": load_owned_names()})
    return _owned_cache["set"]


# Owned-printing index (resolved collection rows by card), cached on the same CSV mtime so a
# deck load does not re-enrich the whole collection each time.
_owned_print_cache: dict = {"mtime": None, "index": {}}


def _owned_printings_cached() -> dict:
    p = suite_collection_path()
    try:
        dbp = scryfall_prints.db_path()
        db_mtime = dbp.stat().st_mtime if dbp.exists() else 0
    except Exception:
        db_mtime = 0
    key = (p.stat().st_mtime if p.exists() else 0, db_mtime)   # CSV AND prints store
    if _owned_print_cache["mtime"] != key:
        try:
            _, enriched = _enriched_collection()
            index = owned_printings_index(enriched)
        except Exception:
            # advisory: a deck must still load without printing art -- but do NOT cache the
            # empty result, so the next call retries once the cause is gone.
            logger.warning("owned-printings index failed", exc_info=True)
            return {}
        _owned_print_cache.update({"mtime": key, "index": index})
    return _owned_print_cache["index"]


def _card_is_owned(name: str, type_line: str, owned: set) -> bool:
    """Owned = a real copy you have, OR a basic land (freely available — never a proxy
    you'd need to acquire). Everything else is judged against the collection."""
    tl = (type_line or "").lower()
    if "basic" in tl and "land" in tl:
        return True
    return owned_key(name) in owned


def _annotate_owned(payload: dict) -> dict:
    """Tag the commander + each deck card with `owned` (real copy in the collection vs
    a proxy) at SERVE time — so loaded/old decks get it too, and it reflects live
    collection edits rather than whatever was baked into deck.json at build time."""
    owned = _owned_names_cached()
    printings = None
    for c in ([payload.get("commander")] if isinstance(payload.get("commander"), dict) else []) \
            + (payload.get("deck") or []):
        if isinstance(c, dict) and c.get("original_name"):
            c["owned"] = _card_is_owned(c["original_name"], c.get("type_line", ""), owned)
            # The printing the user really owns (resolved rows only; basics owned by rule and
            # unresolved rows give None -- a stand-in is never shown as theirs).
            if c["owned"]:
                if printings is None:
                    printings = _owned_printings_cached()
                c["owned_printing"] = pick_owned_printing(
                    c, printings.get(coll_index_key(c["original_name"]), []))
            else:
                c.pop("owned_printing", None)
    return payload


# ── Collection manager (edit the canonical MythSuite/collection.csv) ──────────────
# The collection is the Myth Suite handoff file (contract C1): MythScanner writes it,
# Myth Forge + MythGauntlet read it for owned-aware building & advice. These endpoints
# let the user browse/add/edit/remove owned cards from inside Myth Forge; every write
# goes to the SAME canonical CSV (with a .bak) so the whole suite stays in sync.

# Collection prices (Scryfall market USD), cached on disk with a timestamp so a page
# load never blocks on the network. Refreshed explicitly via /api/collection/prices.
_PRICE_CACHE_FILE = app_path("cache", "prices.json")


def _load_prices() -> dict:
    try:
        return json.loads(_PRICE_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"updated": None, "prices": {}}


def _save_prices(prices: dict) -> None:
    try:
        _PRICE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PRICE_CACHE_FILE.write_text(json.dumps(prices), encoding="utf-8")
    except Exception as e:
        print(f"  [prices] save failed: {e}")


def _price_of(row: dict, prices: dict):
    return prices.get(_price_key(row.get("name", ""), row.get("set", ""), row.get("cn", "")))


def _enrich_with_prices(rows: list[dict], pmap: dict) -> list[dict]:
    """Enrich raw rows. `pmap` (cache/prices.json) is only the fallback price for a row whose
    printing did not resolve; a resolved row is priced from its own print and finish."""
    return enrich_rows([{**r, "price": _price_of(r, pmap)} for r in rows])


def _collection_summary(rows: list[dict], prices: dict | None = None,
                        enriched: list[dict] | None = None) -> dict:
    """Totals for the whole collection. `enriched` is the per-row view the browser shows;
    when omitted the raw `rows` are enriched here, so `total_value` always sums the same
    per-row price the browser displays (a foil is never valued at the nonfoil price)."""
    cache = _load_prices() if prices is None else {"prices": prices, "updated": None}
    if enriched is None:
        enriched = _enrich_with_prices(rows, cache.get("prices") or {})
    valued = [(int(r.get("count", 0)), r.get("price")) for r in enriched]
    total_value = sum(cnt * val for cnt, val in valued if val)
    return {
        "distinct":       len(rows),
        "total_cards":    sum(int(r.get("count", 0)) for r in rows),
        "path":           str(suite_collection_path()),
        "exists":         suite_collection_path().exists(),
        # Value of the WHOLE collection (price x count), not just the returned page.
        "total_value":    round(total_value, 2),
        "priced":         sum(1 for _, val in valued if val),
        "prices_updated": _prices_updated(),
    }


def _prints_built_at() -> Optional[str]:
    """ISO-seconds build time of the per-printing store (its db file mtime), or None."""
    try:
        p = scryfall_prints.db_path()
        if p.exists():
            return _dt.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
    except Exception:
        pass
    return None


def _prices_updated() -> Optional[str]:
    """Newer of prices.json's `updated` and the prints-store build time (R18): resolved
    rows are priced from the store, so its build time is when their prices were fresh."""
    stamps = [t for t in (_load_prices().get("updated"), _prints_built_at()) if t]
    return max(stamps) if stamps else None


def _csv_param(value: str) -> list[str]:
    """A comma-separated query param as a list. Blank -> [] (i.e. no constraint)."""
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def _enriched_collection() -> tuple[list[dict], list[dict]]:
    """(raw rows, rows enriched with cached prices + offline card metadata).

    The raw rows are what the summary counts; the enriched copies are what the browser
    filters and sorts. Enrichment is a dict lookup per row against an lru_cached index,
    so this is cheap enough to do per request and always reflects the file on disk.
    """
    rows = load_collection()
    pmap = (_load_prices().get("prices") or {})
    enriched = _enrich_with_prices(rows, pmap)
    # row_id comes from the RAW row's identity (enrichment must not change it).
    for raw, card in zip(rows, enriched):
        card["row_id"] = coll_row_id(raw)
    return rows, enriched
