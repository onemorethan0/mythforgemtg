"""Calibrate `advisor._AXIS_NOISE_FLOOR` — the run-to-run spread of each axis.

    python scripts/axis_noise.py            # print the constant
    python scripts/axis_noise.py --check    # diff it against the baked values

Why this exists. The advisor refuses to suggest a swap whose measured gain is smaller than the
axis's own seed-to-seed spread, because such a "gain" is indistinguishable from re-rolling the
RNG on an unchanged deck. That floor was a flat constant, and two things were wrong with it:

**It was measured at runs=150 while every caller uses runs=60.** Simulation noise falls roughly
as 1/sqrt(runs), so a floor calibrated at 150 is about 1.6x too low at 60 — it admits exactly
the noise it exists to exclude. Measured on unchanged decks at 8 seeds:

    axis          sd @60    sd @150    old floor
    speed           3.46       2.41          1.7
    ceiling         2.44       2.98          2.3
    consistency     1.40       0.89          0.9
    resilience      1.91       1.24          0.0
    interaction     0.00       0.00          0.0

**`resilience` was floored at 0.0, which is why that number looked so clean.** The original
sweep called `analyze_deck` without `run_resilience`, so resilience was not simulated at all and
came back constant. It is only ever simulated when it IS the target axis — precisely when the
floor is consulted — and there its real spread is ~1.9 at runs=60. A floor of zero means every
positive resilience delta passes, so resilience advice was unfiltered noise.

The floor is therefore stored at a REFERENCE run count and scaled per call.
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from mythgauntlet.data.scryfall import load_card_db          # noqa: E402
from mythgauntlet.ratings import advisor                     # noqa: E402
from mythgauntlet.ratings.advisor import axis_score          # noqa: E402
from mythgauntlet.ratings.analysis import analyze_deck       # noqa: E402
from mythgauntlet.semantics.store import SemanticsStore      # noqa: E402
from mythgauntlet.sim.tier0 import SimConfig                 # noqa: E402
from advisor_bench import load_decks                         # noqa: E402

AXES = ("speed", "ceiling", "consistency", "resilience", "interaction")
SEEDS = [7, 21, 99, 123, 5, 42, 77, 2024]


def measure(decks_n: int, runs: int) -> dict[str, float]:
    db = load_card_db()
    store = SemanticsStore()
    decks = load_decks(db, decks_n)
    per_axis: dict[str, list[float]] = {a: [] for a in AXES}
    for _name, resolved in decks:
        scores: dict[str, list[float]] = {a: [] for a in AXES}
        for seed in SEEDS:
            # run_resilience=True is the whole point: the original sweep left it off, so
            # resilience was never simulated and its spread read as a clean 0.00.
            a = analyze_deck(resolved, SimConfig(turns=8, runs=runs, seed=seed), store,
                             run_resilience=True)
            for ax in AXES:
                scores[ax].append(axis_score(a, ax))
        for ax in AXES:
            per_axis[ax].append(statistics.pstdev(scores[ax]))
    # The MEAN per-deck spread, not the max: the floor should reflect the typical deck, and a
    # single pathological deck should not silence advice on every other one.
    return {ax: round(statistics.fmean(v), 2) for ax, v in per_axis.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", type=int, default=8)
    ap.add_argument("--runs", type=int, default=advisor.NOISE_REFERENCE_RUNS)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    measured = measure(args.decks, args.runs)
    if args.check:
        drift = {a: (advisor._AXIS_NOISE_FLOOR.get(a), v) for a, v in sorted(measured.items())
                 if abs(advisor._AXIS_NOISE_FLOOR.get(a, 0.0) - v) > 0.25}
        for axis, (was, now) in drift.items():
            print(f"DRIFT {axis}: baked {was} measured {now}")
        print("_AXIS_NOISE_FLOOR is current." if not drift
              else "_AXIS_NOISE_FLOOR needs regenerating.")
        return 0 if not drift else 1

    print(f"# measured at runs={args.runs}, {args.decks} decks, {len(SEEDS)} seeds")
    print("_AXIS_NOISE_FLOOR = {")
    for axis, value in measured.items():
        print(f'    "{axis}": {value},')
    print("}")
    print(f"\n# scaled to runs=60: "
          + ", ".join(f"{a} {v * math.sqrt(args.runs / 60):.2f}" for a, v in measured.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
