"""Regenerate `mythgauntlet.ratings.redundancy.ROLE_TARGETS` from real decks.

A redundancy detector answers "what does this deck have too MUCH of", so its targets have
to say what "too much" means. The first version borrowed them from the BUILDER's slot plan
(`playstyle.DEFAULT_SLOTS`) — the app's opinion of a deck it is about to construct — and
that turned out to be the wrong baseline for judging a deck someone already owns.

Measured over 120 corpus decks, the builder's plan sits BELOW the population median for
ramp and draw and ABOVE it for removal and wipe, so nearly every deck read as
draw/ramp-oversupplied and essentially none ever read as removal-oversupplied:

    role          plan   median supply
    ramp            10            12.0
    draw            10            14.5
    removal          7             4.0
    wipe             4             3.0
    counterspell     3             0.0

The consequence was a systematically lopsided cut pool — draw 48.7% and ramp 34.5% of
every suggestion, against removal 1.5% and wipe 1.0%. That is an artifact of the baseline,
not a judgement about any particular deck.

Targets are now the 60th percentile of what real decks actually supply, so a role has to
clear a modest evidential bar (above ~60% of decks) before it counts as over-served.
Swept, not chosen — top-role share of the cut pool:

    current  48.7%    draw+ramp 83.2%   removal+wipe  2.5%
    p50      34.9%    draw+ramp 63.8%   removal+wipe 12.3%
    p60      32.8%    draw+ramp 57.8%   removal+wipe 17.1%   <- knee
    p75      30.4%    draw+ramp 55.7%   removal+wipe 16.4%

p75 barely improves on p60 while pushing targets so high (ramp 18, draw 20) that little
would ever flag.

THE SAMPLE IS NOW THE WHOLE CORPUS, and that changed an answer. The sweep above ran under a
`DECKS = 120` cap; the corpus has since reached 499. Re-measured over all of them, `tutor`
moves 2 -> 4 and nothing else moves at all. Tutors were therefore judged against half their
real population target, and the module over-flagged them: 13.8% of every cut suggestion
against 10.6% after, with the pool changing on 16% of decks.

`--check` could not have caught this, because it re-measured under the SAME cap the constant
was generated from and so could only ever agree with itself. See `DECKS` below.

    python scripts/role_targets.py             # print the table
    python scripts/role_targets.py --check     # diff against the baked-in constant
    python scripts/role_targets.py --limit 120 # the old sample, for comparison

Needs data/cards_slim.json (gitignored), so it is not CI-safe.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings import redundancy  # noqa: E402

PERCENTILE = 0.60
MIN_TARGET = 2      # a floor: counterspell's median is 0.0, and "any counterspell is
                    # redundant" is obviously wrong.

# ALL of them. This used to be `DECKS = 120`, a cap that predates the corpus reaching 499
# decks, and it silently mis-measured `tutor`: p60 over the first 120 is 2.0, over all 499
# it is 4.0. Every other role is identical, so the cap looked harmless.
#
# The cap was invisible because `--check` INHERITS IT. The checker re-measured with the same
# 120-deck sample the constant was generated from, re-derived 2, and reported "ROLE_TARGETS
# is current" — a self-confirming test that could only ever agree with itself. A calibration
# checker has to be able to disagree with the baked value, and this one structurally could
# not. Confirmed a population fact, not a shuffle: three disjoint thirds of the corpus each
# give tutor p60 = 4.0 independently.
#
# `--limit` is kept for a fast run while iterating; it is not the default.
DECKS = None


def measure(percentile: float = PERCENTILE, decks: int | None = DECKS) -> dict[str, int]:
    db = load_card_db()
    supplies: dict[str, list[float]] = {r: [] for r in redundancy.ROLE_TARGETS}
    seen = 0
    for path in sorted((Path(__file__).resolve().parents[1] / "corpus" / "decks").glob("*.txt")):
        deck = Deck.parse_text(path.read_text(encoding="utf-8"))
        resolved = resolve(deck, db)
        if resolved.card_count < 90:
            continue
        supply = redundancy.role_supply(resolved)
        for role in supplies:
            supplies[role].append(supply.get(role, 0.0))
        seen += 1
        if decks is not None and seen >= decks:
            break
    out = {}
    for role, values in supplies.items():
        ordered = sorted(values)
        idx = min(len(ordered) - 1, int(percentile * len(ordered)))
        out[role] = max(MIN_TARGET, round(ordered[idx]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--percentile", type=float, default=PERCENTILE)
    ap.add_argument("--limit", type=int, default=DECKS,
                    help="stop after N corpus decks (default: all of them)")
    args = ap.parse_args()
    targets = measure(args.percentile, args.limit)

    if args.check:
        drift = {r: (redundancy.ROLE_TARGETS.get(r), v) for r, v in sorted(targets.items())
                 if redundancy.ROLE_TARGETS.get(r) != v}
        for role, (was, now) in drift.items():
            print(f"DRIFT {role}: baked {was} measured {now}")
        print("ROLE_TARGETS is current." if not drift else "ROLE_TARGETS needs regenerating.")
        return 0 if not drift else 1

    print("ROLE_TARGETS: dict[str, int] = {")
    for role, value in targets.items():
        print(f'    "{role}": {value},')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
