"""Cluster the 'other' note-only statics by template, to see whether the bucket is one big pile or a
few parseable shapes (B3). Normalises numbers, mana symbols, quoted text and the card's own name,
then groups by the first words.

    PYTHONPATH=src python scripts/static_clusters.py [--top 40] [--words 5]
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import static_scan  # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore  # noqa: E402


def shape(note: str, name: str, words: int) -> str:
    n = note.strip().rstrip(".")
    n = re.sub(re.escape(name.split(",")[0]), "~", n, flags=re.I) if name else n
    n = re.sub(r"\{[^}]+\}", "{M}", n)
    n = re.sub(r"[+-]?\d+(?:/[+-]?\d+)?", "N", n)
    n = re.sub(r"\"[^\"]*\"|'[^']*'", "\"Q\"", n)
    n = re.sub(r"\b(?:Equipped|Enchanted) creature\b", "ATTACHED", n)
    return " ".join(n.lower().split()[:words])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--words", type=int, default=5)
    args = ap.parse_args()
    store = SemanticsStore()
    c: collections.Counter = collections.Counter()
    ex: dict[str, tuple[str, str]] = {}
    total = 0
    for name, sem in store._by_name.items():
        for ab in (sem.ccm or {}).get("abilities") or []:
            if ab.get("kind") != "static" or ab.get("effects"):
                continue
            note = (ab.get("note") or "").strip()
            if not note or static_scan.bucket(note) != "other":
                continue
            total += 1
            card = (sem.ccm or {}).get("name", name)
            k = shape(note, card, args.words)
            c[k] += 1
            ex.setdefault(k, (card, note[:100]))
    print(f"'other' note-only statics: {total}; distinct {args.words}-word shapes: {len(c)}")
    covered = 0
    for k, n in c.most_common(args.top):
        covered += n
        print(f"{n:5d}  {k:<42} e.g. {ex[k][0]}: {ex[k][1]!r}")
    print(f"\ntop {args.top} shapes cover {covered} of {total} ({100 * covered / total:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
