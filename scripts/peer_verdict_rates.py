"""B37 acceptance: how often each strength/weakness line fires, per bracket.

Reads the per-deck rows `bracket_axis_reference.py` cached (metrics + the ESTIMATED bracket),
aggregates the reference exactly as the bake does, then runs `insight._verdict` on a duck-typed
analysis per deck -- the deck is ranked against the bracket the engine estimates for it, as the
app does. Prints, per estimated bracket, the share of decks each line fires for, beside the
pre-B37 fixed bars on the same rows. The spec's bar: each strength line fires for 15-35%.

    python scripts/peer_verdict_rates.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from bracket_accuracy import labelled_decks  # noqa: E402
from bracket_axis_reference import DEFAULT_CACHE, aggregate, load_cache  # noqa: E402
from mythgauntlet.ratings import insight, reference  # noqa: E402

TOPICS = ("Consistency", "Interaction", "Ceiling", "Wipe resilience", "Multiplayer closing power")
OLD_BARS = {"Consistency": ("consistency", 80, 45), "Interaction": ("interaction", 55, 30),
            "Ceiling": ("ceiling", 45, 5.0001), "Wipe resilience": ("resilience", 60, 42),
            "Multiplayer closing power": ("pod", 55, None)}


def _analysis(m: dict) -> SimpleNamespace:
    return SimpleNamespace(
        report=SimpleNamespace(consistency_score=m["consistency"], avg_commander_turn=4.0),
        interaction=SimpleNamespace(score=m["interaction"], breadth=2, breadth_max=3),
        ceiling=SimpleNamespace(score=m["ceiling"]),
        resilience=SimpleNamespace(resilience_score=m["resilience"]),
        pod=SimpleNamespace(score=m["pod"], pod_close_turn=m.get("pod_close_turn", 1)),
        bracket=SimpleNamespace(bracket=m["est_bracket"]),
    )


def main() -> int:
    labels = {p.name: b for p, b in labelled_decks()}
    rows = [dict(r, label=labels[r["deck"]]) for r in load_cache(DEFAULT_CACHE).values()
            if "est_bracket" in r["metrics"] and r["deck"] in labels]
    if not rows:
        raise SystemExit(f"no rows with est_bracket in {DEFAULT_CACHE}; run the sweep first")
    if "--peers=estimated" in sys.argv:
        # peers = decks the engine RATES at the bracket, not decks LABELLED with it
        reference.BRACKET_AXIS_REFERENCE = aggregate(
            [dict(r, label=r["metrics"]["est_bracket"]) for r in rows])
    else:
        reference.BRACKET_AXIS_REFERENCE = aggregate(rows)
    new: dict[int, Counter] = defaultdict(Counter)
    old: dict[int, Counter] = defaultdict(Counter)
    n: Counter = Counter()
    for r in rows:
        m = r["metrics"]
        b = m["est_bracket"]
        n[b] += 1
        s, w = insight._verdict(_analysis(m), 0, 0, 0, 0, 0, 30, False)
        for t in TOPICS:
            new[b]["+" + t] += any(x.startswith(t) for x in s)
            new[b]["-" + t] += any(x.startswith(t) for x in w)
            metric, hi, lo = OLD_BARS[t]
            old[b]["+" + t] += m[metric] >= hi
            old[b]["-" + t] += lo is not None and m[metric] < lo
        new[b]["-No multiplayer closing power"] += any(x.startswith("No multiplayer") for x in w)
    print(f"{len(rows)} decks; share of decks per ESTIMATED bracket (new peer-ranked / old bars)")
    print(f"{'line':34}" + "".join(f"  B{b} (n={n[b]:3})" for b in sorted(n)))
    for key in [f"{sign}{t}" for sign in "+-" for t in TOPICS] + ["-No multiplayer closing power"]:
        cells = []
        for b in sorted(n):
            o = f"{old[b][key] / n[b]:4.0%}" if key in old[b] or key[1:] in OLD_BARS else "   -"
            cells.append(f"  {new[b][key] / n[b]:4.0%} / {o}")
        print(f"{key:34}" + "".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
