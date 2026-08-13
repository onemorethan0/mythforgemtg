"""Myth Suite collection contract (C1): read the user's owned-cards export.

The canonical file is ``%USERPROFILE%/Documents/MythSuite/collection.csv`` (a Moxfield-style
CSV written by MythScanner). Both ends of the suite honor the same ``MYTHSUITE_DIR`` override
(MythGauntlet's ``config.suite_collection_path`` and MythScanner's exporter mirror this) —
keep them in lock-step. See mythgauntlet/docs/SUITE_PLAN.md for the authoritative contract.

Collection-aware building only needs the SET of owned card names, normalized so it matches
Scryfall card names (front face, case-insensitive).
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

_NAME_COLUMNS = ("name", "card name", "card")


def suite_dir() -> Path:
    """The Myth Suite handoff directory (contract C1). Override: MYTHSUITE_DIR."""
    override = os.environ.get("MYTHSUITE_DIR")
    return Path(override) if override else Path.home() / "Documents" / "MythSuite"


def suite_collection_path() -> Path:
    """Canonical collection file (Moxfield CSV) — contract C1."""
    return suite_dir() / "collection.csv"


def owned_key(name: str) -> str:
    """Normalize a card name for owned-set membership: front face, casefolded.

    Double-faced/split cards are keyed on the front face so 'Fire // Ice' in a decklist
    matches an 'owned' entry written as either the full name or just 'Fire'.
    """
    n = (name or "").strip()
    if "//" in n:
        n = n.split("//", 1)[0].strip()
    return n.casefold()


def _find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {(f or "").strip().casefold(): f for f in fieldnames}
    for cand in candidates:
        if cand in lowered:
            return lowered[cand]
    return None


def parse_owned(text: str) -> set[str]:
    """Owned card names (normalized) from a Moxfield-style CSV or a plain decklist."""
    stripped = text.lstrip()
    first_line = stripped.splitlines()[0] if stripped else ""
    if "," in first_line and _find_column(first_line.split(","), _NAME_COLUMNS):
        return _from_csv(text)
    return _from_decklist(text)


def _from_csv(text: str) -> set[str]:
    reader = csv.DictReader(text.splitlines())
    name_col = _find_column(reader.fieldnames or [], _NAME_COLUMNS)
    if name_col is None:
        return set()
    owned: set[str] = set()
    for row in reader:
        name = (row.get(name_col) or "").strip()
        if name:
            owned.add(owned_key(name))
    return owned


def _from_decklist(text: str) -> set[str]:
    """'1 Sol Ring' / 'Sol Ring' / 'Commander: X' lines -> owned names."""
    owned: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        if ":" in line.split(" ", 1)[0]:  # 'Commander:' style header prefix
            line = line.split(":", 1)[1].strip()
        parts = line.split(" ", 1)
        if parts[0].isdigit() and len(parts) > 1:  # leading quantity
            line = parts[1].strip()
        line = line.split("(", 1)[0].strip()  # strip a trailing '(SET) 123' tag
        if line:
            owned.add(owned_key(line))
    return owned


def load_owned_names(path: Path | None = None) -> set[str]:
    """Load the owned-card name set from the collection file. Empty set if absent/unreadable."""
    p = path or suite_collection_path()
    try:
        return parse_owned(p.read_text(encoding="utf-8-sig"))
    except OSError:
        return set()


def owned_count(cards: list[dict], owned: set[str]) -> int:
    """How many of these card dicts (by name) are in the owned set."""
    if not owned:
        return 0
    return sum(1 for c in cards if owned_key(c.get("name", "")) in owned)


# ── Collection editing (CRUD over the canonical MythSuite/collection.csv) ─────────
# The deck-building path above only needs the SET of owned names. The manager below
# is quantity-aware: it round-trips the `Count,Name` CSV so a user can browse/add/
# edit/remove owned cards inside Myth Forge. Writes go to the SAME canonical file
# MythScanner appends to (single source of truth), with a .bak safety copy each write.

_COUNT_COLUMNS = ("count", "quantity", "qty", "amount")
# Moxfield/ManaBox/Scanner exports name the set column differently; collector number
# disambiguates printings within a set (alt arts, showcases).
_SET_COLUMNS = ("edition", "set", "set code", "setcode", "expansion")
_CN_COLUMNS  = ("collector number", "collector_number", "card number", "number", "cn")


def printing_key(name: str, set_code: str = "", cn: str = "") -> tuple:
    """Identity of a specific PRINTING: (normalized name, set, collector number).

    A collection can hold the same card in several sets; each printing is its own row
    with its own count. Ownership questions ("do I own Sol Ring?") stay name-level —
    see load_owned_names — so nothing downstream has to care about printings."""
    return (owned_key(name), (set_code or "").strip().upper(), (cn or "").strip())


def load_collection(path: Path | None = None) -> list[dict]:
    """Owned cards as an ordered list of {"name", "count", "set", "cn"}.

    Reads the canonical CSV honoring its Count column (unlike load_owned_names, which
    only needs the name set). Duplicate names are merged, counts summed. A plain
    decklist (no header) is accepted too — each line's leading quantity is the count.
    Returns [] if the file is absent/unreadable/empty."""
    p = path or suite_collection_path()
    try:
        return _parse_rows(p.read_text(encoding="utf-8-sig"))
    except OSError:
        return []


def write_collection(rows: list[dict], path: Path | None = None) -> int:
    """Persist as a `Count,Name,Edition,Collector Number` CSV (Moxfield-compatible),
    backing up the previous file to `<name>.bak` first. Rows with count<=0 are dropped.
    Set/collector number are written blank when unknown, so the file stays readable by
    anything that only understands Count,Name. Returns the number of rows written."""
    p = path or suite_collection_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            (p.with_suffix(p.suffix + ".bak")).write_bytes(p.read_bytes())
        except OSError:
            pass
    clean = [r for r in rows if int(r.get("count", 0)) > 0 and (r.get("name") or "").strip()]

    # ATOMIC WRITE — this is the canonical Myth Suite collection file, it has more than one
    # writer (MythScanner's export targets the same path), and Myth Forge rewrites it on
    # every single +/- click in the collection manager. Opening the real path with "w"
    # truncates it immediately, so an interrupted write (crash, power loss, disk full) left
    # the user's entire collection truncated, and a reader mid-write — the deck builder's
    # load_owned_names, say — could silently build from half a collection. Writing a temp
    # file in the SAME directory and os.replace()ing it is atomic on both Windows and POSIX
    # for same-volume renames, so readers see either the old file or the new one, never a
    # partial one. (Same directory matters: os.replace across volumes is not atomic.)
    # Columns this module does not model but the file may carry. MythScanner's export
    # writes Condition/Language/Foil; before this, a single +/- click in Forge rewrote the
    # file with only our four columns and silently DELETED the scanner's per-copy data.
    # Preserve any extra column seen on read, in first-seen order, appended after ours.
    extra_cols: list[str] = []
    for r in clean:
        for key in (r.get("_extra") or {}):
            if key not in extra_cols:
                extra_cols.append(key)

    tmp = p.with_name(f".{p.name}.tmp")
    try:
        # utf-8-sig so Excel and MythScanner (which reads utf-8-sig) both open it cleanly.
        with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Count", "Name", "Edition", "Collector Number"] + extra_cols)
            for r in clean:
                extra = r.get("_extra") or {}
                w.writerow([int(r["count"]), r["name"].strip(),
                            (r.get("set") or "").strip().upper(), (r.get("cn") or "").strip()]
                           + [extra.get(col, "") for col in extra_cols])
            fh.flush()
            os.fsync(fh.fileno())   # durable before the rename, not just in the page cache
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)   # never leave a stray .tmp beside the collection
        raise
    return len(clean)


def _find_row(rows: list[dict], name: str, set_code: str | None = None,
              cn: str | None = None) -> dict | None:
    """Find a row. With `set_code` it targets that exact PRINTING; without one it
    matches the first printing of that card (legacy, name-level behaviour)."""
    k = owned_key(name)
    if set_code:
        want = (set_code or "").strip().upper()
        for r in rows:
            if owned_key(r["name"]) == k and (r.get("set") or "").strip().upper() == want:
                if cn is None or (r.get("cn") or "").strip() == (cn or "").strip():
                    return r
        return None
    return next((r for r in rows if owned_key(r["name"]) == k), None)


def add_card(name: str, count: int = 1, path: Path | None = None,
             display_name: str | None = None, set_code: str | None = None,
             cn: str | None = None) -> list[dict]:
    """Add `count` copies. With `set_code` this adds/merges that specific PRINTING (a
    different set becomes its own row); without one it merges into the first printing
    of that card. `display_name` overrides the stored spelling."""
    rows = load_collection(path)
    existing = _find_row(rows, name, set_code, cn)
    if existing:
        existing["count"] += max(int(count), 1)
        if display_name:
            existing["name"] = display_name
    else:
        rows.append({"name": (display_name or name).strip(), "count": max(int(count), 1),
                     "set": (set_code or "").strip().upper(), "cn": (cn or "").strip()})
    write_collection(rows, path)
    return rows


def set_count(name: str, count: int, path: Path | None = None,
              set_code: str | None = None, cn: str | None = None) -> list[dict]:
    """Set an exact count. count<=0 removes that row. With `set_code`, targets that
    printing; otherwise the first printing of the card."""
    rows = load_collection(path)
    existing = _find_row(rows, name, set_code, cn)
    if existing:
        if int(count) <= 0:
            rows = [r for r in rows if r is not existing]
        else:
            existing["count"] = int(count)
    elif int(count) > 0:
        rows.append({"name": name.strip(), "count": int(count),
                     "set": (set_code or "").strip().upper(), "cn": (cn or "").strip()})
    write_collection(rows, path)
    return rows


def remove_card(name: str, path: Path | None = None, set_code: str | None = None,
                cn: str | None = None) -> list[dict]:
    """Remove a card. With `set_code` only that printing is dropped; without one, ALL
    printings of the card are removed (you no longer own it in any set)."""
    rows = load_collection(path)
    if set_code:
        target = _find_row(rows, name, set_code, cn)
        rows = [r for r in rows if r is not target]
    else:
        rows = [r for r in rows if owned_key(r["name"]) != owned_key(name)]
    write_collection(rows, path)
    return rows


def set_printing(name: str, set_code: str, cn: str, from_set: str | None = None,
                 from_cn: str | None = None, path: Path | None = None) -> list[dict]:
    """Move a row to a different PRINTING of the same card, keeping its count.

    If the collection already holds that printing, the two rows merge (counts summed)
    rather than becoming duplicates of the same physical card.
    """
    rows = load_collection(path)
    src = _find_row(rows, name, from_set, from_cn)
    if src is None:
        return rows
    dest = _find_row(rows, name, (set_code or "").strip().upper() or None, cn)
    if dest is not None and dest is not src:
        dest["count"] += src["count"]
        rows = [r for r in rows if r is not src]
    else:
        src["set"] = (set_code or "").strip().upper()
        src["cn"] = (cn or "").strip()
    write_collection(rows, path)
    return rows


def bulk_apply(targets: list[dict], action: str, count: int = 0,
               path: Path | None = None) -> tuple[list[dict], int]:
    """Apply one action to many printings in a SINGLE write. Returns (rows, affected).

    Every mutating helper above rewrites the whole CSV and refreshes the .bak, so doing a
    20-row cleanup one call at a time means 20 full rewrites — and 20 chances for the
    backup to be overwritten with an already-modified file, which would cost the user
    their Undo. One pass, one write, one .bak.

    `targets` are {"name", "set", "cn"} dicts; `action` is "remove" or "set_count".
    """
    rows = load_collection(path)
    wanted = {printing_key(t.get("name", ""), t.get("set", ""), t.get("cn", ""))
              for t in targets if (t.get("name") or "").strip()}
    if not wanted:
        return rows, 0

    affected = 0
    kept: list[dict] = []
    for r in rows:
        if printing_key(r["name"], r.get("set", ""), r.get("cn", "")) not in wanted:
            kept.append(r)
            continue
        affected += 1
        if action == "remove" or (action == "set_count" and int(count) <= 0):
            continue
        if action == "set_count":
            r["count"] = int(count)
        kept.append(r)
    write_collection(kept, path)
    return kept, affected


def bulk_import(text: str, mode: str = "merge", path: Path | None = None) -> list[dict]:
    """Import a pasted CSV or decklist. mode="merge" adds counts onto the current
    collection; mode="replace" overwrites it. Merging is per PRINTING, so importing a
    second set's copy adds a row rather than inflating the first printing's count."""
    incoming = _parse_rows(text)
    if mode == "replace":
        merged = incoming
    else:
        merged = load_collection(path)
        index = {printing_key(r["name"], r.get("set", ""), r.get("cn", "")): r for r in merged}
        for r in incoming:
            k = printing_key(r["name"], r.get("set", ""), r.get("cn", ""))
            if k in index:
                index[k]["count"] += r["count"]
            else:
                merged.append(dict(r))
                index[k] = merged[-1]
    write_collection(merged, path)
    return merged


import re as _re

# Everything a pasted decklist line can carry around the card name:
#     "13x Island (msh) 290 *F* [Land]"
#      qty  name    set  cn  foil  exporter's deckbuilding category
# All four decorations are optional; only the name is required.
#
# This is ONE pattern with TWO callers on purpose. It parses imports here, and
# `collection_repair` re-parses rows that were imported before it existed — the older
# parser accepted only a bare "13 Island" (`parts[0].isdigit()`, which "13x" fails) and
# its printing regex was anchored to end-of-line, so a trailing "*F*" or "[Land]" also
# defeated it. Both misses stored the WHOLE LINE as the card name, and a name like
# "1x sol ring (ltc) 273 [ramp]" never equals owned_key("sol ring"), so those cards were
# invisible to owned-aware building, the buildable scan and /advise alike. 246 of the
# live collection's 1040 rows were in that state. Two copies of this regex would let the
# import path and the repair path drift apart, and then a repaired row could be
# re-broken by the next import — so there is exactly one.
DECORATED_LINE_RE = _re.compile(
    r"""^\s*
        (?:(?P<qty>\d+)\s*(?P<qty_x>[xX])?\s+)? # "13x " or a bare "13 "
        (?P<name>.+?)                           # the card name (lazy)
        (?:\s*\((?P<set>[A-Za-z0-9]{2,6})\)     # " (msh)"
           (?:\s*(?P<cn>[A-Za-z0-9\-★]+))?      # " 290"
        )?
        (?:\s*\*(?P<foil>[A-Za-z]{1,2})\*)?     # " *F*" foil, " *E*" etched
        (?:\s*\[(?P<tag>[^\]]*)\])?             # " [Land]"
        \s*$""",
    _re.X,
)


_BLANK_PARSE = {"name": "", "qty": None, "qty_x": False, "set": "", "cn": "",
                "foil": False, "tag": ""}


def parse_decorated_line(raw: str) -> dict:
    """Split a decklist line into {"name", "qty", "qty_x", "set", "cn", "foil", "tag"}.

    `qty` is None when the line carried no quantity prefix. `qty_x` records whether that
    prefix was the explicit "13x" form rather than a bare "13" — importing trusts either,
    but `collection_repair` rewrites a name the user already has stored and so only
    trusts the unambiguous one ("1996 World Champion" is a card; "1996x Foo" is not).

    `name` is NEVER empty: a line the pattern can't read degrades to "store it verbatim",
    because losing a card is worse than storing an ugly name.
    """
    text = (raw or "").strip()
    m = DECORATED_LINE_RE.match(text)
    name = (m.group("name") or "").strip() if m else ""
    if not m or not name:
        return {**_BLANK_PARSE, "name": text}
    return {
        "name":  name,
        "qty":   int(m.group("qty")) if m.group("qty") else None,
        "qty_x": bool(m.group("qty_x")),
        "set":   (m.group("set") or "").strip().upper(),
        "cn":    (m.group("cn") or "").strip(),
        "foil":  bool(m.group("foil")),
        "tag":   (m.group("tag") or "").strip(),
    }


def _parse_rows(text: str) -> list[dict]:
    """Parse pasted CSV/decklist text into [{"name","count","set","cn"}] (no file I/O).

    Printing-aware: a CSV's Edition/Collector-Number columns and a decklist's
    "(SET) 123" suffix are captured instead of discarded, so the same card owned in
    several sets stays several rows. Rows are merged on the full printing key."""
    import io
    stripped = text.lstrip()
    first_line = stripped.splitlines()[0] if stripped else ""
    rows: dict[tuple, dict] = {}
    order: list[tuple] = []

    def _add(name: str, count: int, set_code: str = "", cn: str = "",
             extra: dict | None = None) -> None:
        name = (name or "").strip()
        if not name:
            return
        k = printing_key(name, set_code, cn)
        if k in rows:
            rows[k]["count"] += count
        else:
            rows[k] = {"name": name, "count": count,
                       "set": (set_code or "").strip().upper(), "cn": (cn or "").strip()}
            # Columns we do not model (MythScanner writes Condition/Language/Foil) ride
            # along so a Forge edit round-trips them instead of deleting them. See
            # write_collection.
            if extra:
                rows[k]["_extra"] = extra
            order.append(k)

    if "," in first_line and _find_column(first_line.split(","), _NAME_COLUMNS):
        reader = csv.DictReader(io.StringIO(text))
        fields = reader.fieldnames or []
        name_col  = _find_column(fields, _NAME_COLUMNS)
        count_col = _find_column(fields, _COUNT_COLUMNS)
        set_col   = _find_column(fields, _SET_COLUMNS)
        cn_col    = _find_column(fields, _CN_COLUMNS)
        for row in reader:
            name = (row.get(name_col) or "").strip() if name_col else ""
            try:
                cnt = int(float((row.get(count_col) or "1").strip())) if count_col else 1
            except (TypeError, ValueError):
                cnt = 1
            known = {c for c in (name_col, count_col, set_col, cn_col) if c}
            extra = {k: v for k, v in row.items()
                     if k and k not in known and (v or "").strip()}
            _add(name, max(cnt, 1),
                 (row.get(set_col) or "") if set_col else "",
                 (row.get(cn_col) or "") if cn_col else "",
                 extra)
    else:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "//")):
                continue
            if ":" in line.split(" ", 1)[0]:
                line = line.split(":", 1)[1].strip()
            p = parse_decorated_line(line)
            # The exporter's "[Land]"/"[Ramp]" tag is a deckbuilding CATEGORY, not
            # collection data, so it is read off the line and discarded. Foil is real
            # per-copy data, and write_collection round-trips unmodelled columns.
            _add(p["name"], max(p["qty"] or 1, 1), p["set"], p["cn"],
                 {"Foil": "foil"} if p["foil"] else None)
    return [rows[k] for k in order]
