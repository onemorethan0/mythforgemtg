"""Measure the UPGRADE ADVISOR end to end, the way builder_bench measures the builder.

`advisor.advise` picks swaps by re-simulating the deck, and its cut pool changed on
2026-08-14 from "least played" (`CUT_POPULARITY`) to "what the deck has too much of"
(`CUT_REDUNDANT`). That change shipped on a conceptual argument with no end-to-end
measurement behind it. This is the measurement.

    python scripts/advisor_bench.py --decks 30
    python scripts/advisor_bench.py --decks 10 --show-cuts

WHAT IT FOUND — and read the seed line first (20 corpus decks, full-fidelity store):

    seed        redundant   popularity
       7           185.83       142.29
      21            79.38       136.04
      99           231.04       205.00
     123           118.96        83.75
    mean           153.80       141.77     redundant better on 3/4 seeds

RUN-TO-RUN SPREAD IS LARGER THAN THE EFFECT. A single seed ranges 79 to 231 for the same
strategy on the same decks, against a ~12-point mean difference between strategies. An
earlier revision of this file reported 237.92 vs 209.38 from ONE seed and read it as a
clean +13.6% win; that was overstated precision. Always compare means across seeds — which
is why --seeds takes a list and defaults to four.

The honest reading: the redundancy cut pool is better on 3 of 4 seeds by roughly 8%, and a
single seed can reverse it.

THE DELTA METRIC CANNOT SEE THE ACTUAL DEFECT, which is why a near-tie is not a null
result. `advise` tests every add against the WHOLE pool and keeps the best-measuring
pairing, so the simulation partly rescues a bad cut pool. What reaches the USER differs
sharply, and --show-cuts is how you see it:

    Shelob (spiders)     popularity cuts "Eaten by Spiders", "Gloomwidow's Feast"
    Ghired (tokens)      popularity cuts "Dollhouse of Horrors"
    Sefris (reanimator)  popularity cuts "Living End", a reanimator payoff

— the deck's own theme every time. So the redundancy pool is justified on ADVICE QUALITY,
which is why it was built, and only weakly by measured axis delta.

NOT CI-SAFE: needs data/cards_slim.json and a semantics store (MYTHGAUNTLET_STORE), both
gitignored. Same status as builder_bench, which needs the network.
"""

from __future__ import annotations

import argparse
import io
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _ensure_utf8_stdout() -> None:
    """A card name must not be able to kill a long run.

    Windows hands this process a cp1252 stdout and Magic prints names it cannot encode -
    AEther Vial, Lim-Dul the Necromancer, Jotun Grunt. `--show-cuts` prints card names, so
    one such card mid-run raises UnicodeEncodeError and loses everything measured so far.

    Same wrapper `image_gen` and `model3d` install; `errors="replace"` so output degrades to
    a `?` rather than ever raising.
    """
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr, None)
        if stream is None or not hasattr(stream, "buffer"):
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8" or getattr(stream, "errors", "") != "replace":
            setattr(sys, attr,
                    io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))


_ensure_utf8_stdout()

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
    ap.add_argument("--seeds", type=int, nargs="+", default=[7, 21, 99, 123, 5, 42, 77, 2024],
                    help="sim seeds to average over. NEVER report a single "
                         "seed: run-to-run spread across this roster is "
                         "LARGER than the gap between the strategies.")
    args = ap.parse_args()

    db = load_card_db()
    store = SemanticsStore()
    print(f"semantics store: {len(store._by_name)} cards")
    owned = sorted(builder_bench.synthetic_collection())
    candidates = [c for c in (db.get(n) for n in owned) if c is not None][:args.candidates]
    decks = load_decks(db, args.decks)
    print(f"decks: {len(decks)}   candidate pool: {len(candidates)}   "
          f"seeds: {args.seeds}")
    print()

    per_seed = {s: [] for s in STRATEGIES}
    pools = {s: [] for s in STRATEGIES}
    print(f"{'seed':>6} " + "".join(f"{s:>14}" for s in STRATEGIES))
    for seed in args.seeds:
        cfg = SimConfig(turns=8, runs=args.runs, seed=seed)
        row = []
        for strat in STRATEGIES:
            total = 0.0
            for name, resolved in decks:
                rep = advisor.advise(resolved, cfg, store, candidates, top=5,
                                     max_eval=10, cut_pool=3, cut_strategy=strat)
                total += sum(x.delta for x in rep.suggestions)
                if seed == args.seeds[0]:
                    pools[strat].append(
                        {c.name for c in advisor._cut_candidates(resolved, 3, strat)})
                    if args.show_cuts and rep.suggestions:
                        print(f"   {name[:28]:28} {strat:11} cuts: "
                              f"{[x.cut for x in rep.suggestions]}")
            per_seed[strat].append(total)
            row.append(total)
        print(f"{seed:>6} " + "".join(f"{v:>14.2f}" for v in row))

    print()
    # Report the STANDARD ERROR OF THE MEAN, not just the raw spread. "spread 76 - 228" reads
    # as "this number is meaningless"; the mean of n seeds is far better determined than any
    # single seed, and sem is the honest measure of how well. Measured relative sd of a single
    # seed is ~60% at runs=60, so the mean over 8 seeds carries roughly 20% error — enough to
    # rank two strategies, not enough to quote a percentage difference to two decimals.
    for strat in STRATEGIES:
        v = per_seed[strat]
        sem = statistics.pstdev(v) / max(1, len(v) ** 0.5)
        print(f"{strat:11} mean {statistics.fmean(v):8.2f} +/- {sem:6.2f} (sem)   "
              f"spread {min(v):8.2f} - {max(v):8.2f}")

    # The PAIRED difference. Both strategies run on the same seed and the same decks, so the
    # per-seed difference cancels the shared deck/seed noise that dominates each total. This is
    # the statistic the comparison should be read from — a mean difference smaller than its own
    # sem is not a result, however clean the two means look side by side.
    a_, b_ = STRATEGIES
    diffs = [x - y for x, y in zip(per_seed[a_], per_seed[b_])]
    d_mean = statistics.fmean(diffs)
    d_sem = statistics.pstdev(diffs) / max(1, len(diffs) ** 0.5)
    verdict = ("INCONCLUSIVE - the difference is within its own error"
               if abs(d_mean) <= d_sem else
               f"{a_ if d_mean > 0 else b_} better")
    print()
    print(f"paired difference ({a_} - {b_}): {d_mean:+8.2f} +/- {d_sem:.2f} (sem)   {verdict}")

    a, b = STRATEGIES
    differ = sum(1 for x, y in zip(pools[a], pools[b]) if x != y)
    wins = sum(1 for x, y in zip(per_seed[a], per_seed[b]) if x > y)
    print()
    print(f"cut POOLS differ on {differ}/{len(decks)} decks")
    print(f"{a} better on {wins}/{len(args.seeds)} seeds")
    print()
    print("SEED SPREAD IS LARGE: compare MEANS across seeds, never a single run. A tie "
          "on axis delta is also not a null result — see the module docstring, and use "
          "--show-cuts for the difference the metric cannot see.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
