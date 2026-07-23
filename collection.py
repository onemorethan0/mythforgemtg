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


def load_collection(path: Path | None = None) -> list[dict]:
    """Owned cards as an ordered list of {"name": str, "count": int}.

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
    """Persist the collection as a `Count,Name` CSV (Moxfield shape), backing up the
    previous file to `<name>.bak` first. Rows with count<=0 are dropped. Returns the
    number of distinct cards written."""
    p = path or suite_collection_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            (p.with_suffix(p.suffix + ".bak")).write_bytes(p.read_bytes())
        except OSError:
            pass
    clean = [r for r in rows if int(r.get("count", 0)) > 0 and (r.get("name") or "").strip()]
    # utf-8-sig so Excel and MythScanner (which reads utf-8-sig) both open it cleanly.
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Count", "Name"])
        for r in clean:
            w.writerow([int(r["count"]), r["name"].strip()])
    return len(clean)


def _find_row(rows: list[dict], name: str) -> dict | None:
    k = owned_key(name)
    return next((r for r in rows if owned_key(r["name"]) == k), None)


def add_card(name: str, count: int = 1, path: Path | None = None,
             display_name: str | None = None) -> list[dict]:
    """Add `count` copies of a card (merging into an existing entry). `display_name`
    (e.g. the Scryfall-canonical spelling) overrides how a new entry is stored.
    Returns the updated collection."""
    rows = load_collection(path)
    existing = _find_row(rows, name)
    if existing:
        existing["count"] += max(int(count), 1)
        if display_name:
            existing["name"] = display_name
    else:
        rows.append({"name": (display_name or name).strip(), "count": max(int(count), 1)})
    write_collection(rows, path)
    return rows


def set_count(name: str, count: int, path: Path | None = None) -> list[dict]:
    """Set a card's exact count. count<=0 removes it. Returns the updated collection."""
    rows = load_collection(path)
    existing = _find_row(rows, name)
    if existing:
        if int(count) <= 0:
            rows = [r for r in rows if r is not existing]
        else:
            existing["count"] = int(count)
    elif int(count) > 0:
        rows.append({"name": name.strip(), "count": int(count)})
    write_collection(rows, path)
    return rows


def remove_card(name: str, path: Path | None = None) -> list[dict]:
    """Remove a card entirely. Returns the updated collection."""
    rows = [r for r in load_collection(path) if owned_key(r["name"]) != owned_key(name)]
    write_collection(rows, path)
    return rows


def bulk_import(text: str, mode: str = "merge", path: Path | None = None) -> list[dict]:
    """Import a pasted CSV or decklist. mode="merge" adds counts onto the current
    collection; mode="replace" overwrites it. Returns the updated collection."""
    # Reuse load_collection's parser by round-tripping the pasted text through a temp
    # in-memory parse: write to a scratch parse via the same logic.
    incoming = _parse_rows(text)
    if mode == "replace":
        merged = incoming
    else:
        merged = load_collection(path)
        for r in incoming:
            existing = _find_row(merged, r["name"])
            if existing:
                existing["count"] += r["count"]
            else:
                merged.append(dict(r))
    write_collection(merged, path)
    return merged


def _parse_rows(text: str) -> list[dict]:
    """Parse pasted CSV/decklist text into [{"name","count"}] (no file I/O)."""
    import io
    # Delegate to load_collection's parsing by temporarily treating text as file
    # content: replicate its branching here without touching disk.
    stripped = text.lstrip()
    first_line = stripped.splitlines()[0] if stripped else ""
    rows: dict[str, dict] = {}
    order: list[str] = []

    def _add(name: str, count: int) -> None:
        name = (name or "").strip()
        if not name:
            return
        k = owned_key(name)
        if k in rows:
            rows[k]["count"] += count
        else:
            rows[k] = {"name": name, "count": count}
            order.append(k)

    if "," in first_line and _find_column(first_line.split(","), _NAME_COLUMNS):
        reader = csv.DictReader(io.StringIO(text))
        name_col = _find_column(reader.fieldnames or [], _NAME_COLUMNS)
        count_col = _find_column(reader.fieldnames or [], _COUNT_COLUMNS)
        for row in reader:
            name = (row.get(name_col) or "").strip() if name_col else ""
            try:
                cnt = int(float((row.get(count_col) or "1").strip())) if count_col else 1
            except (TypeError, ValueError):
                cnt = 1
            _add(name, max(cnt, 1))
    else:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "//")):
                continue
            if ":" in line.split(" ", 1)[0]:
                line = line.split(":", 1)[1].strip()
            cnt = 1
            parts = line.split(" ", 1)
            if parts[0].isdigit() and len(parts) > 1:
                cnt = max(int(parts[0]), 1)
                line = parts[1].strip()
            line = line.split("(", 1)[0].strip()
            _add(line, cnt)
    return [rows[k] for k in order]
