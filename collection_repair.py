"""Diagnose and repair collection rows whose NAME is really a whole decklist line.

An older bulk-import parser understood only a bare "13 Island", so every "13x Island
(msh) 290 *F* [Land]" landed with the entire line stored as the card name — invisible to
every owned-card lookup, because owned_key("1x sol ring (ltc) 273 [ramp]") is not
"sol ring". 246 of the live collection's 1040 rows were in that state, hiding ~24% of the
collection from collection-aware building. `collection.parse_decorated_line` fixes the
import path; this module cleans up what the old one already wrote.

Nothing here writes a file. `diagnose` PROPOSES and `apply_repairs` returns new rows —
the caller shows the proposals and applies only what the user accepts, because silently
rewriting the canonical collection is exactly the failure this module exists to undo.

    "1x Abandoned Air Temple (tla) 263 [Land]"   -> Abandoned Air Temple  x1   TLA 263
    "13x Island (msh) 290 [Land]"                -> Island               x13   MSH 290
    "1x Conciliator's Duelist (sos) 182 *F* [Creature]"
                                                 -> Conciliator's Duelist x1   SOS 182  foil
    "Sol Ring"                                   -> clean, no issue
"""

from __future__ import annotations

from collection import parse_decorated_line, printing_key

ISSUE_KINDS = ("quantity_prefix", "embedded_printing", "foil_marker", "category_suffix")


def parse_decorated(raw: str) -> dict:
    """Split a stored name into its parts, trusting only an explicit "13x" quantity.

    Delegates to `collection.parse_decorated_line` — one pattern serves both the import
    path and this repair path, so a repaired row can't be re-broken by the next import.
    A bare leading number is left ON the name here: at import time "13 Island" is a
    quantity, but a name already sitting in the collection may legitimately start with
    digits ("1996 World Champion"), and this function rewrites stored names.
    """
    p = parse_decorated_line(raw)
    if p["qty"] is not None and not p["qty_x"]:
        return {**p, "name": f"{p['qty']} {p['name']}".strip(), "qty": None}
    return p


def diagnose_row(row: dict, index: int) -> dict | None:
    """One row's proposed repair, or None when its name is already just a name."""
    p = parse_decorated(row.get("name", ""))
    qty, set_code, cn = p["qty"], p["set"], p["cn"]
    foil, tag = p["foil"], p["tag"]

    if qty is None and not set_code and not foil and not tag:
        return None

    kinds = [k for k, present in (
        ("quantity_prefix",   qty is not None),
        ("embedded_printing", bool(set_code)),
        ("foil_marker",       foil),
        ("category_suffix",   bool(tag)),
    ) if present]

    count = int(row.get("count", 0) or 0)
    # The "<n>x" is the quantity the user's SOURCE decklist stated. The stored Count is
    # an import artifact: the old parser gave every "13x ..." row a count of 1, so a
    # stored count above 1 means the same junk row was merge-imported that many times,
    # not that the user owns more copies. Multiplying the two would fabricate copies, so
    # take the source quantity and flag the disagreement rather than guess.
    proposed = {
        "name":  p["name"],
        "count": qty if qty is not None else count,
        "set":   set_code or (row.get("set") or ""),
        "cn":    cn or (row.get("cn") or ""),
    }
    return {
        "index":    index,
        "kinds":    kinds,
        "current":  {"name": row.get("name", ""), "count": count,
                     "set": row.get("set") or "", "cn": row.get("cn") or ""},
        "proposed": proposed,
        "foil":     foil,
        "tag":      tag,
        "count_conflict": qty is not None and count != qty,
    }


def diagnose(rows: list[dict]) -> dict:
    """Every proposed repair, plus what accepting all of them would do to the totals."""
    issues = [i for i in (diagnose_row(r, n) for n, r in enumerate(rows)) if i]
    by_index = {i["index"]: i for i in issues}
    copies_before = sum(int(r.get("count", 0) or 0) for r in rows)
    # A clean row contributes its own count; an affected row contributes its PROPOSED
    # count. Summing only the affected rows would report the recovered copies as if they
    # were the whole collection.
    copies_after = sum(
        by_index[n]["proposed"]["count"] if n in by_index else int(r.get("count", 0) or 0)
        for n, r in enumerate(rows)
    )
    return {
        "issues":        issues,
        "rows":          len(rows),
        "affected":      len(issues),
        "clean":         len(rows) - len(issues),
        "copies_before": copies_before,
        "copies_after":  copies_after,
    }


def _fresh(row: dict, name: str, count: int, set_code: str, cn: str,
           foil: bool) -> dict:
    """A NEW row dict — never sharing the input's `_extra`, which callers still hold."""
    out = {"name": name, "count": int(count), "set": set_code, "cn": cn}
    extra = dict(row.get("_extra") or {})
    if foil:
        # Moxfield-style column; write_collection preserves columns it doesn't model.
        extra["Foil"] = "foil"
    if extra:
        out["_extra"] = extra
    return out


def apply_repairs(rows: list[dict], accept: set[int] | None = None
                  ) -> tuple[list[dict], dict]:
    """Apply the accepted repairs. Returns (new_rows, report); inputs are never mutated.

    `accept` holds issue indexes; None accepts every issue. Repairing can collapse two
    rows onto one printing, so counts are merged into the first occurrence.
    """
    out: list[dict] = []
    seen: dict[tuple, dict] = {}
    repaired = merged = 0

    for index, row in enumerate(rows):
        issue = diagnose_row(row, index)
        if issue and (accept is None or index in accept):
            p = issue["proposed"]
            new_row = _fresh(row, p["name"], p["count"], p["set"], p["cn"], issue["foil"])
            repaired += 1
        else:
            new_row = _fresh(row, row.get("name", ""), int(row.get("count", 0) or 0),
                             row.get("set") or "", row.get("cn") or "", False)

        # Collisions are checked against EVERY row already emitted, not just repaired
        # ones — a repaired row usually collides with an untouched one.
        key = printing_key(new_row["name"], new_row["set"], new_row["cn"])
        if key in seen:
            first = seen[key]
            first["count"] += new_row["count"]
            # First row wins on conflicts: it is the one the user has been looking at.
            for k, v in (new_row.get("_extra") or {}).items():
                first.setdefault("_extra", {}).setdefault(k, v)
            merged += 1
            continue
        seen[key] = new_row
        out.append(new_row)

    return out, {
        "repaired":      repaired,
        "merged":        merged,
        "copies_before": sum(int(r.get("count", 0) or 0) for r in rows),
        "copies_after":  sum(r["count"] for r in out),
        "rows_before":   len(rows),
        "rows_after":    len(out),
    }
