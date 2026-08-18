"""Which cards the strength engine can actually reason about, and which it guesses at.

The engine executes a compiled CCM when it has one and falls back to rung-1 Oracle-text
heuristics when it does not. `docs/ENGINE_DATA.md` reports the headline number; this reports
the part that decides whether a bracket is trustworthy — **which** cards are missing.

    python scripts/ccm_coverage.py                 # pool coverage, worst-covered bands
    python scripts/ccm_coverage.py --top 300       # uncompiled cards among the N most played
    python scripts/ccm_coverage.py --deck <file>   # coverage for one decklist

Read `card.name` out of every stored CCM rather than trusting filenames: the store slugifies
names, so a filename check mangles double-faced cards and punctuation (it under-reported
coverage by 2.4 points), and grepping for a name matches the nested ability names inside a CCM.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def store_dirs() -> list[Path]:
    """BOTH tiers, exactly as `SemanticsStore.__init__` reads them.

    Reading only `compiled/` was a real bug in the first version of this script, and it
    produced a dramatic wrong answer: the 14 hand-authored **rung 3** CCMs — Sol Ring,
    Counterspell, Command Tower, Swords to Plowshares, Rhystic Study, Demonic Tutor,
    Lightning Bolt and friends — came back as "uncompiled", which read as the engine
    guessing at the format's most-played cards. They are the opposite: the highest-quality
    tier in the store, hand-written rather than model-compiled, which is exactly why
    `compile-top` skips them and why they never appear in the ledger.

    They also live in a DIFFERENT PLACE — `authored/` sits in this repo while `compiled/`
    follows MYTHGAUNTLET_STORE — so a check that assumes one root silently misses a whole
    rung. Same class of mistake as the two-structures bugs this file's siblings keep finding.
    """
    from mythgauntlet.semantics import compiler  # noqa: PLC0415 — optional engine import
    return [compiler.compiled_dir(), compiler.authored_dir()]


def compiled_names(dirs: list[Path]) -> set[str]:
    names: set[str] = set()
    for p in [f for d in dirs if d.is_dir() for f in d.glob("*.json")]:
        try:
            card = (json.loads(p.read_text(encoding="utf-8")).get("card") or {})
        except Exception:          # noqa: BLE001 — a corrupt CCM is a gap, not a crash
            continue
        n = card.get("name")
        if isinstance(n, str):
            names.add(n)
            names.add(n.split(" // ")[0])
    return names


def covered(name: str, names: set[str]) -> bool:
    return name in names or name.split(" // ")[0] in names


def load_pool() -> list[dict]:
    p = ROOT / "data" / "cards_slim.json"
    if not p.exists():
        raise SystemExit("data/cards_slim.json missing — run the fetch first.")
    return json.loads(p.read_text(encoding="utf-8"))["cards"]


_QTY = re.compile(r"^\s*(\d+)\s*x?\s+(.*)$", re.I)


def deck_names(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _QTY.match(s)
        name = (m.group(2) if m else s).strip()
        name = re.sub(r"\s*\([^)]*\)\s*\d*$", "", name).strip()
        if name and not name.rstrip(":").casefold() in (
                "commander", "deck", "sideboard", "maybeboard"):
            out.append(name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0,
                    help="list uncompiled cards among the N most-played")
    ap.add_argument("--deck", type=Path, help="report coverage for one decklist file")
    args = ap.parse_args()

    names = compiled_names(store_dirs())
    pool = load_pool()
    print(f"CCM names indexed (compiled + authored): {len(names)}")

    if args.deck:
        wanted = deck_names(args.deck)
        miss = [n for n in wanted if not covered(n, names)]
        pct = 100 * (len(wanted) - len(miss)) / max(1, len(wanted))
        print(f"\n{args.deck.name}: {len(wanted) - len(miss)}/{len(wanted)} covered ({pct:.0f}%)")
        # A bracket derived from a deck whose staples are uncompiled deserves less weight,
        # which is the whole reason this is worth reporting per deck.
        for n in miss:
            print("   uncompiled:", n)
        return 0

    hit = sum(1 for c in pool if covered(c["name"], names))
    print(f"pool {len(pool)} · covered {hit} ({100*hit/len(pool):.1f}%)")

    ranked = sorted((c for c in pool if isinstance(c.get("edhrec_rank"), int)),
                    key=lambda c: c["edhrec_rank"])
    print(f"\n{'popularity band':<22}{'cards':>7}{'covered':>9}{'coverage':>10}")
    print("-" * 48)
    for lo, hi in [(0, 100), (100, 500), (500, 1000), (1000, 5000), (5000, len(ranked))]:
        chunk = ranked[lo:hi]
        if not chunk:
            continue
        n = sum(1 for c in chunk if covered(c["name"], names))
        print(f"{f'top {lo}-{hi}':<22}{len(chunk):>7}{n:>9}{100*n/len(chunk):>9.1f}%")

    if args.top:
        miss = [c["name"] for c in ranked[:args.top] if not covered(c["name"], names)]
        print(f"\nuncompiled among the {args.top} most-played: {len(miss)}")
        for n in miss:
            print("   ", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
