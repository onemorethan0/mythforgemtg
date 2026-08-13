"""Aggregate an enriched collection into the numbers a "what do I own" panel shows.

Pure aggregation over the output of `collection_index.enrich_rows` — no file I/O, no
network, no mutation of the input.

    "distinct" counts rows (printings owned); "copies" sums their counts. The mana
    curve excludes lands. `colors` buckets are mutually exclusive and sum to the
    total; `color_presence` overlaps, because a Boros card is both white and red.
"""

from __future__ import annotations

import collections

from collection_index import color_bucket

_COLOR_LABELS = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green",
                 "Multicolor": "Multicolor", "Colorless": "Colorless"}
_COLOR_ORDER    = ("W", "U", "B", "R", "G", "Multicolor", "Colorless")
_PRESENCE_ORDER = ("W", "U", "B", "R", "G")
_RARITY_ORDER   = ("common", "uncommon", "rare", "mythic", "special", "bonus")

CURVE_TOP = 7          # everything at this mana value or above shares the "7+" bucket
MAX_SETS  = 15
UNKNOWN_SET = "—"      # the row's printing is unknown, not a set called "—"


def row_value(row: dict) -> float:
    """`price x count` for one row; 0.0 when the price is unknown. Never raises."""
    price = row.get("price")
    if price is None:
        return 0.0
    try:
        return float(price) * int(row.get("count") or 0)
    except (TypeError, ValueError):
        return 0.0


def collection_stats(rows: list[dict], top_n: int = 10) -> dict:
    """Totals, colour spread, mana curve, type/rarity/set breakdown and top-value cards.

    Money is accumulated at full precision and rounded only on the way out.
    """
    totals = {"distinct": 0, "copies": 0, "value": 0.0,
              "priced": 0, "unpriced": 0, "unresolved": 0}

    buckets  = collections.defaultdict(lambda: {"distinct": 0, "copies": 0, "value": 0.0})
    presence = collections.defaultdict(lambda: {"distinct": 0, "copies": 0})
    types    = collections.defaultdict(lambda: {"distinct": 0, "copies": 0})
    rarities = collections.defaultdict(lambda: {"distinct": 0, "copies": 0, "value": 0.0})
    curve    = collections.defaultdict(lambda: {"distinct": 0, "copies": 0})
    sets     = collections.defaultdict(lambda: {"distinct": 0, "copies": 0, "value": 0.0})
    priced_rows: list[dict] = []

    for row in rows:
        count = int(row.get("count") or 0)
        value = row_value(row)
        price = row.get("price")

        totals["distinct"] += 1
        totals["copies"] += count
        if price is None:
            totals["unpriced"] += 1
        else:
            totals["priced"] += 1
            totals["value"] += value
        if not row.get("resolved", True):
            totals["unresolved"] += 1

        b = buckets[color_bucket(row.get("colors") or [])]
        b["distinct"] += 1
        b["copies"] += count
        b["value"] += value

        # Overlapping on purpose: colour IDENTITY is what "how much white do I own"
        # means, and a Boros card is white and red both.
        for colour in (row.get("color_identity") or []):
            p = presence[colour]
            p["distinct"] += 1
            p["copies"] += count

        t = types[row.get("type") or "Other"]
        t["distinct"] += 1
        t["copies"] += count

        rarity = row.get("rarity")
        if rarity:
            r = rarities[rarity]
            r["distinct"] += 1
            r["copies"] += count
            r["value"] += value

        # Lands are excluded: a mana curve that counts the cards you cast for free is
        # not a curve. They stay in every other breakdown.
        if not row.get("is_land"):
            cmc = int(row.get("cmc") or 0)
            c = curve[CURVE_TOP if cmc >= CURVE_TOP else cmc]
            c["distinct"] += 1
            c["copies"] += count

        s = sets[(row.get("set") or "").upper() or UNKNOWN_SET]
        s["distinct"] += 1
        s["copies"] += count
        s["value"] += value

        if price is not None:
            priced_rows.append({
                "name":  row.get("name", ""),
                "set":   row.get("set") or "",
                "cn":    row.get("cn") or "",
                "count": count,
                "price": round(float(price), 2),
                "total": round(value, 2),
                "_sort": value,
            })

    colors = [{"key": k, "label": _COLOR_LABELS[k], "distinct": buckets[k]["distinct"],
               "copies": buckets[k]["copies"], "value": round(buckets[k]["value"], 2)}
              for k in _COLOR_ORDER if k in buckets]

    # Always all five, including zeroes, so a chart axis is stable across refreshes.
    color_presence = [{"key": k, "label": _COLOR_LABELS[k],
                       "distinct": presence[k]["distinct"], "copies": presence[k]["copies"]}
                      for k in _PRESENCE_ORDER]

    types_out = [{"key": k, "distinct": v["distinct"], "copies": v["copies"]}
                 for k, v in sorted(types.items(), key=lambda e: (-e[1]["distinct"], e[0]))]

    known = [k for k in _RARITY_ORDER if k in rarities]
    extra = sorted(k for k in rarities if k not in _RARITY_ORDER)
    rarities_out = [{"key": k, "label": k.capitalize(), "distinct": rarities[k]["distinct"],
                     "copies": rarities[k]["copies"], "value": round(rarities[k]["value"], 2)}
                    for k in known + extra]

    curve_out = [{"cmc": n, "label": f"{n}+" if n == CURVE_TOP else str(n),
                  "distinct": curve[n]["distinct"], "copies": curve[n]["copies"]}
                 for n in range(CURVE_TOP + 1)]

    sets_out = [{"key": k, "distinct": v["distinct"], "copies": v["copies"],
                 "value": round(v["value"], 2)}
                for k, v in sorted(sets.items(),
                                   key=lambda e: (-e[1]["distinct"], e[0]))][:MAX_SETS]

    priced_rows.sort(key=lambda e: (-e["_sort"], e["name"]))
    top_value = [{k: v for k, v in e.items() if k != "_sort"} for e in priced_rows[:top_n]]

    totals["value"] = round(totals["value"], 2)
    return {
        "totals":         totals,
        "colors":         colors,
        "color_presence": color_presence,
        "types":          types_out,
        "rarities":       rarities_out,
        "curve":          curve_out,
        "sets":           sets_out,
        "top_value":      top_value,
    }
