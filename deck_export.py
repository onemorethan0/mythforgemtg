"""Deck export: a saved deck as text for other sites and tools, or as a backup.

Pure functions over a stored deck (`deck.json` shape); the route in `api/routes_decks.py` loads the
job and calls `render`. Nothing here touches the network or the GPU: printings come from the local
Scryfall printings store when the caller hands them in.

Formats (`FORMATS`)
  text      original card names and real quantities, in the format this app imports (round-trips)
  moxfield  `1 Sol Ring (C21) 263`, commander(s) first, a blank line, then the 99 -- pastes into
            Moxfield and Archidekt
  arena     the same lines under `Commander` / `Deck` headers, which MTG Arena's importer reads
  mtgo      `1 Sol Ring`, the command zone as `SB:` lines (how MTGO files a Commander deck)
  csv       one row per card: spreadsheets, inventory tools
  backup    the whole saved deck as JSON, for moving it to another machine or keeping a copy

The printing written is the one the source list named (a deck imported with `(SET) 123` keeps it),
else the cheapest nonfoil English printing -- the same basis the deck price uses.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Callable, Optional

FORMATS = ("text", "moxfield", "arena", "mtgo", "csv", "backup")

# format -> (file extension, media type)
_KIND = {
    "text": ("txt", "text/plain; charset=utf-8"),
    "moxfield": ("txt", "text/plain; charset=utf-8"),
    "arena": ("txt", "text/plain; charset=utf-8"),
    "mtgo": ("txt", "text/plain; charset=utf-8"),
    "csv": ("csv", "text/csv; charset=utf-8"),
    "backup": ("json", "application/json"),
}

PrintsLookup = Callable[[list], "dict[str, list[dict]]"]


def extension(fmt: str) -> str:
    return _KIND[fmt][0]


def media_type(fmt: str) -> str:
    return _KIND[fmt][1]


def safe_name(job: dict) -> str:
    cmd = (job.get("commander") or {}).get("original_name") or "deck"
    return ("".join(c if c.isalnum() else "_" for c in cmd)[:30]) or "deck"


def command_zone(job: dict) -> tuple[list[str], list[dict]]:
    """(the command zone's card names, the 99's stored entries).

    Only a real Commander deck has a command zone: an auto-elected display face is an ordinary
    maindeck card and must export as one. Partners live inside `deck` (they render as cards), so
    they are named in the zone and left out of the 99."""
    cmd = job.get("commander") or {}
    deck = list(job.get("deck") or [])
    if cmd.get("original_name"):
        if job.get("is_commander_deck", True) and not job.get("import_auto_face"):
            heads = [cmd["original_name"]] + [n for n in (job.get("partners") or []) if n]
            zone = {n.casefold() for n in heads}
            return heads, [c for c in deck if (c.get("original_name") or "").casefold() not in zone]
        deck = [cmd] + deck
    return [], deck


def _qty(card: dict) -> int:
    return int(card.get("quantity", 1) or 1)


def _hinted_printings(job: dict) -> dict[str, dict]:
    """The printings the source list named, {lowercased name: {"set", "collector_number"}}."""
    text = job.get("import_source_input")
    if not text:
        return {}
    try:
        import deck_import
        raw = deck_import._parse_text(text)
    except Exception:                                   # noqa: BLE001 - a hint, never a failure
        return {}
    return {k: v for k, v in (raw.printings or {}).items() if v.get("set") and v.get("collector_number")}


def _cheapest(prints: list[dict]) -> Optional[dict]:
    english = [p for p in prints if p.get("lang") in (None, "en") and p.get("set") and p.get("cn")]
    priced = [p for p in english if (p.get("prices") or {}).get("usd")]
    pool = priced or english
    if not pool:
        return None
    return min(pool, key=lambda p: ((p.get("prices") or {}).get("usd") or 1e9, p.get("set", ""),
                                    p.get("cn", "")))


def printing_for(name: str, hints: dict[str, dict], prints: dict[str, list[dict]]) -> Optional[tuple]:
    """(SET, collector number) to write after `name`, or None to write the bare name."""
    key = name.strip().lower()
    h = hints.get(key)
    if h:
        return str(h["set"]).upper(), str(h["collector_number"])
    best = _cheapest(prints.get(key) or [])
    return (best["set"].upper(), best["cn"]) if best else None


def _line(card_name: str, qty: int, printing: Optional[tuple]) -> str:
    return f"{qty} {card_name}" + (f" ({printing[0]}) {printing[1]}" if printing else "")


def _plain(job: dict) -> list[str]:
    heads, main = command_zone(job)
    lines = [f"Commander: {n}" for n in heads] + ([""] if heads else [])
    lines += [f"{_qty(c)} {c['original_name']}" for c in main if c.get("original_name")]
    unresolved = job.get("import_unresolved") or []
    if unresolved:
        # recorded as comments (the importer skips '#' lines) so the export is an honest account of
        # the source deck rather than a silently shorter one
        lines += ["", f"# {len(unresolved)} card(s) from the source could not be matched on "
                      "Scryfall and are NOT in this deck:"] + [f"# {n}" for n in unresolved]
    return lines


def render(job: dict, fmt: str, prints_lookup: Optional[PrintsLookup] = None) -> str:
    """The deck as `fmt` (see FORMATS). `prints_lookup(names)` returns {lowercased name: slim
    printings} (scryfall_prints.prints_of_many); without it a set-code format uses only the
    printings the source list named."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format {fmt!r}; choose one of: {', '.join(FORMATS)}")
    if fmt == "backup":
        return json.dumps(job, ensure_ascii=False, indent=1, default=str) + "\n"
    if fmt == "text":
        return "\n".join(_plain(job)) + "\n"

    heads, main = command_zone(job)
    entries = [(n, 1, None) for n in heads] + [(c["original_name"], _qty(c), c)
                                               for c in main if c.get("original_name")]
    if fmt == "mtgo":
        lines = [f"{q} {n}" for n, q, _ in entries[len(heads):]]
        return "\n".join(lines + ([""] + [f"SB: 1 {n}" for n in heads] if heads else [])) + "\n"

    hints = _hinted_printings(job)
    prints: dict[str, list[dict]] = {}
    if prints_lookup is not None:
        want = [n for n, _q, _c in entries if n.strip().lower() not in hints]
        try:
            prints = prints_lookup(want) or {}
        except Exception:                               # noqa: BLE001 - names only beats a failure
            prints = {}

    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["Quantity", "Name", "Set", "Collector Number", "Zone", "Mana Cost", "Type"])
        by_name = {(c.get("original_name") or ""): c for c in [job.get("commander") or {}] + list(job.get("deck") or [])}
        for i, (n, q, _c) in enumerate(entries):
            p = printing_for(n, hints, prints)
            card = by_name.get(n, {})
            w.writerow([q, n, p[0] if p else "", p[1] if p else "",
                        "Commander" if i < len(heads) else "Mainboard",
                        card.get("mana_cost", ""), card.get("original_type_line") or card.get("type_line", "")])
        return out.getvalue()

    lines = []
    cmd_lines = [_line(n, 1, printing_for(n, hints, prints)) for n in heads]
    main_lines = [_line(n, q, printing_for(n, hints, prints)) for n, q, _c in entries[len(heads):]]
    if fmt == "arena":
        lines += (["Commander"] + cmd_lines + [""] if cmd_lines else []) + ["Deck"] + main_lines
    else:                                               # moxfield / archidekt: command zone, blank, 99
        lines += cmd_lines + ([""] if cmd_lines else []) + main_lines
    return "\n".join(lines) + "\n"
