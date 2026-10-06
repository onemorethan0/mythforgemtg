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
import hashlib
import os
import re as _re
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
#
# Set-code precedence (D1). MythScanner writes the real code to `Edition Code` and leaves
# `Edition` blank, so the dedicated code columns come first. The generic columns (`Edition`,
# `Set`) hold a SET NAME in Deckbox-style exports, so they are adopted only when the value is
# shaped like a code (see _looks_like_code); the first non-blank acceptable value wins per row.
_SET_CODE_COLUMNS = ("edition code", "set code", "setcode")
_SET_GENERIC_COLUMNS = ("edition", "set", "expansion")
_SET_COLUMNS = _SET_CODE_COLUMNS + _SET_GENERIC_COLUMNS
_CN_COLUMNS  = ("collector number", "collector_number", "card number", "number", "cn")
_FINISH_COLUMNS = ("finish", "foil", "printing")
_LANG_COLUMNS = ("language", "lang")
_CONDITION_COLUMNS = ("condition",)
_SCRYFALL_COLUMNS = ("scryfall id", "scryfall_id", "scryfallid")
# Derivable from the printing itself; dropped on read rather than written back, where they
# could only go stale and contradict the Edition/Collector Number we do write.
_CONSUMED = ("edition name", "set name", "multiverse id")

_CODE_RE = _re.compile(r"^[A-Za-z0-9]{2,6}$")

_FINISH_FOIL = {"foil", "f", "yes", "true"}
_FINISH_ETCHED = {"etched", "e", "foil etched"}


def normalize_finish(value: str) -> str:
    """'nonfoil' | 'foil' | 'etched' from any exporter's spelling (case-insensitive).

    Unknown/blank values are 'nonfoil': the plain card is the honest default."""
    v = (value or "").strip().casefold()
    if v in _FINISH_ETCHED:
        return "etched"
    if v in _FINISH_FOIL:
        return "foil"
    return "nonfoil"


def _looks_like_code(value: str) -> bool:
    """A generic Edition/Set value that is a code rather than a set NAME (R8).

    2-6 alphanumerics AND (all-lowercase, all-uppercase, or containing a digit): "znr",
    "C21" and "40K" are codes; a mixed-case word like "Mirage" or "Alpha" is a name."""
    v = (value or "").strip()
    if not _CODE_RE.match(v):
        return False
    return v.islower() or v.isupper() or any(ch.isdigit() for ch in v)


def row_identity(row: dict) -> tuple:
    """Identity of one physical-card row (D4): (name, SET, cn, finish, lang or 'en', condition).

    Finish is part of it because foil and nonfoil copies are different cards with different
    prices; a blank language means English; condition compares case-insensitively."""
    return (owned_key(row.get("name", "")),
            (row.get("set") or "").strip().upper(),
            (row.get("cn") or "").strip(),
            normalize_finish(row.get("finish", "")),
            (row.get("lang") or "").strip().casefold() or "en",
            (row.get("condition") or "").strip().upper())


def row_id(row: dict) -> str:
    """Stable 12-hex id of a row's identity (D6): sha1 of the identity joined on \\x1f.

    The CSV has a second writer (MythScanner), so a client addresses a row by what it IS,
    not by its position; an id whose row has since changed no longer resolves."""
    joined = "\x1f".join(str(part) for part in row_identity(row))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def find_by_id(rows: list[dict], rid: str) -> dict | None:
    """The row whose row_id is `rid`, or None."""
    return next((r for r in rows if row_id(r) == rid), None)


def set_count_by_id(rid: str, count: int, path: Path | None = None) -> list[dict]:
    """Set the exact count of the row `rid` (count<=0 removes it). KeyError(rid) if absent."""
    rows = load_collection(path)
    target = find_by_id(rows, rid)
    if target is None:
        raise KeyError(rid)
    if int(count) <= 0:
        rows = [r for r in rows if r is not target]
    else:
        target["count"] = int(count)
    write_collection(rows, path)
    return rows


def remove_by_id(rid: str, path: Path | None = None) -> list[dict]:
    """Remove the row `rid`. KeyError(rid) if absent."""
    rows = load_collection(path)
    target = find_by_id(rows, rid)
    if target is None:
        raise KeyError(rid)
    rows = [r for r in rows if r is not target]
    write_collection(rows, path)
    return rows


def _blank_row(name: str, count: int, set_code: str = "", cn: str = "") -> dict:
    return {"name": name.strip(), "count": int(count),
            "set": (set_code or "").strip().upper(), "cn": (cn or "").strip(),
            "finish": "nonfoil", "lang": "", "condition": "", "scryfall_id": ""}


def _merge_row(rows: list[dict], exact: dict, loose: dict, incoming: dict) -> None:
    """Fold `incoming` into `rows` using row_identity plus the D4 blank-condition rule.

    A row with a BLANK condition merges into the unique existing row that matches on
    everything else (so a plain decklist import doesn't fork every conditioned row);
    otherwise it becomes a new row. `exact`/`loose` are the caller's indexes. Pass
    `loose=None` for an exact-identity-only merge (loading a file must not depend on row
    order or collapse the file's own rows, R9)."""
    k = row_identity(incoming)
    target = exact.get(k)
    if target is None and loose is not None and not k[5]:
        cands = loose.get(k[:5], [])
        if len(cands) == 1:
            target = cands[0]
    if target is not None:
        target["count"] += incoming["count"]
        if not target.get("scryfall_id") and incoming.get("scryfall_id"):
            target["scryfall_id"] = incoming["scryfall_id"]
        return
    rows.append(incoming)
    exact[k] = incoming
    if loose is not None and k[5]:
        loose.setdefault(k[:5], []).append(incoming)


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
    """Persist as a Moxfield-compatible CSV with the canonical header (D5):
    `Count,Name,Edition,Collector Number,Foil,Language,Condition,Scryfall ID`, then any
    unmodelled extra columns. `Foil` is ""/foil/etched. Alias columns (Edition Code, Finish,
    Edition Name...) are consumed on read, never written back, so a printing change cannot
    leave a stale column contradicting the new one. The previous file is backed up to
    `<name>.bak` first. Rows with count<=0 are dropped; unknown fields are written blank.
    Returns the number of rows written."""
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
    canonical = ["Count", "Name", "Edition", "Collector Number", "Foil", "Language",
                 "Condition", "Scryfall ID"]
    reserved = {c.casefold() for c in canonical}
    extra_cols: list[str] = []
    for r in clean:
        for key in (r.get("_extra") or {}):
            if key not in extra_cols and key.strip().casefold() not in reserved:
                extra_cols.append(key)

    tmp = p.with_name(f".{p.name}.tmp")
    try:
        # utf-8-sig so Excel and MythScanner (which reads utf-8-sig) both open it cleanly.
        with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(canonical + extra_cols)
            for r in clean:
                extra = r.get("_extra") or {}
                finish = normalize_finish(r.get("finish", ""))
                w.writerow([int(r["count"]), r["name"].strip(),
                            (r.get("set") or "").strip().upper(), (r.get("cn") or "").strip(),
                            "" if finish == "nonfoil" else finish,
                            (r.get("lang") or "").strip().casefold(),
                            (r.get("condition") or "").strip(),
                            (r.get("scryfall_id") or "").strip()]
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
        rows.append(_blank_row(display_name or name, max(int(count), 1), set_code or "", cn or ""))
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
        rows.append(_blank_row(name, int(count), set_code or "", cn or ""))
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

    `targets` are {"row_id"} or {"name", "set", "cn"} dicts (a target with a row_id is
    addressed by it alone); `action` is "remove" or "set_count". A row_id that matches no
    row raises KeyError(rid) BEFORE anything is written, so a stale selection changes nothing.
    """
    rows = load_collection(path)
    wanted_ids = {t["row_id"] for t in targets if (t.get("row_id") or "").strip()}
    wanted = {printing_key(t.get("name", ""), t.get("set", ""), t.get("cn", ""))
              for t in targets
              if not (t.get("row_id") or "").strip() and (t.get("name") or "").strip()}
    if not wanted and not wanted_ids:
        return rows, 0
    if wanted_ids:
        present = {row_id(r) for r in rows}
        for rid in sorted(wanted_ids):
            if rid not in present:
                raise KeyError(rid)

    affected = 0
    kept: list[dict] = []
    for r in rows:
        if (row_id(r) not in wanted_ids
                and printing_key(r["name"], r.get("set", ""), r.get("cn", "")) not in wanted):
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
    collection; mode="replace" overwrites it. Merging is per row identity (printing + finish,
    language, condition): a second set's copy or a foil of an owned nonfoil adds a row. An
    incoming blank condition merges into the unique otherwise-matching conditioned row (D4)."""
    incoming = _parse_rows(text)
    if mode == "replace":
        merged = incoming
    else:
        merged = load_collection(path)
        exact: dict[tuple, dict] = {}
        loose: dict[tuple, list] = {}
        for r in merged:
            k = row_identity(r)
            exact.setdefault(k, r)
            if k[5]:
                loose.setdefault(k[:5], []).append(r)
        for r in incoming:
            _merge_row(merged, exact, loose, dict(r))
    write_collection(merged, path)
    return merged


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
        (?:\[(?P<lead>[A-Za-z0-9]{2,6})\]\s*)?  # "[C21] " — Deckstats puts the set FIRST
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
                "foil": False, "finish": "nonfoil", "tag": ""}


def parse_decorated_line(raw: str) -> dict:
    """Split a decklist line into {"name", "qty", "qty_x", "set", "cn", "foil", "finish", "tag"}.

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
    set_code = (m.group("set") or "").strip().upper()
    # A LEADING bracket is Deckstats' set code ("1 [C21] Sol Ring"); a TRAILING one is
    # Archidekt's deckbuilding category ("... [Ramp]"), handled by `tag`. Position tells
    # them apart, but not perfectly — a few exporters lead with the category instead, and
    # "[LAND]" is shaped exactly like a set code. So the token is always stripped off the
    # NAME (a name that doesn't resolve is the expensive failure), while it is only
    # ADOPTED as a set when it looks like one: real codes carry a digit or are all-caps,
    # whereas categories read as words ("Ramp", "Land"). When in doubt the printing stays
    # unknown, which is honest and fixable, rather than confidently wrong.
    lead = (m.group("lead") or "").strip()
    if lead and not set_code and (any(ch.isdigit() for ch in lead) or lead.isupper()):
        set_code = lead.upper()
    marker = (m.group("foil") or "").strip()
    return {
        "name":  name,
        "qty":   int(m.group("qty")) if m.group("qty") else None,
        "qty_x": bool(m.group("qty_x")),
        "set":   set_code,
        "cn":    (m.group("cn") or "").strip(),
        "foil":  bool(marker),
        # "*F*" foil, "*E*" etched; any other marker still means "not the plain card".
        "finish": "etched" if marker.casefold() == "e" else ("foil" if marker else "nonfoil"),
        "tag":   (m.group("tag") or "").strip(),
    }


def _first(row: dict, cols: list[str], accept=None) -> str:
    """First non-blank value among `cols` (already in precedence order) that `accept`s it."""
    for c in cols:
        v = (row.get(c) or "").strip()
        if v and (accept is None or accept(v)):
            return v
    return ""


def _present(fields: list[str], candidates: tuple[str, ...]) -> list[str]:
    """The actual header spellings for `candidates`, in the candidates' precedence order."""
    lowered = {(f or "").strip().casefold(): f for f in fields}
    return [lowered[c] for c in candidates if c in lowered]


def _parse_rows(text: str) -> list[dict]:
    """Parse pasted CSV/decklist text into row dicts (no file I/O).

    Every row carries name, count, set (UPPER), cn, finish (nonfoil|foil|etched), lang
    (lowercase, "" when unknown), condition, scryfall_id, plus `_extra` for columns we do
    not model. Set resolves per D1: the dedicated code columns (Edition Code, Set Code)
    first, then Edition/Set only when the value looks like a code (Deckbox puts the set NAME
    there). Rows merge on row_identity, so foil and nonfoil of one printing stay separate."""
    import io
    stripped = text.lstrip()
    first_line = stripped.splitlines()[0] if stripped else ""
    rows: list[dict] = []
    exact: dict[tuple, dict] = {}

    def _add(name: str, count: int, set_code: str = "", cn: str = "", finish: str = "",
             lang: str = "", condition: str = "", scryfall_id: str = "",
             extra: dict | None = None) -> None:
        name = (name or "").strip()
        if not name:
            return
        row = _blank_row(name, count, set_code, cn)
        row.update(finish=normalize_finish(finish), lang=(lang or "").strip().casefold(),
                   condition=(condition or "").strip(), scryfall_id=(scryfall_id or "").strip())
        # Columns we do not model (Date Added, Tags...) ride along so a Forge edit
        # round-trips them instead of deleting them. See write_collection.
        if extra:
            row["_extra"] = extra
        _merge_row(rows, exact, None, row)

    if "," in first_line and _find_column(first_line.split(","), _NAME_COLUMNS):
        reader = csv.DictReader(io.StringIO(text))
        fields = reader.fieldnames or []
        name_col  = _find_column(fields, _NAME_COLUMNS)
        count_col = _find_column(fields, _COUNT_COLUMNS)
        code_cols    = _present(fields, _SET_CODE_COLUMNS)
        generic_cols = _present(fields, _SET_GENERIC_COLUMNS)
        cn_cols      = _present(fields, _CN_COLUMNS)
        finish_cols  = _present(fields, _FINISH_COLUMNS)
        lang_cols    = _present(fields, _LANG_COLUMNS)
        cond_cols    = _present(fields, _CONDITION_COLUMNS)
        sfid_cols    = _present(fields, _SCRYFALL_COLUMNS)
        known = {c for c in [name_col, count_col, *code_cols, *generic_cols, *cn_cols,
                             *finish_cols, *lang_cols, *cond_cols, *sfid_cols,
                             *_present(fields, _CONSUMED)] if c}
        for row in reader:
            name = (row.get(name_col) or "").strip() if name_col else ""
            try:
                cnt = int(float((row.get(count_col) or "1").strip())) if count_col else 1
            except (TypeError, ValueError):
                cnt = 1
            extra = {k: v for k, v in row.items()
                     if k and k not in known and (v or "").strip()}
            set_code = (_first(row, code_cols)
                        or _first(row, generic_cols, _looks_like_code))
            _add(name, max(cnt, 1), set_code, _first(row, cn_cols),
                 _first(row, finish_cols), _first(row, lang_cols), _first(row, cond_cols),
                 _first(row, sfid_cols), extra)
    else:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "//")):
                continue
            if ":" in line.split(" ", 1)[0]:
                line = line.split(":", 1)[1].strip()
            p = parse_decorated_line(line)
            # The exporter's "[Land]"/"[Ramp]" tag is a deckbuilding CATEGORY, not
            # collection data, so it is read off the line and discarded. The finish
            # marker (*F*/*E*) is real per-copy data and becomes the row's finish.
            _add(p["name"], max(p["qty"] or 1, 1), p["set"], p["cn"], p["finish"])
    return rows
