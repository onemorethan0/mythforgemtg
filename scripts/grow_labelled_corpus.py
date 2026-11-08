"""Grow the bracket-labelled corpus from the sources most likely to be labelled right, then
audit every label against the official hard gates (`mythgauntlet.data.label_audit`).

    python scripts/grow_labelled_corpus.py precons              # WotC Commander precons -> Bracket 2
    python scripts/grow_labelled_corpus.py archidekt --pages 5  # self-labelled, most-viewed first
    python scripts/grow_labelled_corpus.py audit                # demote labels the gates forbid
    python scripts/grow_labelled_corpus.py audit --dry-run

SOURCES, strongest first:
  * Official Commander precons (MTGJSON deck files, one per product; reprint/collector editions
    with an identical list are written once). Wizards' own bracket announcement places
    preconstructed decks at Bracket 2; the audit then removes any precon whose list the
    Bracket 2 gates forbid (a precon with a Game Changer is not counted as a Bracket 2 anchor).
  * Archidekt decks whose builder set `edhBracket`, most-viewed first -- a popular list has had
    the most eyes on its label. Each label still has to survive the audit.
  * Not used: the cEDH Decklist Database (every list links to Moxfield, whose API needs a
    pre-approved User-Agent) and EDHREC bracket averages (an average of many lists is not a
    deck anyone labelled).

NETWORK: MTGJSON, Archidekt (throttled, unauthenticated, as `fetch-decks`), and Commander
Spellbook for the audit's two-card-combo gate (cached by decklist). No LLM, no GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from mythgauntlet.config import USER_AGENT, corpus_dir  # noqa: E402
from mythgauntlet.data import decksources, label_audit  # noqa: E402
from mythgauntlet.model.deck import Deck  # noqa: E402

MTGJSON = "https://mtgjson.com/api/v5"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


# --- manifest ------------------------------------------------------------------------------


def _load_manifest(out: Path) -> dict:
    path = out / "manifest.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"decks": []}


def _save_manifest(out: Path, manifest: dict) -> None:
    manifest["decks"] = sorted(manifest["decks"], key=lambda e: e["file"])
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                       encoding="utf-8")


def _standard(text: str) -> bool:
    """Same gate `fetch-decks` applies: a commander and 95-102 cards."""
    parsed = Deck.parse_text(text)
    return bool(parsed.commanders) and 95 <= parsed.total_cards <= 102


def _write(out: Path, by_file: dict, slug: str, name: str, source: str, text: str,
           bracket: int | None) -> bool:
    if not _standard(text):
        print(f"  skip {slug}: not a standard Commander list", flush=True)
        return False
    (out / f"{slug}.txt").write_text(text, encoding="utf-8", newline="\n")
    by_file[f"{slug}.txt"] = {"file": f"{slug}.txt", "name": name, "source": source,
                              "bracket": bracket, "fetched": date.today().isoformat()}
    return True


# --- precons -------------------------------------------------------------------------------


def _get(url: str) -> dict:
    time.sleep(0.2)
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def precon_text(deck: dict) -> tuple[str, list[str], list[tuple[str, int]]]:
    commanders = [c["name"] for c in deck.get("commander") or []]
    entries: Counter = Counter()
    for c in deck.get("mainBoard") or []:
        entries[c["name"]] += int(c.get("count") or 1)
    title = f"WotC precon — {deck['name']} ({deck.get('code', '')}, {deck.get('releaseDate', '')})"
    body = [f"# {title}", f"# source: mtgjson:{deck['fileName']}",
            f"# fetched: {date.today().isoformat()}", "# bracket: 2",
            "# label_source: Wizards places preconstructed Commander decks at Bracket 2", "",
            "Commander:", *[f"1 {n}" for n in commanders], "", "Deck:",
            *[f"{n} {name}" for name, n in sorted(entries.items())], ""]
    return "\n".join(body), commanders, sorted(entries.items())


def cmd_precons(args) -> int:
    out = corpus_dir()
    manifest = _load_manifest(out)
    by_file = {e["file"]: e for e in manifest["decks"]}
    listing = [d for d in _get(f"{MTGJSON}/DeckList.json")["data"] if d["type"] == "Commander Deck"]
    seen: set = set()
    wrote = 0
    for meta in sorted(listing, key=lambda d: d["releaseDate"]):
        slug = f"precon-{meta['fileName']}"
        try:
            deck = _get(f"{MTGJSON}/decks/{meta['fileName']}.json")["data"]
        except requests.RequestException as exc:
            print(f"  {slug}: fetch failed ({exc})", flush=True)
            continue
        deck["fileName"] = meta["fileName"]
        text, commanders, entries = precon_text(deck)
        key = (tuple(sorted(commanders)), tuple(entries))
        if key in seen:           # a collector's/reprint edition of a list already written
            continue
        seen.add(key)
        if f"{slug}.txt" in by_file and not args.refresh:
            continue
        if _write(out, by_file, slug, deck["name"], f"mtgjson:{meta['fileName']}", text, 2):
            wrote += 1
    manifest["decks"] = list(by_file.values())
    _save_manifest(out, manifest)
    print(f"precons: {len(seen)} distinct lists, {wrote} written")
    return 0


# --- archidekt -----------------------------------------------------------------------------


def cmd_archidekt(args) -> int:
    out = corpus_dir()
    manifest = _load_manifest(out)
    by_file = {e["file"]: e for e in manifest["decks"]}
    brackets = [int(b) for b in args.brackets.split(",")]
    for b in brackets:
        wrote = 0
        for page in range(1, args.pages + 1):
            try:
                metas = decksources.archidekt_top(page_size=60, order=args.order, bracket=b,
                                                  page=page)
            except requests.RequestException as exc:
                print(f"  B{b} page {page}: search failed ({exc})", flush=True)
                break
            if not metas:
                break
            for meta in metas:
                if f"archidekt-{meta.id}.txt" in by_file or meta.view_count < args.min_views:
                    continue
                try:
                    deck = decksources.fetch_archidekt_deck(meta.id)
                except requests.RequestException as exc:
                    print(f"  archidekt-{meta.id}: fetch failed ({exc})", flush=True)
                    continue
                if deck.bracket != b:      # label changed since the search indexed it
                    continue
                if _write(out, by_file, deck.slug, deck.name, deck.source, deck.text, deck.bracket):
                    wrote += 1
            manifest["decks"] = list(by_file.values())
            _save_manifest(out, manifest)    # resumable: progress lands every page
            print(f"  B{b} page {page}: {wrote} new so far", flush=True)
    return 0


# --- audit ---------------------------------------------------------------------------------


def cmd_audit(args) -> int:
    from bracket_accuracy import real_combo_lookup
    from mythgauntlet.data.scryfall import load_card_db
    from mythgauntlet.model.deck import resolve

    out = corpus_dir()
    db = load_card_db()
    manifest = _load_manifest(out)
    by_file = {e["file"]: e for e in manifest["decks"]}
    kept: Counter = Counter()
    dropped: Counter = Counter()
    why: Counter = Counter()
    unchecked = 0
    for path in sorted(out.glob("*.txt")):
        original = path.read_text(encoding="utf-8")
        text = label_audit.unmark(original)      # re-judge earlier verdicts under today's rules
        m = label_audit.LABEL_RE.search(text)
        if not m:
            continue
        label = int(m.group(1))
        try:
            resolved = resolve(Deck.parse_text(text), db)
        except Exception as exc:   # noqa: BLE001 - one bad file must not stop the audit
            print(f"  {path.name}: unresolvable ({exc})", flush=True)
            continue
        report, failed = real_combo_lookup(resolved, path.name)
        unchecked += failed
        result = label_audit.audit_resolved(resolved, label, report)
        (kept if result.ok else dropped)[label] += 1
        for r in result.reasons:
            kind = next((k for k in ("Game Changers", "two-card") if k in r), "other")
            why[f"B{label}: {kind}"] += 1
        if args.verbose and not result.ok:
            print(f"  {path.name} [B{label}]: " + "; ".join(result.reasons), flush=True)
        final = label_audit.mark(text, result)
        if args.dry_run or final == original:
            continue
        path.write_text(final, encoding="utf-8", newline="\n")
        entry = by_file.get(path.name)
        if entry is not None:
            entry.pop("bracket_claimed", None)
            entry.pop("label_audit", None)
            if result.ok:
                entry["bracket"] = label
            else:
                entry["bracket"] = None
                entry["bracket_claimed"] = label
                entry["label_audit"] = "; ".join(result.reasons)
    if not args.dry_run:
        manifest["decks"] = list(by_file.values())
        _save_manifest(out, manifest)
    print(f"{'(dry run) ' if args.dry_run else ''}kept per bracket {dict(sorted(kept.items()))}; "
          f"demoted {dict(sorted(dropped.items()))}; combo lookup failed for {unchecked}")
    for k, v in why.most_common():
        print(f"  {v:4}  {k}")
    return 0


def main() -> int:
    for attr in ("stdout", "stderr"):
        getattr(sys, attr).reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("precons")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_precons)
    p = sub.add_parser("archidekt")
    p.add_argument("--pages", type=int, default=5, help="60 decks a page, per bracket")
    p.add_argument("--brackets", default="1,2,3,4,5")
    p.add_argument("--order", default="-viewCount")
    p.add_argument("--min-views", type=int, default=0)
    p.set_defaults(func=cmd_archidekt)
    p = sub.add_parser("audit")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_audit)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
