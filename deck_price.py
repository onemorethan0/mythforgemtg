"""What a deck is worth, and what it would cost to finish (B20, DEVELOPMENT_PLAN.md).

Moxfield and Archidekt lead every deck page with a price. For a casual pod the useful figure
is the second one: **what you still have to buy** to sleeve this up for real. Pure: the caller
passes the price lookup and the owned test, so this is testable offline and the API decides
where prices come from (the local Scryfall bulk store, refreshed weekly).

Rules, each one a choice made on purpose:
  - Price = Scryfall's `usd` for the card's default printing. A card with no nonfoil price is
    UNPRICED, never valued at its foil or etched price (the collection's D8 rule: a finish
    never borrows another finish's price).
  - Owned cards and basic lands count toward the deck's value but not toward the cost to
    finish it. Ownership is the same test the deck page's badges use.
  - Unpriced cards are counted and named. A total over a partial set is reported as partial,
    never presented as the whole.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional


def _qty(card: dict) -> int:
    try:
        return max(1, int(card.get("quantity", 1) or 1))
    except (TypeError, ValueError):
        return 1


def _usd(scry: Optional[dict]) -> Optional[float]:
    if not scry:
        return None
    raw = (scry.get("prices") or {}).get("usd")
    try:
        return round(float(raw), 2) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def cheapest_lookup(prints_many: Callable[[list[str]], dict[str, list[dict]]],
                    fallback: Optional[Callable[[list[str]], dict[str, dict]]] = None
                    ) -> Callable[[list[str]], dict[str, dict]]:
    """A `price_deck` lookup that prices each card at its CHEAPEST nonfoil English printing.

    Measured on real saved decks: Scryfall's per-name "default" printing (the oracle bulk) is
    often a promo or Secret Lair with no nonfoil price, which left Forest, Evolving Wilds,
    Lotus Petal and Mox Diamond unpriced in ordinary decks. The cheapest printing is also the
    honest answer to "what would this cost me". `prints_many(names)` returns
    {lowercased name: slim printings} (scryfall_prints.prints_of_many); names it knows nothing
    about go to `fallback` (the oracle bulk).
    """
    def lookup(names: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        missing: list[str] = []
        prints = prints_many(list(names)) or {}
        for name in dict.fromkeys(names):
            usds = [p["prices"]["usd"] for p in (prints.get(name.lower().strip()) or [])
                    if (p.get("lang") in (None, "en")) and (p.get("prices") or {}).get("usd")]
            if usds:
                out[name.lower()] = {"prices": {"usd": min(usds)}}
            else:
                missing.append(name)
        if missing and fallback:
            for key, card in (fallback(missing) or {}).items():
                out.setdefault(key, card)
        return out
    return lookup


def price_deck(cards: Iterable[dict],
               lookup: Callable[[list[str]], dict[str, dict]],
               is_owned: Callable[[dict], bool]) -> dict:
    """`cards` are stored deck entries (original_name, quantity, type_line) INCLUDING the
    commander and any partners. `lookup(names)` returns {lowercased name: scryfall card}.
    """
    cards = [c for c in cards if (c.get("original_name") or "").strip()]
    found = lookup([c["original_name"] for c in cards]) or {}
    rows, total, to_buy = [], 0.0, 0.0
    unpriced: list[str] = []
    priced_cards = buy_cards = 0
    for c in cards:
        name = c["original_name"].strip()
        qty = _qty(c)
        usd = _usd(found.get(name.lower()) or found.get(name.split(" // ")[0].lower()))
        owned = bool(is_owned(c))
        rows.append({"name": name, "quantity": qty, "usd": usd, "owned": owned})
        if usd is None:
            unpriced.append(name)
            continue
        priced_cards += qty
        total += usd * qty
        if not owned:
            to_buy += usd * qty
            buy_cards += qty
    rows.sort(key=lambda r: -(r["usd"] or 0) * r["quantity"])
    return {
        "total": round(total, 2),
        "to_buy": round(to_buy, 2),
        "to_buy_cards": buy_cards,
        "priced_cards": priced_cards,
        "unpriced": sorted(set(unpriced)),
        "complete": not unpriced,
        "cards": rows,
    }
