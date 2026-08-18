"""Measure the UPGRADE ADVISOR end to end, the way builder_bench measures the builder.

`advisor.advise` picks swaps by re-simulating the deck, and its cut pool changed on
2026-08-14 from "least played" (`CUT_POPULARITY`) to "what the deck has too much of"
(`CUT_REDUNDANT`). That change shipped on a conceptual argument with no end-to-end
measurement behind it. This is the measurement.

    python scripts/advisor_bench.py --decks 30
    python scripts/advisor_bench.py --decks 10 --show-cuts

WHAT IT FOUND, and why both numbers matter (30 corpus decks, full-fidelity store):

    cut POOLS differ on            29/30 decks
    total measured gain            237.92 (redundant) vs 209.38 (popularity)
    decks helped                   13 vs 12
    head-to-head                   redundant better on 6, WORSE on 6, tied on 18

By the simulation's own axis delta the two strategies are roughly equivalent. That is
not a null result to bury — it says the delta metric CANNOT SEE the defect, because
`advise` tests every add against the whole pool and keeps the best-measuring pairing, so
the simulation partly rescues a bad cut pool.

What reaches the USER differs sharply, and `--show-cuts` is how you see it:

    Shelob (spiders)   popularity cuts "Eaten by Spiders", "Gloomwidow's Feast"
    Sefris (reanimator) popularity cuts "Living End", a reanimator payoff
    ...redundant suggests neither, offering redundant looters instead.

So the redundancy pool is justified on ADVICE QUALITY — which is why it was built — and
NOT on measured axis delta, which does not support it. Both halves are the finding.

NOT CI-SAFE: needs data/cards_slim.json and a semantics store (MYTHGAUNTLET_STORE), both
gitignored. Same status as builder_bench, which needs the network.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import builder_bench  # noqa: E402  (reuses the synthetic collection)
from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings import advisor  # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore  # noqa: E402
from mythgauntlet.sim.tier0 import SimConfig  # noqa: E402

STRATEGIES = (advisor.CUT_REDUNDANT, advisor.CUT_POPULARITY)


def load_decks(db, limit: int) -> list[tuple[str, object]]:
    """Complete corpus decks, in a fixed order so two runs are comparable."""
    out = []
    for path in sorted((Path(__file__).resolve().parents[1] / "corpus" / "decks").glob("*.txt")):
        deck = Deck.parse_text(path.read_text(encoding="utf-8"))
        if not deck.commanders:
            continue
        resolved = resolve(deck, db)
        if resolved.card_count >= 90:
            out.append((deck.commanders[0], resolved))
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", type=int, default=30)
    ap.add_argument("--candidates", type=int, default=500)
    ap.add_argument("--show-cuts", action="store_true",
                    help="print what each strategy suggests CUTTING — the difference the "
                         "axis delta cannot show")
    ap.add_argument("--runs", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    db = load_card_db()
    store = SemanticsStore()
    print(f"semantics store: {len(store._by_name)} cards")
    owned = sorted(builder_bench.synthetic_collection())
    candidates = [c for c in (db.get(n) for n in owned) if c is not None][:args.candidates]
    decks = load_decks(db, args.decks)
    cfg = SimConfig(turns=8, runs=args.runs, seed=args.seed)
    print(f"decks: {len(decks)}   candidate pool: {len(candidates)}\n")

    gains: dict[str, list[float]] = {s: [] for s in STRATEGIES}
    pools: dict[str, list[set]] = {s: [] for s in STRATEGIES}
    for name, resolved in decks:
        reports = {}
        for strat in STRATEGIES:
            rep = advisor.advise(resolved, cfg, store, candidates, top=5, max_eval=10,
                                 cut_pool=3, cut_strategy=strat)
            reports[strat] = rep
            gains[strat].append(sum(s.delta for s in rep.suggestions))
            pools[strat].append({c.name for c in advisor._cut_candidates(resolved, 3, strat)})
        if args.show_cuts and any(r.suggestions for r in reports.values()):
            print(f"{name[:38]}  (axis {reports[STRATEGIES[0]].axis})")
            for strat, rep in reports.items():
                cuts = [s.cut for s in rep.suggestions]
                print(f"   {strat:11} cuts: {cuts or '(none)'}")

    print()
    for strat in STRATEGIES:
        g = gains[strat]
        print(f"{strat:11} decks helped {sum(1 for v in g if v > 0):3}/{len(g)}   "
              f"total gain {sum(g):8.2f}   mean/deck {statistics.fmean(g):5.2f}")

    a, b = STRATEGIES
    differ = sum(1 for x, y in zip(pools[a], pools[b]) if x != y)
    better = sum(1 for x, y in zip(gains[a], gains[b]) if x > y + 1e-9)
    worse = sum(1 for x, y in zip(gains[a], gains[b]) if y > x + 1e-9)
    print(f"\ncut POOLS differ on {differ}/{len(decks)} decks")
    print(f"{a} vs {b}: better on {better}, worse on {worse}, "
          f"tied on {len(decks) - better - worse}")
    print("\nA tie on axis delta is NOT a null result — see the module docstring. Run with "
          "--show-cuts for the difference that matters.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
